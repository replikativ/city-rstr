"""Fit additional North Shore drives to shops and recreation east of Vancouver."""
import argparse
from collections import Counter
import hashlib
from pathlib import Path
import tempfile

import duckdb
import numpy as np
import pandas as pd

from scripts.vancouver_atlas import write_json
from scripts.vancouver_bridge_traffic import road_profile
from scripts.vancouver_census_geography import area_membership
from scripts.vancouver_cityday import xy
from scripts.vancouver_discretionary_outings import (
    PURPOSES, RECREATION, SHOPPING, accessible_sites, available_windows, donor_tours, place_outing,
    raster_clock, read_opportunities,
)
from scripts.vancouver_eastern_workplaces import DESTINATIONS, EASTERN_FRAME
from scripts.vancouver_flexible_transit import WORKPLACE_RUN
from scripts.vancouver_north_shore_demand import EASTERN_DESTINATION, NORTH_SHORE
from scripts.vancouver_region import package, read, rows
from scripts.vancouver_streets import access_graph
from scripts.vancouver_transit_commutes import pointer
from scripts.vancouver_weekday_attendance import reserve_school

SEED = 20231104
MODE = "car-driver"
RADII = (8000, 13000, 19000)


def inventory(raw, catalogue, areas, offset):
    kinds = {"store": SHOPPING, "outdoors": RECREATION, "sports-venue": RECREATION}
    west, south, east, north = EASTERN_FRAME
    points = pd.DataFrame({"lon": lon, "lat": lat, "purpose": kinds[kind], "name": name}
                          for lon, lat, kind, name, _ in rows(catalogue)
                          if kind in kinds and name and west <= lon <= east and south <= lat <= north)
    membership = area_membership(raw, set(DESTINATIONS))
    members = pd.DataFrame(list(membership.items()), columns=["da", "csd"])
    with duckdb.connect() as db:
        db.execute("load spatial")
        db.register("points", points)
        db.register("members", members)
        db.execute("""create temp table bounds as select csd,
            st_transform(st_union_agg(st_makevalid(s.geom)),'EPSG:3347','EPSG:4326',always_xy:=true) g
            from st_read(?) s join members m on s.DAUID=m.da group by csd""", [str(raw/"lda_000b21a_e.shp")])
        located = db.execute("""select distinct csd,lon,lat,purpose,name from points
            join bounds on st_covers(g,st_point(lon,lat)) order by csd,lon,lat,purpose,name""").fetchall()
    venues, places, seen = {p: [] for p in PURPOSES}, [], set()
    for csd, lon, lat, purpose, name in located:
        x, y = xy(lon, lat)
        area = areas.index(DESTINATIONS[csd])
        key = x, y, area, purpose
        if key in seen:
            continue
        seen.add(key)
        venues[purpose].append(offset+len(places))
        places.append([x, y, area, name])
    if not all(venues.values()):
        raise ValueError("Missing mapped shopping or recreation sites in the eastern cities")
    return places, venues


def reserve_attendance(root, versions, day, places):
    protected, occupancy, shared = reserve_school(root, versions, day)
    key = "_".join(versions[k] for k in ("atlas", "day", "streets"))
    folder = root/"weekday-attendance"
    release = read(folder/(key+".json"))["version"]
    folder = folder/release
    report = read(folder/"report.json")
    if report["shared"] != shared or any(report["versions"][k] != v for k, v in versions.items() if k != "transit"):
        raise ValueError("On-site work uses different weekday layers")
    eastern = 0
    for da in report["areas"]:
        for d, i, _, place, _, start, _, _, end, _, _, _, caregiver, *_ in read(folder/(da+".json")):
            if day["das"][d] != da:
                raise ValueError("On-site work uses a different roster")
            protected[da, i].append((start, end))
            if caregiver is not None:
                protected[da, caregiver].append((start, end))
            eastern += day["areas"][places[place][2]] in DESTINATIONS.values()
    occupancy += np.asarray(report["occupancyDelta"])
    return protected, occupancy, dict(shared, attendance=release), eastern


def survey_limits(evidence, existing_metrics, attendance):
    model, survey = evidence["model"][NORTH_SHORE], evidence["observations"][NORTH_SHORE]
    reference = survey["outbound"][EASTERN_DESTINATION]
    assigned = model["outbound"][EASTERN_DESTINATION][0]
    ceiling = round(reference*model["residents"]/survey["residents"])
    comparison = dict(assigned=assigned, attendance=attendance, scaledCeiling=ceiling, survey=reference,
                      residents=model["residents"], surveyResidents=survey["residents"],
                      check2025=evidence["heldOut2025"]["observations"][NORTH_SHORE]["outbound"][EASTERN_DESTINATION])
    caps = {(area, purpose): max(0, target-baseline-added) for area, purpose, mode, baseline, target, added in existing_metrics
            if mode == MODE}
    return comparison, caps


def eligible_residents(opportunities, das, reserved, minimum):
    for d, i, home, template, municipality, can_drive in opportunities["residents"]:
        if not can_drive or home < 0:
            continue
        free = list(available_windows(opportunities["windows"][template], sorted(reserved.get((das[d], i), ()))))
        if any(min(b, 1260)-max(a, 420) >= minimum for a, b in free):
            yield d, i, home, municipality, free


