"""Fit incoming work trips to the regional weekday's shared timetable."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from contextlib import nullcontext
import hashlib
import json
from multiprocessing import get_context
from pathlib import Path
import tempfile

from scripts.artifacts import package, pointer, read, write_json
from scripts.vancouver_city_transit import DirectService
from scripts.vancouver_commuter_coverage import carry_bookings, full_timetable, passenger_walks, publish_walks
from scripts.vancouver_downtown import station_counts
from scripts.vancouver_flexible_transit import WORKPLACE_RUN
from scripts.vancouver_personal_transit import reservation_inputs
from scripts.vancouver_regional_inbound import commute_legs
from scripts.vancouver_transit_commutes import BOARDING_MARGIN_SECONDS
from scripts.vancouver_transit_load import ANNUAL_TABLE, TABLE, BusSpaces, bus_capacity_profile, bus_load_evidence, ride_legs
from scripts.vancouver_transit_transfers import MAX_TRANSFER_METRES, TwoTransfers
from scripts.vancouver_work_transit import match_windows, prepare_windows, priority, transfer_inputs, window


def incoming_windows(region, geography, worker_release, places):
    base = read(region / "cityday" / geography["day"] / "places.json")
    if base != places[:len(base)]:
        raise ValueError("Incoming workers and resident weekdays have different workplace coordinates")
    prefix, legs, groups, _ = commute_legs(region, geography, worker_release, "Public transit")
    local, additional = len(base), len(places) - len(base)
    homes = prefix[local:]
    rows = []
    for _, a, b, start, duration, group, person in legs.tolist():
        if (a < local) == (b < local):
            raise ValueError("Incoming trip must connect one external home and one mapped job")
        workward = b < local
        rows.append((groups[group], person, start, duration, a + additional if workward else a,
                     b if workward else b + additional, workward))
    return rows, [*places, *homes], homes


def init_transfer_search(search):
    global process_search
    process_search = search


def search_window(search, row):
    start, end, origin, destination = row
    return search.journey(start * 60, end * 60, origin, destination)


def process_window(row):
    return search_window(process_search, row)


def search_key(windows, sources):
    return hashlib.sha256(json.dumps([1, sources, windows]).encode()).hexdigest()


def checked_choices(checkpoint, key, count):
    saved = read(checkpoint)
    if saved["key"] != key or len(saved["choices"]) > count:
        raise ValueError("The transfer checkpoint belongs to a different commute search")
    return saved["choices"]


def connection_options(search, windows, workers, checkpoint, sources, *, reuse=None):
    """Checkpoint independent schedule results before applying shared seat reservations."""
    key = search_key(windows, sources)
    choices = []
    if checkpoint and checkpoint.is_file():
        choices = checked_choices(checkpoint, key, len(windows))
        print(f"Resuming after {len(choices):,} checked windows", flush=True)
    remaining = windows[len(choices):]
    reuse = reuse or {}
    uncached = [w for w in remaining if w not in reuse]
    if reuse:
        print(f"Reusing {len(remaining)-len(uncached):,} identical itinerary searches", flush=True)
    pool = (ProcessPoolExecutor(max_workers=workers, mp_context=get_context("fork"),
                                initializer=init_transfer_search, initargs=(search,))
            if workers > 1 and uncached else nullcontext())
    with pool as executor:
        results = (executor.map(process_window, uncached, chunksize=24) if executor else
                   (search_window(search, row) for row in uncached))
        for w in remaining:
            choice = reuse[w] if w in reuse else next(results)
            choices.append(choice)
            done = len(choices)
            if checkpoint and (done % 128 == 0 or done == len(windows)):
                checkpoint.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(dir=checkpoint.parent) as tmp:
                    staged = Path(tmp) / "checked.json"
                    write_json(staged, {"key": key, "choices": choices})
                    staged.replace(checkpoint)
            if done % 500 == 0 or done == len(windows):
                print(f"Checked {done:,} of {len(windows):,} windows", flush=True)
    return dict(zip(windows, choices, strict=True))


def known_incoming(rows, baseline_dir, prior):
    identities = {tuple(row[:3]): row for row in rows}
    booked = {}
    for group, (_, matched) in prior["groups"].items():
        if matched:
            for row in read(baseline_dir / (group + ".json")):
                key = tuple(row[:3])
                if tuple(row[:6]) != identities[key][:6] or key in booked:
                    raise ValueError("The comparison changed a previously matched commute")
                booked[key] = row
    return identities, booked


def reserve_incoming(rows, spaces, baseline_dir, prior):
    identities, booked = known_incoming(rows, baseline_dir, prior)
    for row in booked.values():
        spaces.reserve(row[6:])
    return identities, booked


def unresolved(identities, booked, places):
    return [row for key, row in identities.items() if key not in booked and places[row[4]][:2] != places[row[5]][:2]]


def accessible_windows(windows, access):
    return sorted((w for w in windows if w[2] in access and w[3] in access), key=lambda w: (w[3], w[1], w[2], w[0]))


def add_second_transfers(rows, places, service, streets, schedule, spaces, baseline_dir, prior, *, workers=1, checkpoint=None,
                         reuse=None):
    identities, booked = reserve_incoming(rows, spaces, baseline_dir, prior)
    assigned = [(row, identities[key][-1]) for key, row in booked.items()]
    remaining = unresolved(identities, booked, places)
    wanted = {window(row) for row in remaining}
    previous = set()
    if reuse:
        old_rows, old_dir, old_report, old_file = reuse
        before, bookings = known_incoming(old_rows, old_dir, old_report)
        previous = {window(row) for row in unresolved(before, bookings, places)}
    access, planner = transfer_inputs(wanted | previous, places, service, streets, schedule)
    search = TwoTransfers(planner)
    windows = accessible_windows(wanted, access)
    cached = None
    if reuse:
        old_windows = accessible_windows(previous, access)
        key = search_key(old_windows, (old_dir.name, schedule.name, streets.name))
        cached = dict(zip(old_windows, checked_choices(old_file, key, len(old_windows))))
    print(f"Checking {len(windows):,} remaining distinct windows with two transfers", flush=True)
    options = connection_options(search, windows, workers, checkpoint, (baseline_dir.name, schedule.name, streets.name), reuse=cached)
    counts = Counter({k: n for k,n in prior["outcomes"].items() if k not in {"schedule", "capacity", "rerouted"}})
    for row in sorted(remaining, key=priority):
        candidate = options.get(window(row))
        if candidate is None:
            continue
        if not spaces.fits(candidate):
            start, end, a, b = window(row)
            candidate = search.journey(start*60, end*60, a, b, spaces.available)
            if candidate is None:
                counts["newCapacityConflicts"] += 1
                continue
        spaces.reserve(candidate)
        assigned.append(([*row[:6], *candidate], row[-1]))
        counts["twoTransfers"] += 1
        counts["towardWork" if row[-1] else "fromWork"] += 1
    counts["scheduleOrCapacity"] = len(rows) - len(assigned) - counts["access"] - counts["sameCoordinates"]
    if counts["scheduleOrCapacity"] < 0 or counts["newCapacityConflicts"] > counts["scheduleOrCapacity"]:
        raise ValueError("Two-transfer outcomes do not reconcile with the earlier commuter coverage")
    return sorted(assigned, key=lambda item: item[0][:3]), dict(counts)


def publish(region, archive, workplace_run, *, expanded=False, inputs=Path("data/region"), two_transfers=False):
    geography = read(region / "current.json")
    workplace = read(region / "regional-workplaces" / workplace_run / "report.json")
    versions = dict(workplace["versions"], day=workplace["day"], transit=workplace["timetable"])
    if any(versions[k] != geography[k] for k in ("atlas", "streets")):
        raise ValueError("The resident run must use the regional incoming workers' atlas and streets")
    key = "_".join(versions[k] for k in ("atlas", "day", "streets"))
    worker_release = read(region / "incoming-workers" / (geography["atlas"] + ".json"))["version"]
    personal_id = read(region / "personal-transit" / (key + ".json"))["version"]
    personal = region / "personal-transit" / personal_id
    personal_report = read(personal / "report.json")
    day = region / "cityday" / versions["day"]
    residents = read(day / "day.json")
    choices, booked, _ = reservation_inputs(region, versions, residents, key)
    if personal_report["versions"] != versions or personal_report["shared"] != choices:
        raise ValueError("The incoming workers must share the published resident transit reservations")
    for da in personal_report["coverage"]["areas"]:
        for row in read(personal / (da + ".json")):
            booked.extend(ride_legs(row[6:]))

    rows, places, homes = incoming_windows(region, geography, worker_release, read(day / "places.json"))
    key_path = region / "incoming-transit" / (key + ".json")
    streets = region / "streets" / versions["streets"]
    schedule = region / "transit" / versions["transit"]
    raw = archive / "data/raw/probes"
    coverage = prior = comparison = None
    original_journeys = set()
    if expanded or two_transfers:
        comparison = read(key_path)["version"]
        prior = read(region / "incoming-transit" / comparison / "report.json")
        if "transferComparison" in prior:
            comparison = prior["transferComparison"]["version"]
            prior = read(region / "incoming-transit" / comparison / "report.json")
        if two_transfers:
            if "expanded" not in prior:
                raise ValueError("Publish the expanded one-transfer comparison first")
            coverage = prior["expanded"].copy()
        elif "expanded" in prior:
            comparison = prior["expanded"]["comparison"]
            prior = read(region / "incoming-transit" / comparison / "report.json")
        if prior["versions"] != versions or prior["workerRelease"] != worker_release or prior["personalTransit"] != personal_id:
            raise ValueError("The coverage comparison requires the same residents, workers and timetable source")
        baseline_dir = region / "incoming-transit" / comparison
        for group, (_, matched) in prior["groups"].items():
            if matched:
                original_journeys.update(tuple(row[:3]) for row in read(baseline_dir / (group + ".json")))
        timetable = coverage["timetable"] if two_transfers else full_timetable(region, raw / "transit_translink_gtfs_static.zip", schedule)
        extended = region / "transit" / timetable
        booked = carry_bookings(schedule, extended, booked)
        schedule = extended
    service = DirectService(schedule)
    if two_transfers:
        streets = region / "commuter-walk" / coverage["walking"]
    elif expanded:
        endpoints = {index for row in rows for index in row[4:6]}
        walking = publish_walks(region, inputs / "vancouver.osm.pbf",
                                [*service.stations, *(places[index][:2] for index in sorted(endpoints))])
        streets = region / "commuter-walk" / walking
        coverage = dict(timetable=timetable, walking=walking, comparison=comparison)
    manifest = service.route_manifest
    observed = raw / TABLE
    annual = observed.with_name(ANNUAL_TABLE)
    capacity = bus_capacity_profile(manifest, observed, annual if annual.is_file() else None)
    spaces = BusSpaces(capacity["limits"])
    for ride in booked:
        spaces.reserve(ride)

    print(f"Fitting {len(rows):,} regional incoming work trips", flush=True)
    if two_transfers:
        assigned, outcomes = add_second_transfers(rows, places, service, streets, schedule, spaces, baseline_dir, prior)
        access_by_end = prior["missingStopAccess"]
    else:
        access, planner, options = prepare_windows(rows, places, service, streets, schedule)
        assigned, outcomes = match_windows(rows, options, access, service, planner, spaces, places,
                                           category=lambda workward: "towardWork" if workward else "fromWork")
        access_by_end = Counter()
        for _, _, _, _, a, b, workward in rows:
            home, job = (a, b) if workward else (b, a)
            missing_home, missing_job = home not in access, job not in access
            if missing_home or missing_job:
                access_by_end["both" if missing_home and missing_job else "home" if missing_home else "work"] += 1
    if sum(access_by_end.values()) != outcomes.get("access", 0):
        raise ValueError("The stop access outcomes do not reconcile with the matched cohort")
    groups = defaultdict(list)
    examples, example_ranks = {}, {}
    downtown = residents["areas"].index("Downtown")
    for row, workward in assigned:
        group, person, start, _, a, b = row[:6]
        groups[group].append(row)
        key_example = "towardWork" if workward else "fromWork"
        rank = (places[b if workward else a][2] != downtown, tuple(row[:3]) in original_journeys, len(row) == 12,
                abs(start - (480 if workward else 1020)), group, person)
        if key_example not in examples or rank < example_ranks[key_example]:
            examples[key_example] = row
            example_ranks[key_example] = rank

    trips = [row for row, _ in assigned]
    bus = bus_load_evidence(schedule, manifest, trips, observed, capacity["limits"], reserved=booked)
    if bus["above"]:
        raise ValueError("Incoming trips exceed the regional weekday's bus capacity")
    rail_table = observed.with_name("transit_translink_tspr2025_skytrainavgalightsbrdgs_yearstationdaytypehourly.csv")
    rail = station_counts(rail_table, schedule, manifest, groups)
    eligible = Counter(row[0] for row in rows)
    report = dict(versions=versions, workplaceRun=workplace_run, workerRelease=worker_release, personalTransit=personal_id,
                  serviceDate=manifest["date"], shared=choices, riderLegsReserved=len(booked), outcomes=outcomes,
                  missingStopAccess=dict(access_by_end),
                  rail=rail, bus=bus, capacitySources=capacity["sources"], boardingMargin=BOARDING_MARGIN_SECONDS,
                  transferWalkLimit=MAX_TRANSFER_METRES, homeIndex=len(places) - len(homes), examples=examples,
                  groups={g: [n, len(groups[g])] for g, n in sorted(eligible.items())})
    walks = {}
    if coverage:
        rides = {tuple(row[:3]) for row in trips}
        if two_transfers:
            if not original_journeys <= rides:
                raise ValueError("The extra transfer displaced a reserved itinerary")
            report["transferComparison"] = dict(version=comparison, retained=len(original_journeys),
                                                added=len(rides-original_journeys), previousRail=prior["rail"]["matched"])
        else:
            coverage.update(retained=len(rides & original_journeys), added=len(rides - original_journeys),
                            lost=len(original_journeys - rides), previousOutcomes=prior["outcomes"], previousRail=prior["rail"]["matched"])
        report["expanded"] = coverage
        walks = passenger_walks(read(streets / "network.json"), service, places, trips)

    def stage(out):
        write_json(out / "report.json", report)
        write_json(out / "homes.json", homes)
        for group, journeys in groups.items():
            if journeys:
                write_json(out / (group + ".json"), journeys)
        for group, paths in walks.items():
            write_json(out / (group + "-walks.json"), paths)

    release = package(region, "incoming-transit", stage)
    pointer(key_path, {"version": release})
    print(release, len(trips), outcomes, flush=True)
    return release


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--workplace-run", default=WORKPLACE_RUN)
    parser.add_argument("--expanded", action="store_true", help="Use the complete dated GTFS feed and extend OSM walking coverage")
    parser.add_argument("--two-transfers", action="store_true", help="Extend the published full-feed run with a second transfer")
    parser.add_argument("--inputs", type=Path, default=Path("data/region"), help="Folder containing vancouver.osm.pbf")
    args = parser.parse_args()
    publish(args.region, args.archive, args.workplace_run, expanded=args.expanded, inputs=args.inputs, two_transfers=args.two_transfers)
