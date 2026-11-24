"""Time the direct work commute against the archived TransLink timetable."""
import argparse
from collections import Counter
from datetime import date
from functools import lru_cache
from pathlib import Path
import subprocess
import tempfile

from scripts.vancouver_atlas import write_json
from scripts.vancouver_campus import access_routes
from scripts.vancouver_city_transit import DirectService
from scripts.vancouver_region import NAMES, package, read
from scripts.vancouver_transit import build as timetable
from scripts.vancouver_transit_load import ANNUAL_TABLE, TABLE as BUS_LOAD_TABLE
from scripts.vancouver_transit_load import BusSpaces, bus_capacity_profile, bus_load_evidence, rider_order
from scripts.vancouver_transit_transfers import MAX_TRANSFER_METRES, OneTransfer, walk_transfers

BOARDING_MARGIN_SECONDS = 180


def pointer(path, info):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
        pending = Path(tmp) / "pointer"
        write_json(pending, info)
        pending.replace(path)


def capacity_order(item):
    (da, person, _, start, duration, _, _), _ = item
    return rider_order(da, person, start, duration)


def match_clock(rows, places, home_area, service, street_dir, transfers=None, limits=None):
    endpoints = {p for row in rows for p in row[-2:]}
    access = access_routes(places, endpoints, service.stations, street_dir)
    latest = lru_cache(maxsize=65536)(service.latest_departure(access, BOARDING_MARGIN_SECONDS))
    if transfers is not None:
        connections = walk_transfers(service, transfers, street_dir / "network.json", BOARDING_MARGIN_SECONDS)
        print(f"Checking {sum(map(len, connections.values())):,} walkable transfer pairs.", flush=True)
        planner = OneTransfer(service, access, connections, BOARDING_MARGIN_SECONDS)
        # Consecutive requests to the same workplace at the same time reuse
        # the backwards labels without retaining a citywide routing table.
        rows = sorted(rows, key=lambda row: (row[6], row[3] + row[4], row[0], row[1]))
    else:
        planner = None
    changes, rides, candidates = [], [], []
    rerouted = set()
    spaces = BusSpaces(limits) if limits is not None else None
    fields = ("eligible", "changed", "longBefore", "longAfter", "minutesSaved")
    if planner:
        fields += ("directChanged", "directLongAfter", "transferTrips")
    if spaces:
        fields += ("withoutCapacityChanged", "withoutCapacityLongAfter", "foundAlternative", "noLaterWithCapacity")
    counts = {}

    for da, person, tpl, start, duration, a, b in rows:
        area = home_area[da]
        stats = counts.setdefault(area, dict.fromkeys(fields, 0))
        stats["eligible"] += 1
        stats["longBefore"] += int(duration >= 60)
        stats["longAfter"] += int(duration >= 60)
        end = start + duration
        choice = latest(end * 60, a, b) if a in access and b in access else None
        if planner:
            direct = choice and choice[0] > start
            stats["directChanged"] += int(bool(direct))
            stats["directLongAfter"] += int(end - choice[0] >= 60 if direct else duration >= 60)
            transfer = planner.latest(end * 60, a, b) if a in access and b in access else None
            if transfer and transfer[0] > max(start, choice[0] if choice else start):
                choice = transfer
        if choice and choice[0] > start:
            candidates.append(((da, person, tpl, start, duration, a, b), choice))
        if spaces:
            stats["withoutCapacityLongAfter"] += int(end - max(start, choice[0] if choice else start) >= 60)

    if spaces:
        candidates.sort(key=capacity_order)
        available = spaces.available
        capped_direct = service.latest_departure(access, BOARDING_MARGIN_SECONDS, available)
    for (da, person, tpl, start, duration, a, b), choice in candidates:
        stats = counts[home_area[da]]
        end = start + duration
        if spaces:
            stats["withoutCapacityChanged"] += 1
            if not spaces.fits(choice[2]):
                choice = capped_direct(end * 60, a, b)
                transfer = planner.latest(end * 60, a, b, available) if planner else None
                if transfer and transfer[0] > max(start, choice[0] if choice else start):
                    choice = transfer
                if choice is None or choice[0] <= start:
                    stats["noLaterWithCapacity"] += 1
                    continue
                stats["foundAlternative"] += 1
                rerouted.add((da, person))
            spaces.reserve(choice[2])
        departure, _, ride = choice
        changes.append([da, person, tpl, departure])
        rides.append([da, person, departure, end - departure, a, b, *ride])
        stats["changed"] += 1
        stats["minutesSaved"] += departure - start
        stats["longAfter"] += int(end - departure >= 60) - int(duration >= 60)
        if planner and len(ride) > 6:
            stats["transferTrips"] += 1

    counts["Regional residents"] = {key: sum(area[key] for area in counts.values()) for key in fields}
    return changes, rides, counts, rerouted


