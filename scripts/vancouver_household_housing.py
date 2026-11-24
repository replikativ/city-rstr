"""Add Census-based shelter costs and owner dwelling values to existing synthetic households."""
import argparse
from collections import defaultdict
import csv
import hashlib
from pathlib import Path

import numpy as np

from scripts.vancouver_atlas import donor_person, write_json
from scripts.vancouver_census_geography import CITY, DA, profile_cells
from scripts.vancouver_region import package, read
from scripts.vancouver_transit_commutes import pointer

PUMF = "pumf/data_donnees_2021_hier_v2.csv"
PROFILE = "https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/index.cfm?Lang=E"
MICRODATA = "https://www150.statcan.gc.ca/n1/pub/98m0001x/"
MIN_REFERENCE, MIN_MODEL = 25, 10
SEED = 21489
MASKED_INCOME = (88888888, 99999999)
# Household attribute index, published count, mean control and held-out median.
MARGINS = {
    "ownerShelter": (1, 1482, 1487, 1486),
    "tenantShelter": (1, 1490, 1495, 1494),
    "ownerValue": (3, 1482, 1489, 1488),
}


def signature(tenure, people):
    return tenure, tuple(tuple(member[:7]) for member in people)


def donors(file):
    households = defaultdict(list)
    with file.open() as f:
        for row in csv.DictReader(f):
            if row["CMA"] != "933":
                continue
            households[int(row["HH_ID"])].append((
                int(row["PP_ID"]), donor_person(row),
                *(int(row[k]) for k in ("TENUR", "SHELCO", "TOTINC_AT", "VALUE", "PRESMORTG")), float(row["WEIGHT"])
            ))
    choices = defaultdict(list)
    for members in households.values():
        members.sort()
        _, _, tenure, cost, _, value, mortgage, weight = members[0]
        if any((t, c, v, m) != (tenure, cost, value, mortgage) for _, _, t, c, _, v, m, _ in members):
            raise ValueError("Repeated housing fields disagree within a donor household")
        adult = [r[4] for r in members if r[1][0] not in (1, 2)]
        after_tax = sum(adult) if adult and not any(x in MASKED_INCOME for x in adult) else None
        owner_value = value if tenure == 1 and value not in MASKED_INCOME and value > 0 else None
        choices[signature(tenure, [r[1] for r in members])].append(
            ([tenure, cost if tenure in (1, 2) else None, after_tax, owner_value,
              mortgage if mortgage in (0, 1) else None], weight)
        )
    return choices


def draw(people, tenure, choices, rng):
    options = choices.get(signature(tenure, people))
    if not options:
        return [tenure, None, None, None, None]
    if len(options) == 1:
        return list(options[0][0])
    weights = np.array([weight for _, weight in options])
    return list(options[rng.choice(len(weights), p=weights / weights.sum())][0])


def eligible(key, rows):
    field = MARGINS[key][0]
    tenure = 2 if key == "tenantShelter" else 1
    return [row for row in rows if row[0] == tenure and row[field] is not None]


def reference(cells):
    return {k: dict(n=cells[n], mean=cells[mean], median=cells[median])
            for k, (_, n, mean, median) in MARGINS.items()}


def adjust(rows, local, city_scale):
    support = {}
    for key, (field, *_ids) in MARGINS.items():
        valid = eligible(key, rows)
        raw = sum(row[field] for row in valid)
        info = local[key]
        use_local = (info["n"] or 0) >= MIN_REFERENCE and len(valid) >= MIN_MODEL and bool(info["mean"]) and raw > 0
        scale = info["mean"] * len(valid) / raw if use_local else city_scale[key]
        for row in valid:
            row[field] = round(row[field] * scale)
        support[key] = {"local": use_local, "count": len(valid), "scale": round(scale, 6)}
    return support


def summary(rows):
    data = {}
    for key, (field, *_ids) in MARGINS.items():
        values = [row[field] for row in eligible(key, rows)]
        if values:
            data[key] = dict(count=len(values), mean=round(float(np.mean(values)), 1),
                             median=round(float(np.median(values)), 1))
    return data


def publish(root, raw, atlas_id):
    atlas_root = root / "atlas"
    atlas_dir = atlas_root / atlas_id
    manifest = read(atlas_dir / "atlas.json")
    src = raw / PUMF
    pool = donors(src)
    data = {}
    for da in sorted(manifest["das"]):
        roster = read(atlas_dir / (da + ".json"))
        rng = np.random.default_rng([SEED, int(da)])
        data[da] = [draw(roster["people"][start:start+size], tenure, pool, rng)
                    for start, size, tenure in roster["homes"]]
    rows = [row for households in data.values() for row in households]
    if len(rows) != manifest["city"]["homes"]:
        raise ValueError("Housing rows do not match the private-household roster")
    profiles = profile_cells(raw, {CITY, *(DA + da for da in data)},
                             {i for _, *ids in MARGINS.values() for i in ids})
    benchmarks = {geography: reference(cells) for geography, cells in profiles.items()}
    city_before = summary(rows)
    city_scale = {key: benchmarks[CITY][key]["mean"] / city_before[key]["mean"] for key in MARGINS}
    support = {da: adjust(households, benchmarks[DA + da], city_scale) for da, households in data.items()}
    model_by_area = {name: summary([row for da in group["das"] for row in data[da]])
                     for name, group in manifest["areas"].items()}
    local_coverage = {key: sum(entry[key]["count"] for entry in support.values() if entry[key]["local"])
                      for key in MARGINS}
    after = summary(rows)
    for da, households in data.items():
        for k, (field, *_ids) in MARGINS.items():
            if support[da][k]["local"]:
                values = eligible(k, households)
                if abs(sum(r[field] for r in values)/len(values) - benchmarks[DA + da][k]["mean"]) > .51:
                    raise ValueError(f"Local housing calibration failed for {da} {k}")
    with src.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    report = dict(atlas=atlas_id, year=2021, households=len(rows), linked=sum(row[1] is not None for row in rows),
                  afterTaxKnown=sum(row[2] is not None for row in rows), localCoverage=local_coverage,
                  before=city_before, all=after, census=benchmarks[CITY], areas=model_by_area,
                  das={da: summary(households) for da, households in data.items()}, support=support,
                  fields=["tenure", "shelter", "afterTax", "dwellingValue", "mortgage"],
                  censusSource=PROFILE, donorSource=MICRODATA, donorDigest=digest,
                  minReference=MIN_REFERENCE, minModel=MIN_MODEL, seed=SEED)

    def stage(folder):
        write_json(folder / "report.json", report)
        for da, households in data.items():
            write_json(folder / (da + ".json"), households)
    release = package(atlas_root, "housing", stage)
    pointer(atlas_root / "housing" / (atlas_id + ".json"), {"version": release})
    print("Household housing", release, report["linked"], report["afterTaxKnown"], local_coverage, after, flush=True)
    return release


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--atlas")
    args = parser.parse_args()
    publish(args.data, args.archive / "data/raw/statcan",
            args.atlas or read(args.data / "atlas/current.json")["version"])
