"""Route non-work diary trips on the weekday timetable within shared bus limits."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import subprocess
import tempfile

from scripts.artifacts import pointer, read
from scripts.vancouver_city_transit import DirectService
from scripts.vancouver_flexible_transit import WORKPLACE_RUN
from scripts.vancouver_transit_load import ANNUAL_TABLE, TABLE, BusSpaces, bus_capacity_profile, bus_load_evidence, ride_legs
from scripts.vancouver_work_transit import GTFS_SOURCE, match_windows, outing_rides, prepare_windows, publish_rides


def reservation_inputs(region, versions, day, key):
    flex = read(region / "work-transit-flex" / (key + ".json"))["version"]
    clock = read(region / "household-clock" / flex / "report.json")
    work_id = clock["workTransitRelease"]
    work = region / "work-transit" / work_id
    work_report = read(work / "report.json")
    fixed_id = work_report["flex"]["baselineRelease"]
    attendance_id = read(region / "weekday-attendance" / (key + ".json"))["version"]
    attendance = region / "weekday-attendance" / attendance_id
    report = read(attendance / "report.json")
    outing_id = work_report["sharedOutings"]["version"]
    if any(parent["versions"] != versions for parent in (report, work_report)) or (
        report["shared"]["flexibleTransit"], report["shared"]["outings"]
    ) != (flex, outing_id):
        raise ValueError("Shared bus assignments use different weekday inputs")

    _, outings = outing_rides(region, versions, outing_id)
    prior = [tuple(leg) for ride in outings for leg in ride_legs(ride)]
    occupied = defaultdict(list)
    work_count = 0
    for da in work_report["coverage"]["areas"]:
        for row in read(work / (da + ".json")):
            start, duration = row[2:4]
            occupied[da, row[1]].append((start, start + duration))
            prior.extend(tuple(leg) for leg in ride_legs(row[6:]))
            work_count += 1
    attendance_trips = 0
    for da in report["areas"]:
        for row in read(attendance / (da + ".json")):
            d, person, _, _, mode, start, _, _, end, outward, back, *_ = row
            if da != day["das"][d]:
                raise ValueError("On-site work uses a different resident roster")
            occupied[da, person].append((start, end))
            if mode == "transit":
                prior.extend(tuple(leg) for ride in (outward, back[1]) for leg in ride_legs(ride))
                attendance_trips += 2

    reserved = dict(work=work_id, recordedWork=fixed_id, outings=outing_id, attendance=attendance_id,
                    workTrips=work_count, outingBoardings=len(outings), attendanceTrips=attendance_trips)
    return reserved, prior, occupied


def check_windows(rows, occupied):
    for da, person, start, duration, *_ in rows:
        if any(a < start + duration and start < b for a, b in occupied.get((da, person), ())):
            raise ValueError(f"Personal transit overlaps a reserved work trip for {da}/{person}")


def purpose_examples(assigned):
    examples, ranks = {}, {}
    for row, purpose in assigned:
        if purpose == "home":
            continue
        da, person, start, *_ = row
        rank = (len(row) == 12, abs(start - 720), da, person)
        if purpose not in ranks or rank < ranks[purpose]:
            ranks[purpose] = rank
            examples[purpose] = row
    return examples


def publish(region, archive, run):
    report = read(region / "regional-workplaces" / run / "report.json")
    versions = {**report["versions"], "day": report["day"], "transit": report["timetable"]}
    key = "_".join(versions[k] for k in ("atlas", "day", "streets"))
    atlas = region / "atlas" / versions["atlas"]
    source = region / "cityday" / versions["day"]
    day, places = read(source / "day.json"), read(source / "places.json")
    reserved, prior, occupied = reservation_inputs(region, versions, day, key)

    with tempfile.TemporaryDirectory() as tmp:
        windows = Path(tmp) / "windows.json"
        subprocess.run(["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.transit-commutes",
                        "personal-windows", atlas, source, windows], check=True)
        inputs = read(windows)

    rows = inputs["rows"]
    check_windows(rows, occupied)
    print(f"{len(rows):,} personal travel windows", inputs["excluded"], flush=True)
    schedule = region / "transit" / versions["transit"]
    streets = region / "streets" / versions["streets"]
    service = DirectService(schedule)
    manifest = service.route_manifest
    observed = archive / "data/raw/probes" / TABLE
    annual = observed.with_name(ANNUAL_TABLE)
    capacity = bus_capacity_profile(manifest, observed, annual if annual.is_file() else None)
    spaces = BusSpaces(capacity["limits"])
    for boarding in prior:
        spaces.reserve(boarding)

    access, planner, options = prepare_windows(rows, places, service, streets, schedule)
    assigned, outcomes = match_windows(rows, options, access, service, planner, spaces, places)
    matched = [row for row, _ in assigned]
    windows = {tuple(row[:6]) for row in rows}
    if any(tuple(row[:6]) not in windows for row in matched):
        raise ValueError("Matched trips changed a weekday stop or travel window")
    bus = bus_load_evidence(schedule, manifest, matched, observed, capacity["limits"], reserved=prior)
    if bus["above"]:
        raise ValueError("Scheduled trips exceed the shared bus limits")

    eligible = Counter(row[-1] for row in rows)
    completed = Counter(purpose for _, purpose in assigned)
    purposes = {k: [n, completed[k]] for k, n in sorted(eligible.items())}
    info = dict(versions=versions, workplaceRun=run, serviceDate=manifest["date"], gtfsSource=GTFS_SOURCE,
                eligible=len(rows), excluded=inputs["excluded"], outcomes=outcomes, purposes=purposes,
                examples=purpose_examples(assigned), bus=bus, shared=reserved)
    release = publish_rides(region, day, matched, info, family="personal-transit")
    pointer(region / "personal-transit" / (key + ".json"), {"version": release})
    print(release, "matched", len(matched), "across", len(info["coverage"]["areas"]), "areas", outcomes, purposes, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--workplace-run", default=WORKPLACE_RUN)
    args = parser.parse_args()
    publish(args.region, args.archive, args.workplace_run)
