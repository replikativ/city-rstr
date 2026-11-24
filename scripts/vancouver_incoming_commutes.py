"""Schedule incoming municipal workers alongside the Vancouver resident weekday."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path

from scripts.artifacts import package, pointer, read, write_json
from scripts.vancouver_city_transit import DirectService
from scripts.vancouver_commuter_coverage import carry_bookings, full_timetable, passenger_walks, publish_walks
from scripts.vancouver_downtown import station_counts
from scripts.vancouver_inbound import home_anchors
from scripts.vancouver_incoming_timing import add_timing_slack
from scripts.vancouver_regional_inbound_transit import accessible_windows, add_second_transfers, connection_options
from scripts.vancouver_transit_commutes import BOARDING_MARGIN_SECONDS
from scripts.vancouver_transit_load import ANNUAL_TABLE, TABLE, BusSpaces, bus_capacity_profile, bus_load_evidence, ride_legs
from scripts.vancouver_transit_transfers import MAX_TRANSFER_METRES
from scripts.vancouver_work_transit import choose, match_windows, prepare_windows, transfer_inputs, window


def commute_windows(folder, home_coordinates, places, report, fitted_homes=None):
    homes, rows = [], []
    mode = report["modes"].index("Public transit")
    for group, totals in sorted(report["groups"].items()):
        cohort = read(folder / f"{group}.json")
        home_ids = {da: i for i, da in enumerate(cohort["homes"], len(places)+len(homes))}
        homes.extend([*home_coordinates[da], -1, f"Home census area {da}"] for da in cohort["homes"])
        if len(cohort["people"]) != totals["stock"]:
            raise ValueError("Incoming worker counts differ from the published cohort")
        overrides = fitted_homes.get(group, {}) if fitted_homes else {}
        for i, (home, job, _, _, usual, start, duration, shift, attends, _) in enumerate(cohort["people"]):
            if attends and usual == mode:
                a = home_ids[cohort["homes"][overrides.get(i, home)]]
                if not 0 <= job < len(places) or places[job][2] < 0:
                    raise ValueError("Incoming transit worker has an unresolved workplace")
                rows.extend([(group, i, start, duration, a, job, True),
                             (group, i, start+duration+shift, duration, job, a, False)])
    return rows, homes


class OneTransferSearch:
    def __init__(self, service, access, planner):
        self.direct = service.latest_departure(access, BOARDING_MARGIN_SECONDS)
        self.connection = planner.latest

    def journey(self, start, deadline, origin, destination):
        return choose(self.direct, self.connection, start//60, deadline//60, origin, destination)


def publish(root, archive, joint_id, pbf, two_transfers=False, *, processes=1, checkpoint=None, timing_from=None, home_fit=None,
            reuse_checkpoint=None):
    joint = read(root / "joint-weekday" / joint_id / "report.json")
    versions = joint["versions"]
    if not joint.get("capacityChecked") or not joint.get("transfers"):
        raise ValueError("Incoming commutes require a combined weekday with capacity-booked resident journeys")
    day = root / "cityday" / versions["day"]
    worker_dir = root / "commuters" / joint["commuters"]
    workers = read(worker_dir / "commuters.json")
    if workers["versions"] != {k: versions[k] for k in ("atlas", "day")}:
        raise ValueError("The incoming worker cohort belongs to a different weekday")
    places = read(day / "places.json")
    homes_at = len(places)
    raw = archive / "data/raw"
    family = "incoming-transit"
    index = root / family / f"{joint_id}.json"
    original = root / "transit" / joint["transit"]
    resident_dir = root / "transit-riders" / joint["riders"]
    riders = read(resident_dir / "riders.json")
    if riders["versions"] != dict(versions, transit=joint["transit"], workplaces=joint["workplaces"]["tract-workplaces"]):
        raise ValueError("Resident bookings and the combined weekday have different origins")
    reserved = [leg for da in riders["das"] for row in read(resident_dir / f"{da}.json") for leg in ride_legs(row[6:])]
    probes = raw / "probes"
    fitted_homes, fit = None, None
    if home_fit:
        fit_dir = root / "incoming-home-fit" / home_fit
        fit = read(fit_dir / "report.json")
        if fit["joint"] != joint_id or fit["workerRelease"] != joint["commuters"]:
            raise ValueError("The Census home fit belongs to a different weekday")
        fitted_homes = {g: {i: new for i, _, new in read(fit_dir / f"{g}.json")} for g in workers["groups"]}
    home_index = root / family / f"{joint_id}_homes.json"
    using_reference = bool(two_transfers or timing_from or fit)
    if using_reference:
        base = timing_from or (read(home_index if fit else index)["version"] if two_transfers else fit["baseline"])
        prior = read(root / family / base / "report.json")
        if two_transfers and "transferComparison" in prior:
            base = prior["transferComparison"]["version"]
            prior = read(root / family / base / "report.json")
        if (prior["joint"], prior["workerRelease"], prior["residentRiders"]) != (joint_id, joint["commuters"], joint["riders"]) or "timing" in prior:
            raise ValueError("The previous commute run belongs to a different weekday")
        if two_transfers and fit and prior.get("homeFit", {}).get("version") != home_fit:
            raise ValueError("First publish the one-transfer weekday with these Census-calibrated homes")
        timetable, walking = prior["timetable"], prior["walking"]
        prior_homes = read(root / family / base / "homes.json")
        home_coordinates = {label.removeprefix("Home census area "): (x, y) for x, y, _, label in prior_homes}
    else:
        timetable = full_timetable(root, probes / "transit_translink_gtfs_static.zip", original)
        anchors = home_anchors(raw / "statcan", workers["groups"])
        home_coordinates = {da: (x, y) for group in anchors.values() for da, x, y, *_ in group}
    rows, homes = commute_windows(worker_dir, home_coordinates, places, workers, fitted_homes)
    if using_reference and homes != prior_homes:
        raise ValueError("The previous commute run used different home anchors")
    places += homes
    schedule = root / "transit" / timetable
    booked = carry_bookings(original, schedule, reserved)
    service = DirectService(schedule)
    if not using_reference:
        endpoints = {index for row in rows for index in row[4:6]}
        walking = publish_walks(root, pbf, [*service.stations, *(places[i][:2] for i in sorted(endpoints))])
    streets = root / "commuter-walk" / walking
    manifest = service.route_manifest
    table = probes / TABLE
    capacity = bus_capacity_profile(manifest, table, probes / ANNUAL_TABLE)
    spaces = BusSpaces(capacity["limits"])
    spaces.preload(booked)
    print(f"Fitting {len(rows):,} work trips from outside the City of Vancouver", flush=True)
    timing, recovered = None, []
    if timing_from:
        assigned, outcomes, timing, recovered = add_timing_slack(rows, places, service, streets, schedule, spaces, root / family / base, prior,
                                                               workers=processes, checkpoint=checkpoint)
        missing = prior["missingStopAccess"]
    elif two_transfers:
        previous = None
        if reuse_checkpoint:
            old_directory = root / family / fit["baseline"]
            old_report = read(old_directory / "report.json")
            if (old_report["timetable"], old_report["walking"]) != (timetable, walking):
                raise ValueError("Reusing itinerary searches requires the same timetable and pedestrian graph")
            old_rows, _ = commute_windows(worker_dir, home_coordinates, places[:homes_at], workers)
            previous = old_rows, old_directory, old_report, reuse_checkpoint
        assigned, outcomes = add_second_transfers(rows, places, service, streets, schedule, spaces, root / family / base, prior,
                                                  workers=processes, checkpoint=checkpoint, reuse=previous)
        missing = prior["missingStopAccess"]
    else:
        if fit:
            windows = {window(row) for row in rows if places[row[4]][:2] != places[row[5]][:2]}
            access, planner = transfer_inputs(windows, places, service, streets, schedule)
            accessible = accessible_windows(windows, access)
            print(f"Checking {len(accessible):,} windows using Census-calibrated homes", flush=True)
            choices = connection_options(OneTransferSearch(service, access, planner), accessible, processes, checkpoint,
                                         ("census-home", home_fit, timetable, walking))
        else:
            access, planner, choices = prepare_windows(rows, places, service, streets, schedule)
        assigned, outcomes = match_windows(rows, choices, access, service, planner, spaces, places,
                                           category=lambda inbound: "towardWork" if inbound else "fromWork")
        missing = Counter()
        for row in rows:
            a, b = row[4:6]
            if places[a][:2] == places[b][:2]:
                continue
            home, work = (a, b) if row[-1] else (b, a)
            if home not in access or work not in access:
                missing["both" if home not in access and work not in access else "home" if home not in access else "work"] += 1
    if sum(missing.values()) != outcomes.get("access", 0):
        raise ValueError("Incoming access rejections do not reconcile")
    groups = defaultdict(list)
    examples, ranks = {}, {}
    examples_by_origin, ranks_by_origin = defaultdict(dict), defaultdict(dict)
    downtown = read(day / "day.json")["areas"].index("Downtown")
    rail_routes = {r["id"] for r in manifest["routes"] if r["type"] == 1}
    restored = {tuple(row[:3]) for row in recovered}
    for row, inbound in assigned:
        group, person, start, _, a, b = row[:6]
        groups[group].append(row)
        key = "towardWork" if inbound else "fromWork"
        changed = bool(timing) and (group, person, start) in restored or bool(fit) and person in fitted_homes[group]
        rank = ((bool(timing) or bool(fit)) and not changed, places[b if inbound else a][2] != downtown,
                not any(leg[0] in rail_routes for leg in ride_legs(row[6:])),
                abs(start - (480 if inbound else 1020)), group, person)
        if key not in ranks or rank < ranks[key]:
            ranks[key], examples[key] = rank, row
        if key not in ranks_by_origin[group] or rank < ranks_by_origin[group][key]:
            ranks_by_origin[group][key], examples_by_origin[group][key] = rank, row
    trips = [row for row, _ in assigned]
    bus = bus_load_evidence(schedule, manifest, trips, table, capacity["limits"], reserved=booked)
    if bus["above"]:
        raise ValueError("Incoming transit journeys exceed the shared bus capacity")
    rail_table = probes / "transit_translink_tspr2025_skytrainavgalightsbrdgs_yearstationdaytypehourly.csv"
    rail = station_counts(rail_table, schedule, manifest, groups, by_origin=True)
    rail_by_origin = rail.pop("byOrigin")
    if any(rail["matched"][h][d] != sum(counts[h][d] for counts in rail_by_origin.values())
           for h in range(24) for d in range(2)):
        raise ValueError("Incoming station counts do not reconcile across home municipalities")
    paths = passenger_walks(read(streets / "network.json"), service, places, trips)
    eligible = Counter(row[0] for row in rows)
    report = dict(joint=joint_id, versions=versions, workerRelease=joint["commuters"], residentRiders=joint["riders"],
                  timetable=timetable, walking=walking, serviceDate=manifest["date"], reservedLegs=len(booked),
                  homeIndex=homes_at, outcomes=outcomes, missingStopAccess=dict(missing), capacitySources=capacity["sources"],
                  boardingMargin=BOARDING_MARGIN_SECONDS, transferWalkLimit=MAX_TRANSFER_METRES,
                  groups={g: [n, len(groups[g])] for g,n in sorted(eligible.items())}, examples=examples,
                  examplesByOrigin=examples_by_origin,
                  bus=bus, rail=rail, railByOrigin=rail_by_origin)
    if two_transfers:
        report["transferComparison"] = dict(version=base, retained=sum(n for _,n in prior["groups"].values()),
                                            added=outcomes.get("twoTransfers", 0))
    if timing:
        report["timing"] = timing
    if fit:
        comparison = read(index)["version"] if two_transfers else fit["baseline"]
        reference = read(root / family / comparison / "report.json")
        if two_transfers and reference.get("transferComparison", {}).get("version") != fit["baseline"]:
            raise ValueError("The original home comparison requires a published two-transfer weekday")
        before = {tuple(row[:3]) for g, (_, matched) in reference["groups"].items() if matched
                  for row in read(root / family / comparison / f"{g}.json")}
        after = {tuple(row[:3]) for row in trips}
        report["homeFit"] = dict(version=home_fit, baseline=comparison, fitBasis=fit["baseline"], source=fit["source"], retained=len(before & after),
                                 added=len(after-before), lost=len(before-after),
                                 **{field: sum(g[field] for g in fit["groups"].values())
                                    for field in ("moved", "errorBefore", "errorAfter", "supportedWorkers")})

    def stage(out):
        write_json(out / "report.json", report)
        write_json(out / "homes.json", homes)
        for group, journeys in groups.items():
            if journeys:
                write_json(out / f"{group}.json", journeys)
                write_json(out / f"{group}-walks.json", paths[group])

    release = package(root, family, stage)
    if timing:
        from scripts.vancouver_incoming_timing_presence import publish as publish_timing_presence
        publish_timing_presence(root, release, "jvm")
    from scripts.vancouver_incoming_pedestrians import publish as publish_incoming_pedestrians
    publish_incoming_pedestrians(root, release)
    if timing:
        index = root / family / f"{joint_id}_timing.json"
    if fit:
        index = home_index
    pointer(index, {"version": release})
    print(release, len(trips), outcomes, flush=True)
    return release


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("joint")
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--pbf", type=Path, default=Path("data/region/vancouver.osm.pbf"))
    comparison = parser.add_mutually_exclusive_group()
    comparison.add_argument("--two-transfers", action="store_true", help="Extend the published run with a second transfer")
    comparison.add_argument("--timing-from", help="Test longer commute windows using the pinned incoming transit release")
    parser.add_argument("--home-fit", help="Replay the Census-calibrated incoming worker homes")
    parser.add_argument("--processes", type=int, default=1, help="Parallel processes for independent schedule searches")
    parser.add_argument("--checkpoint", type=Path, help="Save and resume the independent schedule searches")
    parser.add_argument("--reuse-checkpoint", type=Path, help="Reuse identical two-transfer searches from the original home locations")
    args = parser.parse_args()
    if args.processes < 1:
        parser.error("--processes must be positive")
    if args.home_fit and args.timing_from or args.reuse_checkpoint and not (args.two_transfers and args.home_fit):
        parser.error("Reuse requires a two-transfer home fit comparison. The timing comparison uses its own pinned release.")
    publish(args.root, args.archive, args.joint, args.pbf, args.two_transfers,
            processes=args.processes, checkpoint=args.checkpoint, timing_from=args.timing_from, home_fit=args.home_fit,
            reuse_checkpoint=args.reuse_checkpoint)
