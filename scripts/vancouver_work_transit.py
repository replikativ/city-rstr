"""Publish scheduled transit for work-linked trips without changing the weekday clock."""
import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
from pathlib import Path
import subprocess
import tempfile

from scripts.vancouver_atlas import write_json
from scripts.vancouver_campus import access_routes
from scripts.vancouver_city_transit import DirectService
from scripts.vancouver_region import package, read
from scripts.vancouver_transit_commutes import BOARDING_MARGIN_SECONDS, pointer
from scripts.vancouver_transit_load import ANNUAL_TABLE, TABLE, BusSpaces, bus_capacity_profile, bus_load_evidence
from scripts.vancouver_transit_transfers import MAX_TRANSFER_METRES, OneTransfer, walk_transfers

DEFAULT_RUNS = ("06c504c638de40f775a7", "c1b31a9daf40041dcb73", "3c70c4228343c1492290")
GTFS_SOURCE = "https://www.translink.ca/about-us/doing-business-with-translink/app-developer-resources/gtfs/gtfs-data"


def resolve_jobs(region, runs, work):
    entries = []
    for run in runs:
        report = read(region / "regional-workplaces" / run / "report.json")
        versions = dict(report["versions"], day=report["day"], transit=report["timetable"])
        atlas = region / "atlas" / versions["atlas"]
        day = region / "cityday" / versions["day"]
        output = work / f"{run}.json"
        subprocess.run(["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.transit-commutes",
                        "fixed-windows", atlas, day, output], check=True)
        inputs = read(output)
        print(run, f"{len(inputs['rows']):,} eligible trips", inputs["excluded"], flush=True)
        entries.append((versions, day, inputs))
    return entries


def priority(row):
    da, person, start, duration, *_ = row
    order = hashlib.blake2b(f"{da}/{person}/{start}".encode(), digest_size=8, person=b"work-transit")
    return start + duration, order.digest(), da, person, start


def window(row):
    _, _, start, duration, a, b, _ = row
    return start, start + duration, a, b


def fits(choice, start):
    return choice is not None and choice[0] >= start


def choose(direct, transfer, start, end, a, b):
    choice = direct(end * 60, a, b)
    if fits(choice, start):
        return choice
    choice = transfer(end * 60, a, b)
    if fits(choice, start):
        return choice


def outing_rides(region, versions, version=None):
    folder = region / "discretionary-outings"
    index = folder / (versions["atlas"] + "_" + versions["day"] + ".json")
    if version is None:
        if not index.is_file():
            return None, []
        version = read(index)["version"]
    directory = folder / version
    report = read(directory / "report.json")
    if any(report["versions"][k] != versions[k] for k in ("atlas", "day", "streets")):
        raise ValueError("Discretionary trips belong to a different weekday")
    if (report.get("transit") or {}).get("release") != versions["transit"]:
        return None, []
    rides = [ride[:4] for row in read(directory / "tours.json") if row[5] == "transit" for ride in row[11]]
    return version, rides


def match_windows(rows, choices, access, service, planner, spaces, places, category=None):
    direct = service.latest_departure(access, BOARDING_MARGIN_SECONDS, spaces.available)
    bounded_transfer = lambda deadline, a, b: planner.latest(deadline, a, b, spaces.available)
    assigned, stats = [], Counter()
    seen = set()
    for row in sorted(rows, key=priority):
        da, person, start, duration, a, b, context = row
        identity = da, person, start
        if identity in seen:
            raise ValueError("Duplicate transit window")
        seen.add(identity)
        if places[a][:2] == places[b][:2]:
            stats["sameCoordinates"] += 1
            continue
        if a not in access or b not in access:
            stats["access"] += 1
            continue
        choice = choices[window(row)]
        if not choice:
            stats["schedule"] += 1
            continue
        _, _, ride = choice
        if not spaces.fits(ride):
            alternative = choose(direct, bounded_transfer, *window(row))
            if not alternative:
                stats["capacity"] += 1
                continue
            _, _, ride = alternative
            stats["rerouted"] += 1
        spaces.reserve(ride)
        assigned.append(([da, person, start, duration, a, b, *ride], context))
        stats["transfer" if len(ride) > 6 else "direct"] += 1
        if category is not None:
            stats[category(context)] += 1
    if len(rows) != len(assigned) + sum(stats[key] for key in ("sameCoordinates", "access", "schedule", "capacity")):
        raise ValueError("Transit assignments and rejection counts do not reconcile")
    return sorted(assigned, key=lambda item: item[0][:3]), dict(stats)


def match_trips(rows, choices, access, service, planner, spaces, places):
    return match_windows(rows, choices, access, service, planner, spaces, places,
                         category=lambda toward: "towardWork" if toward else "fromWork")


def publish_rides(region, day, rows, report, family="work-transit"):
    sample = {(day["das"][d], person) for d, person, *_ in day["sample"]}
    by_da = defaultdict(list)
    for row in sorted(rows, key=lambda item: item[:3]):
        by_da[row[0]].append(row)
    sample_rides = [row for row in rows if tuple(row[:2]) in sample]
    report["coverage"] = {
        "areas": sorted(by_da), "sampleTrips": len(sample_rides), "trips": len(rows),
        "routes": len({row[6] for row in rows} | {row[12][0] for row in rows if len(row) > 12}),
    }

    def stage(out):
        write_json(out / "report.json", report)
        write_json(out / "sample.json", sample_rides)
        for da, group in by_da.items():
            write_json(out / f"{da}.json", group)

    return package(region, family, stage)


