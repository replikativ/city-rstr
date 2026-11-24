"""Run the part of Metro Vancouver's workplace census that lives outside the regional roster."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import duckdb
import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_bridge_traffic import IRONWORKERS, REGIONAL_BRIDGES, road_profile, score
from scripts.vancouver_cityday import ORIGIN, SCALE, SPEED, xy
from scripts.vancouver_commuter_presence import publish_presence
from scripts.vancouver_inbound import (
    MODES, NAMES, WEEKDAY_ATTENDANCE, commute_donors, home_anchors, shifts, simulate, workplaces,
)
from scripts.vancouver_region import package, read, rows
from scripts.vancouver_regional_workplaces import CENSUS, SOURCE
from scripts.vancouver_workplace_tracts import census_counts

FILE = "regional-incoming-workplaces-2021.csv"
DESTINATIONS = {
    "5915022": "Vancouver", "5915051": "City of North Vancouver",
    "5915046": "District of North Vancouver", "5915055": "West Vancouver",
}


def census_flows(table):
    destinations = {name: csd for csd, name in CENSUS}
    flows, beyond = {}, Counter()
    with table.open(encoding="utf-8-sig", newline="") as stream:
        source = csv.reader(stream)
        header = next(source)
        home, name, job, year = map(header.index, ["DGUID", "GEO", "Place of work", "REF_DATE"])
        total, men, women = map(header.index, ["Gender (3):Total - Gender[1]", "Gender (3):Men+[2]", "Gender (3):Women+[3]"])
        for row in source:
            work = destinations.get(row[job])
            if work is None or not row[home].startswith("2021A0005"):
                continue
            residence = row[home][9:]
            if residence == work:
                continue
            if row[year] != "2021" or row[total+1]:
                raise ValueError("Unexpected year or suppressed commuter count")
            stock = int(row[total])
            if not stock:
                continue
            if not residence.startswith("5915"):
                beyond[work] += stock
            else:
                if (residence, work) in flows:
                    raise ValueError("Repeated census workplace flow")
                flows[residence, work] = dict(name=NAMES.get(residence, row[name]), stock=stock,
                                              men=int(row[men]), women=int(row[women]))
    return flows, dict(beyond)


def split_stock(control, anchors, covered):
    """Use observed cross-CSD commuters to apportion origins cut by the roster boundary."""
    outside = [h for h in anchors if h[0] not in covered]
    if len(anchors) == len(outside):
        return control["stock"], outside, None
    if not outside:
        return 0, outside, "all census areas in the resident roster"
    field = 4 if sum(h[4] for h in anchors) else 3
    total = sum(h[field] for h in anchors)
    if not total:
        return None, outside, "unresolved home geography"
    fraction = sum(h[field] for h in outside) / total
    return round(control["stock"] * fraction), outside, "out-of-municipality workers" if field == 4 else "population"


def regional_worksites(raw, data, inputs, places, areas):
    city, weights = workplaces(raw, places)
    priors = defaultdict(float, zip(city.tolist(), weights.tolist(), strict=True))
    north = set(DESTINATIONS.values()) - {"Vancouver"}
    published = {(p[0], p[1], p[3]): i for i, p in enumerate(places) if p[2] >= 0 and areas[p[2]] in north}
    for lon, lat, kind, label, weight in rows(inputs/"work/places.jsonl"):
        if kind == "job":
            site = published.get((*xy(lon, lat), label))
            if site is not None:
                priors[site] = max(priors[site], weight)
    jobs = np.array(sorted(priors))
    coords = np.array([places[i][:2] for i in jobs]) / SCALE + ORIGIN
    with duckdb.connect() as db:
        db.execute("load spatial")
        db.execute("create table jobs (i integer, lon double, lat double)")
        db.executemany("insert into jobs values (?,?,?)",
                       [(site, float(lon), float(lat)) for site, (lon, lat) in zip(jobs.tolist(), coords, strict=True)])
        tract = dict(db.execute("""select i,min(DGUID) from jobs p
            join st_read(?) t on st_covers(st_makevalid(t.geom), st_point(p.lon,p.lat)) group by i""",
            [str(data/"vancouver-tracts-2021.geojson")]).fetchall())
    totals = census_counts(data/"98100498-eng.zip")
    sums = Counter()
    for i, weight in priors.items():
        sums[tract.get(i)] += weight
    by_city = defaultdict(list)
    for i in jobs.tolist():
        zone = areas[places[i][2]]
        destination = next((csd for csd, name in DESTINATIONS.items() if zone == name), "5915022")
        code = tract.get(i)
        observed = totals.get(code)
        by_city[destination].append((i, code, observed, priors[i]))
    calibrated, diagnostics = {}, {}
    for destination, work in by_city.items():
        known = {code for _, code, n, _ in work if n is not None and n > 0}
        numerator = sum(totals[code] for code in known)
        denominator = sum(sums[code] for code in known)
        if not denominator:
            raise ValueError(f"No census workplace supports for {destination}")
        fallback = numerator / denominator
        mass = np.array([weight * (n / sums[code] if n is not None else fallback) for _, code, n, weight in work])
        sites = np.array([i for i, _, _, _ in work])
        calibrated[destination] = sites, mass
        diagnostics[destination] = dict(sites=len(sites), unobservedTractSites=sum(n is None for _, _, n, _ in work))
    if set(calibrated) != set(DESTINATIONS):
        raise ValueError("Workplace anchors missing for a study municipality")
    return calibrated, diagnostics


def build(archive, region, geography, table, data, inputs, out, backend, verify):
    raw = archive/"data/raw"
    atlas = read(region/"atlas"/geography["atlas"]/"atlas.json")
    day = region/"cityday"/geography["day"]
    places = read(day/"places.json")
    areas = read(day/"day.json")["areas"]
    flows, beyond = census_flows(table)
    homes = home_anchors(raw/"statcan", {csd for csd, _ in flows})
    jobs, diagnostics = regional_worksites(raw, data, inputs, places, areas)
    donors = commute_donors(raw/"statcan/pumf/data_donnees_2021_hier_v2.csv")
    diaries = json.loads(subprocess.check_output(["clojure", "-M", "-m", "city.vancouver.atlas-diaries", archive,
                                                 "--attendance"]))
    library, spans = shifts(diaries)
    coords, zones = np.asarray([p[:2] for p in places]), np.asarray([p[2] for p in places])
    core = areas.index("Downtown")
    covered = set(atlas["das"])
    groups, unresolved, split = {}, {}, {}
    overlap = Counter()
    for (origin, destination), observed in sorted(flows.items()):
        key = origin + "-" + destination
        stock, outside, basis = split_stock(observed, homes[origin], covered)
        if stock is None:
            unresolved[key] = observed
            continue
        overlap[destination] += observed["stock"] - stock
        if basis and outside:
            split[key] = dict(census=observed["stock"], outside=stock, basis=basis)
        if stock == 0:
            continue
        if any(h[0] in covered for h in outside):
            raise ValueError("Incoming commuter and resident census areas overlap")
        sites, weights = jobs[destination]
        control = {**observed, "stock": stock, "origin": origin, "destination": DESTINATIONS[destination],
                   "destinationCsd": destination}
        result = simulate(origin, control, outside, sites, weights, zones, coords, donors, library, WEEKDAY_ATTENDANCE,
                          core, destination=destination)
        if result is None:
            unresolved[key] = control
        else:
            groups[key], roster = result
            roster["homePoints"] = [h[1:3] for h in outside]
            write_json(out/(key+".json"), roster)
    report = dict(atlas=geography["atlas"], places=hashlib.sha256((day/"places.json").read_bytes()).hexdigest(),
                  groups=groups, modes=MODES, unresolved=unresolved, beyondMetro=beyond,
                  excludedResidentStock=dict(overlap), boundarySplits=split, source=SOURCE, workplaceTracts=diagnostics,
                  sourceDigest=hashlib.sha256(table.read_bytes()).hexdigest(),
                  attendance=WEEKDAY_ATTENDANCE, workSpans=spans)
    original = sum(f["stock"] for f in flows.values())
    stock = sum(g["stock"] for g in groups.values())
    if original != stock + sum(overlap.values()) + sum(g["stock"] for g in unresolved.values()):
        raise ValueError("Regional workplace stock does not reconcile to the census")
    print(f"Published schedules for {stock:,} external usual workers in {len(groups)} flows.", flush=True)
    report["execution"] = publish_presence(out, groups, spans, zones, core, backend, verify)
    write_json(out/"commuters.json", report)
    return report


def publish(archive, region, table, data, inputs, backend="jvm", verify=False):
    geography = read(region/"current.json")
    family = "incoming-workers"
    release = package(region, family, lambda out: build(archive, region, geography, table, data, inputs, out,
                                                       backend, verify))
    directory = region/family
    with tempfile.TemporaryDirectory(dir=directory) as tmp:
        pointer = Path(tmp)/"incoming.json"
        write_json(pointer, {"version": release})
        pointer.replace(directory/(geography["atlas"] + ".json"))
    print("Regional incoming workers", release, flush=True)
    return release


def commute_legs(region, geography, release, mode_name):
    folder = region/"incoming-workers"/release
    workers = read(folder/"commuters.json")
    catalog = region/"cityday"/geography["day"]/"places.json"
    if workers["atlas"] != geography["atlas"] or workers["places"] != hashlib.sha256(catalog.read_bytes()).hexdigest():
        raise ValueError("Worker assignments and commute benchmark use different geography")
    places = [p[:2] for p in read(catalog)]
    origin_ids = {}
    legs = []
    groups = sorted(workers["groups"])
    mode_id = workers["modes"].index(mode_name)
    for group_index, group in enumerate(groups):
        cohort = read(folder/(group + ".json"))
        home_ids = []
        for da, point in zip(cohort["homes"], cohort["homePoints"], strict=True):
            if da not in origin_ids:
                origin_ids[da] = len(places)
                places.append(point)
            home_ids.append(origin_ids[da])
        for i, (a, b, _, _, mode, start, duration, span, attend, _) in enumerate(cohort["people"]):
            if attend and mode == mode_id:
                legs.append((1, home_ids[a], b, start, duration, group_index, i))
                legs.append((1, b, home_ids[a], start + duration + span, duration, group_index, i))
    return places, np.array(legs, dtype=np.int32).reshape(-1, 7), groups, workers


def driver_legs(region, geography, release):
    return commute_legs(region, geography, release, "Car driver")


def publish_bridges(region, geography, release, *, road_speeds=False, observed_highway1=False):
    places, legs, groups, workers = driver_legs(region, geography, release)
    folder = region/"incoming-workers"/release
    bridges = [*REGIONAL_BRIDGES, IRONWORKERS]
    sites = [dict(key=key, name=name) for key, name, *_ in bridges]
    network = read(region/"streets"/geography["streets"]/"network.json")
    metric = "highway1" if observed_highway1 else "time" if road_speeds else None
    profile, routing = road_profile(region, geography["streets"], metric) if metric else (None, None)
    required = {}
    coverage, searches = score(legs, places, network, sites, groups,
                              bridges=bridges, scenarios=1, required_crossing=required, profile=profile)
    presence = np.asarray(read(folder/"presence.json")["counts"]).sum(axis=(1, 2))
    report = dict(versions={k: geography[k] for k in ("atlas", "day", "streets")}, workerRelease=release,
                  sites={site["key"]: site["scenarios"][0] for site in sites}, coverage=coverage[0],
                  searches=searches, speed=SPEED["car-driver"], requiredCrossing=required, presence=presence.tolist(),
                  stock=sum(g["stock"] for g in workers["groups"].values()),
                  attending=sum(g["attending"] for g in workers["groups"].values()), source=workers["source"])
    key = "_".join(report["versions"][k] for k in ("atlas", "day", "streets"))
    if routing:
        report["routing"] = routing
        key += "_" + routing["metric"]
    version = package(region, "incoming-bridges", lambda out: write_json(out/"counts.json", report))
    directory = region/"incoming-bridges"
    with tempfile.TemporaryDirectory(dir=directory) as tmp:
        pointer = Path(tmp)/"pointer.json"
        write_json(pointer, {"version": version})
        pointer.replace(directory/(key + ".json"))
    print("Regional incoming bridge counts", version, coverage, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--data", type=Path, default=Path("data/mobility"))
    parser.add_argument("--inputs", type=Path, default=Path("data/region"))
    parser.add_argument("--backend", default="jvm")
    parser.add_argument("--verify-workers", action="store_true")
    routing = parser.add_mutually_exclusive_group()
    routing.add_argument("--road-speeds", action="store_true", help="also score with the published directed road speeds")
    routing.add_argument("--observed-highway1", action="store_true",
                         help="rescore the paired free-flow report's existing workers with the Highway 1 observations")
    parser.add_argument("--day", help="select a published weekday for --observed-highway1")
    args = parser.parse_args()
    geography = read(args.region/"current.json")
    if args.observed_highway1:
        if args.day:
            geography["day"] = args.day
        directory = args.region/"incoming-bridges"
        identity = {k: geography[k] for k in ("atlas", "day", "streets")}
        pointer = read(directory/("_".join(identity.values())+"_time.json"))
        reference = read(directory/pointer["version"]/"counts.json")
        if reference["versions"] != identity or reference["routing"]["metric"] != "time":
            raise ValueError("Incoming workers use a different weekday or routing profile")
        publish_bridges(args.region, geography, reference["workerRelease"], observed_highway1=True)
    else:
        if args.day:
            parser.error("--day selects the parent of an --observed-highway1 report")
        release = publish(args.archive, args.region, args.data/FILE, args.data, args.inputs, args.backend, args.verify_workers)
        publish_bridges(args.region, geography, release)
        if args.road_speeds:
            publish_bridges(args.region, geography, release, road_speeds=True)