def assign(candidates, routes, donors, caps, ceiling):
    rng = np.random.default_rng(SEED)
    counts, tours = Counter(), []
    for j in rng.permutation(len(candidates)):
        if len(tours) >= ceiling:
            break
        d, i, home, municipality, free = candidates[j]
        offers = [p for p in PURPOSES if counts[municipality, p] < caps[municipality, p]]
        offers.sort(key=lambda p: counts[municipality, p]/caps[municipality, p])
        for purpose in offers:
            match = place_outing(free, routes.get((home, purpose)), donors[purpose], purpose, rng, match_times=True)
            if match:
                site, start, there, dwell, back, donor = match
                tours.append([d, i, home, site, purpose, MODE, start, there, dwell, back, donor])
                counts[municipality, purpose] += 1
                break
    return sorted(tours), counts


def publish(root, archive, catalogue, workplace_run, backend):
    workplace = read(root/"regional-workplaces"/workplace_run/"report.json")
    versions = {**workplace["versions"], "day": workplace["day"]}
    atlas = root/"atlas"/versions["atlas"]
    day_dir = root/"cityday"/versions["day"]
    day, places = read(day_dir/"day.json"), read(day_dir/"places.json")
    evidence_root = root/"north-shore-demand"
    demand = read(evidence_root/(versions["atlas"]+"_"+versions["day"]+".json"))["version"]
    evidence = read(evidence_root/demand/"report.json")
    if (evidence["atlas"], evidence["day"]) != (versions["atlas"], versions["day"]):
        raise ValueError("Destination trip evidence uses a different weekday")
    protected, occupancy, shared, commuting = reserve_attendance(root, versions, day, places)
    metrics = read(root/"discretionary-outings"/shared["outings"]/"report.json")["metrics"]
    constraint, caps = survey_limits(evidence, metrics, commuting)
    max_tours = max(0, constraint["scaledCeiling"]-constraint["assigned"]-commuting)
    offset = len(places)
    extras, venues = inventory(archive/"data/raw/statcan", catalogue, day["areas"], offset)
    places.extend(extras)
    donor_pool = donor_tours(read(atlas/"atlas.json"), day)
    donors = {p: [r for r in donor_pool[p, MODE] if min(r[2],r[4]) >= 10] for p in PURPOSES}
    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        opportunities = read_opportunities(atlas, day_dir, scratch)
        minimum = min(there+dwell+back for rows in donors.values() for _, _, there, dwell, back in rows)
        candidates = list(eligible_residents(opportunities, day["das"], protected, minimum))
        homes = sorted({row[2] for row in candidates})
        print(f"{len(candidates):,} residents, {len(homes):,} home addresses and {len(extras):,} candidate venues", flush=True)
        network = read(root/"streets"/versions["streets"]/"network.json")
        profile, roads = road_profile(root, versions["streets"], "time")
        graph, snap = access_graph(network, 2, 4, speeds=profile["kmh"])
        pace = profile["connectorKmh"]*1000/60

        def attach(places, **opts):
            nodes, metres = snap(places, **opts)
            return nodes, metres/pace

        routes = accessible_sites(homes, venues, [p[:2] for p in places], graph, attach, 60,
                                  profile["connectorMetres"]/pace, 1, radii=RADII)
        tours, counts = assign(candidates, routes, donors, caps, max_tours)
        print(len(tours), "eastern outings", flush=True)
        if not tours:
            raise ValueError("No paired eastern outing fits the available road and diary time")
        clock = raster_clock(tours, places, occupancy, day["areas"], scratch, backend)
    cities = Counter(day["areas"][places[site][2]] for _, _, _, site, *_ in tours)
    used = sorted({site for _, _, _, site, *_ in tours})
    lookup = {site: offset+i for i, site in enumerate(used)}
    for row in tours:
        row[3] = lookup[row[3]]
    report = dict(schema=1, versions=versions, workplaceRun=workplace_run, shared=shared, demand=demand,
                  source=evidence["source"], sourceDigest=evidence["sourceDigest"], constraint=constraint,
                  roadProfile=roads, catalogueDigest=hashlib.sha256(catalogue.read_bytes()).hexdigest(),
                  cities=dict(cities), support={p: len(r) for p, r in donors.items()}, seed=SEED,
                  metrics=[[area, purpose, cap, counts[area, purpose]] for (area,purpose),cap in caps.items()],
                  attendance=len(tours), basePlaces=offset, sites=[places[site] for site in used], **clock)

    def build(out):
        write_json(out/"report.json", report)
        write_json(out/"tours.json", tours)

    family = "eastern-outings"
    release = package(root, family, build)
    key = "_".join(versions[k] for k in ("atlas", "day", "streets"))
    pointer(root/family/(key+".json"), {"version": release})
    print(release, cities, constraint, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--archive", type=Path, default=Path("../Simulations/city"))
    parser.add_argument("--catalogue", type=Path, default=Path("data/region/work/places.jsonl"))
    parser.add_argument("--workplace-run", default=WORKPLACE_RUN)
    parser.add_argument("--backend", default="jvm")
    args = parser.parse_args()
    publish(args.region, args.archive, args.catalogue, args.workplace_run, args.backend)