def publish_day(region, versions, manifest, profile, assigned, stats, inputs, observed, day, places, outings):
    area_names = day["areas"]
    examples, keys = {}, {}
    for row, work in assigned:
        da, person, start, _, a, b = row[:6]
        area_id = places[b if work else a][2]
        area = area_names[area_id] if area_id >= 0 else None
        for key, include in (("direct", len(row) == 12 and work), ("transfer", len(row) > 12 and work),
                             ("return", not work)):
            score = (area not in {"Burnaby", "New Westminster"}, abs(start - (480 if work else 1020)), da, person)
            if include and (key not in keys or score < keys[key]):
                # Start at the first doorstep so the example includes all itinerary stages.
                keys[key], examples[key] = score, row
    rows = [row for row, _ in assigned]
    outing_version, reserved = outings
    bus = bus_load_evidence(region / "transit" / versions["transit"], manifest, rows, observed,
                            profile["limits"], reserved=reserved)
    if bus["above"]:
        raise ValueError("A published work itinerary exceeds its bus capacity")
    report = dict(versions=versions, serviceDate=manifest["date"], eligible=len(inputs["rows"]),
                  excluded=inputs["excluded"], outcomes=stats, examples=examples,
                  bus=bus, capacitySources=profile["sources"], gtfsSource=GTFS_SOURCE,
                  boardingMargin=BOARDING_MARGIN_SECONDS, transferWalkLimit=MAX_TRANSFER_METRES)
    if outing_version:
        report["sharedOutings"] = {"version": outing_version, "reservedRides": len(reserved)}

    release = publish_rides(region, day, rows, report)
    key = "_".join(versions[k] for k in ("atlas", "day", "streets"))
    pointer(region / "work-transit" / (key + ".json"), {"version": release})
    print("Published", versions["day"], release, report["coverage"]["trips"], report["coverage"]["routes"], stats, flush=True)
    return release


def transfer_inputs(windows, places, service, street_dir, schedule):
    endpoints = {p for _, _, a, b in windows for p in (a, b)}
    access = access_routes(places, endpoints, service.stations, street_dir)
    planner = OneTransfer(service, access, walk_transfers(service, read(schedule / "transfers.json")["pairs"],
                                                          street_dir / "network.json", BOARDING_MARGIN_SECONDS),
                          BOARDING_MARGIN_SECONDS)
    return access, planner


def schedule_choices(windows, access, planner, service):
    direct = lru_cache(maxsize=16384)(service.latest_departure(access, BOARDING_MARGIN_SECONDS))
    windows = sorted((w for w in windows if w[2] in access and w[3] in access), key=lambda w: (w[3], w[1], w[2], w[0]))
    print(f"Checking {len(windows):,} distinct scheduled journeys.", flush=True)
    choices = {}
    for index, w in enumerate(windows, 1):
        choices[w] = choose(direct, planner.latest, *w)
        if index % 5000 == 0:
            print(f"Checked {index:,} scheduled journeys.", flush=True)
    return choices


def prepare_windows(rows, places, service, street_dir, schedule):
    windows = {window(row) for row in rows if places[row[4]][:2] != places[row[5]][:2]}
    access, planner = transfer_inputs(windows, places, service, street_dir, schedule)
    return access, planner, schedule_choices(windows, access, planner, service)


def build(archive, region, runs):
    with tempfile.TemporaryDirectory() as temp:
        entries = resolve_jobs(region, runs, Path(temp))
    catalogues = [read(day / "places.json") for _, day, _ in entries]
    places = max(catalogues, key=len)
    network = {(v["streets"], v["transit"]) for v, _, _ in entries}
    if len(network) != 1 or any(catalogue != places[:len(catalogue)] for catalogue in catalogues):
        raise ValueError("Paired workdays require a common timetable, streets and place catalogue")
    (streets, transit), = network
    street_dir = region / "streets" / streets
    schedule = region / "transit" / transit
    service = DirectService(schedule)
    manifest = service.route_manifest
    observed = archive / "data/raw/probes" / TABLE
    annual = observed.with_name(ANNUAL_TABLE)
    profile = bus_capacity_profile(manifest, observed, annual if annual.is_file() else None)
    access, planner, choices = prepare_windows((row for _, _, inputs in entries for row in inputs["rows"]),
                                              places, service, street_dir, schedule)
    for versions, day, inputs in entries:
        outings = outing_rides(region, versions)
        spaces = BusSpaces(profile["limits"])
        for ride in outings[1]:
            spaces.reserve(ride)
        assigned, stats = match_trips(inputs["rows"], choices, access, service, planner, spaces, places)
        publish_day(region, versions, manifest, profile, assigned, stats, inputs, observed,
                    read(day / "day.json"), places, outings)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--workplace-run", action="append")
    args = parser.parse_args()
    build(args.archive, args.region, args.workplace_run or DEFAULT_RUNS)
