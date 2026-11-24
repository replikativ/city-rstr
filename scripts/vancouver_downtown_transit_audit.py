"""Trace Downtown transit demand through the published municipal weekday's bookings."""
import argparse
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
import re
import subprocess
import tempfile

from scripts.vancouver_atlas import write_json
from scripts.vancouver_campus import access_routes
from scripts.vancouver_city_transit import DirectService
from scripts.vancouver_incoming_commutes import OneTransferSearch, commute_windows
from scripts.vancouver_incoming_timing import flex_window
from scripts.vancouver_mobility import PRIORITY, REPORT
from scripts.vancouver_region import read
from scripts.vancouver_regional_inbound_transit import accessible_windows, connection_options, known_incoming, unresolved
from scripts.vancouver_transit_load import ride_legs
from scripts.vancouver_transit_reach import Reach
from scripts.vancouver_transit_transfers import TwoTransfers
from scripts.vancouver_work_transit import transfer_inputs, window


def downtown_window(row, places, downtown):
    _, _, start, duration, origin, destination = row[:6]
    a, b = places[origin][2], places[destination][2]
    if (a == downtown) == (b == downtown):
        return None
    # Compare the same activity endpoint clock as the Downtown mode table.
    return ((start + duration) // 60 % 24, "arriving") if b == downtown else (start // 60 % 24, "leaving")


class Counts:
    def __init__(self):
        self.hourly = defaultdict(Counter)
        self.origins = defaultdict(Counter)

    def add(self, hour, direction, origin, outcome, rail, flexible=()):
        fields = ("demand", outcome, *flexible, *(("withSkyTrain",) if rail else ()))
        for field in fields:
            self.hourly[hour, direction][field] += 1
            self.origins[origin, hour, direction][field] += 1

    def report(self):
        def totals(table, prefix):
            return dict(arriving=[dict(table.get((*prefix, h, "arriving"), {})) for h in range(24)],
                        leaving=[dict(table.get((*prefix, h, "leaving"), {})) for h in range(24)])
        return dict(hourly=totals(self.hourly, ()),
                    byHome={name: totals(self.origins, (name,)) for name in sorted({k[0] for k in self.origins})})


def has_rail(ride, rail):
    return bool(ride and any(leg[0] in rail for leg in ride_legs(ride[6:])))


def rail_routes(service):
    return {r["id"] for r in service.route_manifest["routes"] if r["type"] == 1}


def resident_audit(root, joint, day, places, core):
    versions = joint["versions"]
    rider_dir = root / "transit-riders" / joint["riders"]
    published = read(rider_dir / "riders.json")
    if published["versions"] != dict(versions, transit=joint["transit"], workplaces=joint["workplaces"]["tract-workplaces"]):
        raise ValueError("Resident bookings belong to a different weekday")
    inputs = dict(versions, outbound=joint["workplaces"]["outbound"], worksites=joint["workplaces"]["worksites"],
                  tracts=joint["workplaces"]["tract-workplaces"], outings=joint["outings"], priority=PRIORITY, surveyModes=REPORT)
    with tempfile.TemporaryDirectory() as tmp:
        parameters, extracted = (Path(tmp) / name for name in ("input.json", "legs.json"))
        write_json(parameters, inputs)
        subprocess.run(["node", "scripts/vancouver_joint_trips.mjs", root, parameters, extracted], check=True)
        demand = read(extracted)
    rows = {tuple(row[:3]): row for row in demand["transit"]}
    booked = {tuple(row[:3]): row for da in published["das"] for row in read(rider_dir / f"{da}.json")}
    if (len(rows) != len(demand["transit"]) or len(booked) != published["matched"]
            or any(row[:6] != rows.get(key) for key, row in booked.items())
            or len(rows) + sum(demand["excluded"].values()) != published["total"]):
        raise ValueError("Resident demand and published bookings do not reconcile")
    for reason, count in demand["excluded"].items():
        if published["excluded"][reason] != count:
            raise ValueError(f"Resident exclusions changed for {reason}")
    located = {key: row for key, row in rows.items() if downtown_window(row, places, core)}
    service = DirectService(root / "transit" / joint["transit"])
    rail = rail_routes(service)
    access = access_routes(places, {p for row in located.values() for p in row[4:6]},
                           service.stations, root / "streets" / versions["streets"])
    atlas = read(root / "atlas" / versions["atlas"] / "atlas.json")
    homes = {da: area for area, record in atlas["areas"].items() for da in record["das"]}
    counts = Counts()
    for key, row in located.items():
        ride = booked.get(key)
        if ride and any(p not in access for p in row[4:6]):
            raise ValueError("Published resident ride has an inaccessible endpoint")
        if ride:
            outcome = "booked"
        elif places[row[4]][:2] == places[row[5]][:2]:
            outcome = "sameCoordinates"
        else:
            outcome = "access" if any(p not in access for p in row[4:6]) else "unbooked"
        counts.add(*downtown_window(row, places, core), homes[row[0]], outcome, has_rail(ride, rail))
    saved = read(rider_dir / "downtown.json")
    reported_mode = saved["modes"].index("Public transit")
    if saved["areas"] != day["areas"]:
        raise ValueError("Published Downtown counts use different areas")
    return dict(**counts.report(), citywide=dict(demand=published["total"], booked=published["matched"],
                                                excluded=published["excluded"]),
                reportedEndpointTrips={direction: [sum(a[i][reported_mode] for a in h) for h in saved["counts"]]
                                       for i, direction in enumerate(("arriving", "leaving"))})


def incoming_inputs(root, joint_id, joint, version, places):
    family = root / "incoming-transit"
    directory = family / version
    report = read(directory / "report.json")
    fit_id = report["homeFit"]["version"]
    first = family / report["transferComparison"]["version"]
    prior = read(first / "report.json")
    fit = root / "incoming-home-fit" / fit_id
    workers = root / "commuters" / joint["commuters"]
    cohort = read(workers / "commuters.json")
    homes = read(directory / "homes.json")
    names = {key: group["name"] for key, group in cohort["groups"].items()}
    if any(report[k] != prior[k] for k in ("joint", "versions", "workerRelease", "residentRiders", "timetable", "walking", "homeIndex")):
        raise ValueError("The incoming transfer stages use different inputs")
    fit_report = read(fit / "report.json")
    if (report["joint"] != joint_id or report["workerRelease"] != joint["commuters"] or report["versions"] != joint["versions"]
            or report["residentRiders"] != joint["riders"] or report["homeIndex"] != len(places)
            or fit_report["joint"] != joint_id or fit_report["workerRelease"] != joint["commuters"]
            or prior["homeFit"]["version"] != fit_id or homes != read(first / "homes.json")):
        raise ValueError("The incoming worker, home and rider releases differ")
    fitted = {group: {i: new for i, _, new in read(fit / f"{group}.json")} for group in names}
    coordinates = {label.removeprefix("Home census area "): (x, y) for x, y, _, label in homes}
    rows, rebuilt = commute_windows(workers, coordinates, places, cohort, fitted)
    if rebuilt != homes:
        raise ValueError("Reconstructed incoming homes differ from the published anchors")
    places = [*places, *homes]
    identities, before = known_incoming(rows, first, prior)
    _, booked = known_incoming(rows, directory, report)
    if len(identities) != len(rows) or any(booked.get(key) != row for key, row in before.items()):
        raise ValueError("The second transfer stage changed an existing booking")
    return report, prior, first, cohort, names, places, identities, before, booked


def incoming_audit(root, joint_id, joint, version, places, core, processes, checkpoints):
    report, _, first, cohort, names, places, identities, before, booked = incoming_inputs(
        root, joint_id, joint, version, places)
    rows = list(identities.values())
    fit_id = report["homeFit"]["version"]
    schedule = root / "transit" / report["timetable"]
    streets = root / "commuter-walk" / report["walking"]
    service = DirectService(schedule)
    rail = rail_routes(service)
    candidates = {window(row) for row in rows if places[row[4]][:2] != places[row[5]][:2]}
    access, planner = transfer_inputs(candidates, places, service, streets, schedule)
    single = accessible_windows(candidates, access)
    one = connection_options(OneTransferSearch(service, access, planner), single, processes, checkpoints / "one.json",
                             ("census-home", fit_id, schedule.name, streets.name))
    pending = unresolved(identities, before, places)
    double = accessible_windows({window(row) for row in pending}, access)
    two = connection_options(TwoTransfers(planner), double, processes, checkpoints / "two.json",
                             (first.name, schedule.name, streets.name))
    reach = Reach(service, access, planner.connections, report["boardingMargin"])

    feasible = lru_cache(maxsize=16384)(reach.fits)

    counts, citywide = Counts(), Counter()
    for key, row in identities.items():
        start, end, a, b = window(row)
        ride = booked.get(key)
        if ride:
            outcome = "booked"
        elif places[a][:2] == places[b][:2]:
            outcome = "sameCoordinates"
        elif a not in access or b not in access:
            outcome = "access"
        elif one.get(window(row)) or two.get(window(row)):
            outcome = "capacity"
        else:
            outcome = "schedule"
        citywide[outcome] += 1
        slot = downtown_window(row, places, core)
        if not slot:
            continue
        alternative = ()
        if outcome == "schedule":
            if feasible(start, end, a, b):
                alternative = ("reachableInOriginalWindow",)
            elif feasible(*flex_window(row, 30)):
                alternative = ("reachableWith30ExtraMinutes",)
        counts.add(*slot, names[row[0]], outcome, has_rail(ride, rail), alternative)
    published = report["outcomes"]
    if (citywide["booked"] != sum(n for _, n in report["groups"].values())
            or citywide["access"] != published["access"]
            or citywide["sameCoordinates"] != published.get("sameCoordinates", 0)
            or citywide["schedule"] + citywide["capacity"] != published["scheduleOrCapacity"]):
        raise ValueError("Diagnosed incoming outcomes do not reconcile with the incoming release")
    summary = counts.report()
    mode = cohort["modes"].index("Public transit")
    for key, group in cohort["groups"].items():
        for i, direction in enumerate(("arriving", "leaving")):
            observed = [h[i][mode] for h in group["flows"]]
            counted = [h.get("demand", 0) for h in summary["byHome"].get(names[key], {}).get(direction, [{}]*24)]
            if counted != observed:
                raise ValueError(f"Incoming Downtown demand differs from the worker roster for {key}")
    return dict(**summary, citywide=dict(demand=len(rows), **citywide),
                parents=dict(workerRelease=report["workerRelease"], timetable=report["timetable"],
                             walking=report["walking"], homeFit=fit_id, oneTransfer=first.name))


def publish(data, release, processes, checkpoints):
    run = read(data / "runs" / f"{release}.json")
    root = data / "vancouver"
    if (run["release"], run["city"], run["coverage"]) != (release, "vancouver", "city"):
        raise ValueError("Choose a published Vancouver city weekday")
    joint = read(root / "joint-weekday" / run["jointRun"] / "report.json")
    if (any(run[key] != value for key, value in joint["versions"].items())
            or not joint["transfers"] or not joint["capacityChecked"]):
        raise ValueError("The diagnostic needs the combined weekday with capacity-booked resident trips")
    day = root / "cityday" / run["day"]
    places = read(day / "places.json")
    day = read(day / "day.json")
    core = day["areas"].index("Downtown")
    resident = resident_audit(root, joint, day, places, core)
    incoming = incoming_audit(root, run["jointRun"], joint, run["incomingTransit"], places, core, processes, checkpoints)
    path = root / "downtown-audit" / f"{release}-transit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    evidence = dict(schema=1, release=release, joint=run["jointRun"], residentRiders=joint["riders"],
                    incomingTransit=run["incomingTransit"], resident=resident, incoming=incoming)
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
        staged = Path(tmp) / path.name
        write_json(staged, evidence)
        staged.replace(path)
    print(path, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=str)
    parser.add_argument("--data", type=Path, default=Path("public/data"))
    parser.add_argument("--processes", type=int, default=1)
    parser.add_argument("--checkpoints", type=Path, default=Path("target/downtown-transit-audit"))
    args = parser.parse_args()
    if args.processes < 1 or not re.fullmatch(r"[a-f0-9]{64}", args.release):
        parser.error("Choose a 64-character weekday ID and a positive process count")
    publish(args.data, args.release, args.processes, args.checkpoints)