def build(archive, region, workplace_run, service_date, transit=None, *, transfers=False, capacity=False):
    parents = read(region / "current.json")
    workday = parents
    if workplace_run:
        pair = read(region / "regional-workplaces" / workplace_run / "report.json")
        workday = dict(pair["versions"], day=pair["day"])
    atlas_dir = region / "atlas" / workday["atlas"]
    day_dir = region / "cityday" / workday["day"]
    streets = workday["streets"]
    atlas = read(atlas_dir / "atlas.json")
    if transit is None:
        areas = {k: detail["geometry"] for k, detail in atlas["areas"].items()}
        feed = archive / "data/raw/probes/transit_translink_gtfs_static.zip"
        transit = package(region, "transit", lambda out: timetable(feed, areas, service_date, out,
                                                                  passenger_rules=True, transfer_rules=transfers))
    schedule = region / "transit" / transit
    service = DirectService(schedule)
    transfer_input = read(schedule / "transfers.json") if transfers else None
    observed = archive / "data/raw/probes" / BUS_LOAD_TABLE
    bus_profile = None
    if capacity:
        annual = observed.with_name(ANNUAL_TABLE)
        bus_profile = bus_capacity_profile(service.route_manifest, observed, annual if annual.is_file() else None)
    if service.route_manifest["date"] != service_date.isoformat():
        raise ValueError("The transit timetable is dated differently from the requested service")
    home_area = {da: group if group in NAMES.values() or group.startswith("UBC ") else "Vancouver"
                 for group, detail in atlas["areas"].items() for da in detail["das"]}

    with tempfile.TemporaryDirectory() as tmp:
        file = Path(tmp) / "revision.json"
        cmd = ["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.transit-commutes"]
        subprocess.run([*cmd, "prepare", atlas_dir, day_dir, file], check=True)
        rows = read(file)
        print(f"Checking {len(rows):,} direct work commutes with {len(service.stations):,} scheduled stop locations.", flush=True)
        places = read(day_dir / "places.json")
        changes, rides, counts, rerouted = match_clock(
            rows, places, home_area, service, region / "streets" / streets,
            transfer_input["pairs"] if transfers else None, bus_profile["limits"] if capacity else None)
        if not changes:
            raise ValueError("No resident commute can leave later on this weekday")
        templates = Counter(tpl for _, _, tpl, _ in changes)
        starts = {(da, i): start for da, i, _, start, *_ in rows}
        example = min(zip(changes, rides, strict=True),
                      key=lambda row: (tuple(row[0][:2]) not in rerouted if capacity else False,
                                       len(row[1]) == 12 if transfers else False,
                                       -templates[row[0][2]], abs(row[1][2] - 480), row[0][:2]))
        (da, i, _, departure), ride = example
        info = dict(streets=streets, transit=transit, timetable=service.route_manifest["date"],
                    boardingMargin=BOARDING_MARGIN_SECONDS, workplaceRun=workplace_run,
                    areas=counts, changedByTemplate=sorted(templates.items()),
                    example=dict(da=da, person=i, before=starts[da, i], after=departure, ride=ride))
        if transfers:
            info["transferWalkMetres"] = MAX_TRANSFER_METRES
        if capacity:
            info["busCapacity"] = bus_profile
            info["example"]["capacityRerouted"] = (da, i) in rerouted
        if (transfers or capacity) and observed.is_file():
            info["busLoadEvidence"] = bus_load_evidence(
                schedule, service.route_manifest, rides, observed, bus_profile["limits"] if capacity else None)
            if capacity and info["busLoadEvidence"]["above"]:
                raise ValueError("The published bus assignment breaches the reservation limits")
        write_json(file, dict(revisions=changes, rides=rides, report=info))
        version = package(region, "household-clock",
                          lambda out: subprocess.run([*cmd, "publish", atlas_dir, day_dir, file, out], check=True))
    key = workday["atlas"] + "_" + workday["day"] + ".json"
    history = region / "releases" / key
    if not history.exists():
        pointer(history, {k: workday[k] for k in ("atlas", "day", "streets", "transit")})
    pointer(region / "transit-commutes" / key, dict(version=version))
    print(version, counts, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--workplace-run", help="Use the paired census workplaces as the base day")
    parser.add_argument("--timetable", help="Reuse an existing regional timetable published with passenger rules")
    parser.add_argument("--transfers", action="store_true", help="Allow one change of vehicle under published transfer rules")
    parser.add_argument("--bus-capacity", action="store_true", help="Share each bus's route-level capacity over all revised trips")
    parser.add_argument("--date", type=date.fromisoformat, default=date(2026, 9, 15))
    args = parser.parse_args()
    build(args.archive, args.region, args.workplace_run, args.date, args.timetable,
          transfers=args.transfers, capacity=args.bus_capacity)
