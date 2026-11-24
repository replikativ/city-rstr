"""Summarize BC Assessment land and building values by Vancouver local area."""
import argparse
import csv
import json
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import duckdb
import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_region import package, read
from scripts.vancouver_transit_commutes import pointer
from scripts.vancouver_transit_load import source_digest

ASSESSMENTS = "https://opendata.vancouver.ca/explore/assets/property-tax-report/"
PARCELS = "https://opendata.vancouver.ca/explore/assets/property-parcel-polygons/"
RATES_2021 = "https://vancouver.ca/files/cov/2021-property-tax-rates.pdf"
SCHOOL_TAX = "https://www.bclaws.gov.bc.ca/civix/document/id/hstats/hstats/1482258268"
RESIDENTIAL_RATE = Decimal("0.0029225")
CENT = Decimal("0.01")
ADDITIONAL_STRATA = "strataOtherZones"
ZONES = {"One-Family Dwelling", "Two-Family Dwelling", "Multiple Dwelling"}
TYPES = {
    "One-Family Dwelling": "Land records in one-family zones",
    "Two-Family Dwelling": "Land records in two-family zones",
    "Multiple Dwelling": "Land records in multiple-dwelling zones",
    "strata": "Strata records across these residential zones",
}


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle, delimiter=";")


def parcel_areas(path, areas):
    points = []
    for row in rows(path):
        if row["tax_coord"] and row["geo_point_2d"]:
            lat, lon = map(float, row["geo_point_2d"].split(","))
            points.append((row["tax_coord"], lon, lat))
    with duckdb.connect() as db:
        db.execute("load spatial")
        db.execute("create temporary table parcels(id varchar, lon double, lat double)")
        db.executemany("insert into parcels values (?, ?, ?)", points)
        db.execute("create temporary table neighbourhood(name varchar, geom geometry)")
        db.executemany("insert into neighbourhood values (?,st_geomfromgeojson(?))",
                       [(name, json.dumps(item["geometry"])) for name, item in areas.items()])
        links = db.execute("""select distinct id,name from parcels left join neighbourhood
                             on st_covers(geom,st_point(lon,lat))""").fetchall()
    names = defaultdict(set)
    for coordinate, area in links:
        names[coordinate].add(area)
    return names


def values(pairs):
    a = np.asarray(pairs, dtype=np.int64)
    total = a.sum(axis=1)
    return dict(count=len(a), median=int(np.median(total)), quartiles=np.quantile(total, [0.25, 0.75]).astype(int).tolist(),
                medianLand=int(np.median(a[:, 0])), medianImprovements=int(np.median(a[:, 1])))


def read_levies(path, year):
    rates = {}
    for row in rows(path):
        if row["report_year"] != str(year) or row["tax_assessment_year"] != str(year):
            raise ValueError("The levy export must contain only the selected roll year")
        folio = row["folio"]
        if not folio or folio in rates:
            raise ValueError("Levy folios must be present and unique")
        rates[folio] = Decimal(row["tax_levy"]) if row["tax_levy"] else None
    return rates


def residential_levy(value, observed):
    if observed is None or observed <= 0:
        return False
    base = value * RESIDENTIAL_RATE
    school = (max(0, min(4_000_000, value) - 3_000_000) * Decimal("0.002")
              + max(0, value - 4_000_000) * Decimal("0.004"))
    # The roll can show the base levy on its own or include the school surcharge.
    return any(abs(observed - expected.quantize(CENT, rounding=ROUND_HALF_UP)) <= CENT
               for expected in (base, base + school))


def build(assessments, parcels, atlas, year, levies=None):
    if levies is not None and year != 2021:
        raise ValueError("The published residential levy comparator is for 2021")
    places = parcel_areas(parcels, atlas["areas"])
    taxes = read_levies(levies, year) if levies is not None else None
    coverage, folios = Counter(), set()
    rate_counts = Counter()
    definitions = dict(TYPES)
    if taxes is not None:
        definitions[ADDITIONAL_STRATA] = "Strata matching the residential levy in other zones"
    by_area = defaultdict(lambda: defaultdict(list))
    citywide = defaultdict(list)
    for row in rows(assessments):
        if row["report_year"] != str(year) or row["tax_assessment_year"] != str(year):
            raise ValueError("The property assessment export must contain only the selected roll year")
        folio = row["folio"]
        if not folio or folio in folios:
            raise ValueError("Assessment folios must be present and unique")
        folios.add(folio)
        zone, legal = row["zoning_classification"], row["legal_type"]
        if zone not in ZONES or legal not in {"LAND", "STRATA"}:
            if taxes is None or legal != "STRATA":
                coverage["zoningOrType"] += 1
                continue
            category = ADDITIONAL_STRATA
        else:
            category = "strata" if legal == "STRATA" else zone
        land, improvements = (int(row[k] or 0) for k in ("current_land_value", "current_improvement_value"))
        if min(land, improvements) <= 0:
            coverage["noPositiveLandOrBuildingValue"] += 1
            continue
        if category == ADDITIONAL_STRATA:
            rate_counts["tested"] += 1
            if not residential_levy(land+improvements, taxes.get(folio)):
                coverage["otherZoneWithoutRateMatch"] += 1
                continue
            rate_counts["matched"] += 1
        citywide[category].append((land, improvements))
        names = places.get(row["land_coordinate"], {None})
        if len(names) != 1:
            coverage["ambiguousLocation"] += 1
        elif None in names:
            coverage["unmappedLocation"] += 1
        else:
            area, = names
            by_area[area][category].append((land, improvements))
            coverage["mapped"] += 1
    if not by_area or sum(coverage.values()) != len(folios):
        raise ValueError("The property assessment audit could not reconcile the roll")
    if taxes is not None and folios != taxes.keys():
        raise ValueError("The property roll and levy extract have different folios")

    def summarize(categories):
        return {category: values(categories[category]) for category in definitions if categories[category]}

    report = dict(year=year, totalFolios=len(folios), definitions=definitions, coverage=coverage,
                  city=summarize(citywide), areas={area: summarize(groups) for area, groups in sorted(by_area.items())},
                  sources=[dict(source=ASSESSMENTS, **source_digest(assessments)), dict(source=PARCELS, **source_digest(parcels))])
    if taxes is not None:
        report["sources"].append(dict(source=ASSESSMENTS, **source_digest(levies)))
        report["levyMatch"] = dict(ratePerThousand="2.92250", toleranceCents=1, counts=rate_counts,
                                   source=RATES_2021, schoolTaxSource=SCHOOL_TAX)
    return report


def publish(assessments, parcels, root, year, levies=None):
    atlas = read(root / "atlas/current.json")["version"]
    data = read(root / "atlas" / atlas / "atlas.json")
    report = dict(atlas=atlas, **build(assessments, parcels, data, year, levies))
    release = package(root / "atlas", "assessments", lambda out: write_json(out / "report.json", report))
    pointer(root / "atlas/assessments" / (atlas + ".json"), {"version": release})
    print(release, dict(report["coverage"]), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--assessments", type=Path, default=Path("data/civic/vancouver-property-assessment-2021.csv"))
    parser.add_argument("--parcels", type=Path, default=Path("data/civic/vancouver-property-parcel-points.csv"))
    parser.add_argument("--year", type=int, default=2021)
    parser.add_argument("--levies", type=Path, help="Add strata in other zones by matching a 2021 levy export")
    args = parser.parse_args()
    publish(args.assessments, args.parcels, args.data, args.year, args.levies)
