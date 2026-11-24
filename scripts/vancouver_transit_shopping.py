"""Book both legs of a work-to-shop transit chain against the combined weekday."""
import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import math
from pathlib import Path
import tempfile

import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_campus import access_routes
from scripts.vancouver_city_transit import DirectService, transit_parts
from scripts.vancouver_commuter_coverage import passenger_walks
from scripts.vancouver_discretionary_outings import verify_intervals
from scripts.vancouver_outbound_transit import Bookings, reservations
from scripts.vancouver_region import package, read
from scripts.vancouver_shopping_outings import named_stores
from scripts.vancouver_street_scenarios import ACCESS, bounds, candidate
from scripts.vancouver_transit_commutes import BOARDING_MARGIN_SECONDS, pointer
from scripts.vancouver_transit_load import ANNUAL_TABLE, TABLE, BusSpaces, bus_capacity_profile, bus_load_evidence, ride_legs
from scripts.vancouver_transit_reach import Reach
from scripts.vancouver_transit_transfers import walk_transfers
from scripts.vancouver_work_transit import GTFS_SOURCE, priority

START = 990


def template_chain(diary, template):
    episodes = {r[0]: r for r in diary["episodes"]}
    legs = {s: n for s, n, _, _, pure in transit_parts(template, diary) if pure}
    parts, slots = template["parts"], template["slots"]
    for work, there, shop, onward, following in zip(parts, parts[1:], parts[2:], parts[3:], parts[4:]):
        start, inward, _, a, b = there
        leave, outward, _, _, c = onward
        arrive, dwell, mode, _, _ = shop
        if (start == START and legs.get(start) == inward and legs.get(leave) == outward
                and work[2] == mode == following[2] == "stop"
                and slots[a] == "job" and slots[b] == "store" and slots[c] != "job"
                and episodes.get(arrive) == [arrive, dwell, "shopping", "store"]
                and any(s + n == start and act == "paid-work" for s, n, act, _ in diary["episodes"])):
            return a, b, c, inward, arrive, leave, outward
    return None


def cohort(root, joint, places):
    versions = joint["versions"]
    atlas_dir = root / "atlas" / versions["atlas"]
    day_dir = root / "cityday" / versions["day"]
    atlas, day = read(atlas_dir / "atlas.json"), read(day_dir / "day.json")
    layout = read(root / "tract-workplaces" / joint["workplaces"]["tract-workplaces"] / "worksites.json")
    external = read(root / "outbound" / joint["workplaces"]["outbound"] / "assignments.json")
    if not layout.get("preserveDiaryModes") or any(layout[k] != v for k, v in versions.items()):
        raise ValueError("This comparison requires the combined weekday's pinned workplace layout")
    changed = {(d, i, slot): dest for d, i, slot, _, dest in layout["changes"]}
    templates = [template_chain(a, b) for a, b in zip(atlas["templates"], day["templates"], strict=True)]
    rider_dir = root / "transit-riders" / joint["riders"]
    areas = set(read(rider_dir / "riders.json")["das"])
    residents, stats = [], Counter()
    for d, da in enumerate(day["das"]):
        file = da + ".json"
        people = read(atlas_dir / file)["people"][:atlas["das"][da]["private"]]
        plans = read(day_dir / file)["plans"]
        outside = {i for i, *_ in external[d]}
        keys = {(r[1], r[2]): r for r in read(rider_dir / file)} if da in areas else {}
        for i, (person, plan) in enumerate(zip(people, plans)):
            if not 3 <= person[0] <= 13 or not (chain := templates[person[-1]]):
                continue
            a, b, c, there, arrive, leave, back = chain
            stats["residents"] += 1
            booked = [keys.get((i, s)) for s in (START, leave)]
            stats["priorWorkToShop"] += bool(booked[0])
            stats["priorShopToNext"] += bool(booked[1])
            if all(booked):
                stats["priorComplete"] += 1
                continue
            if i in outside:
                stats["outsideWorkplace"] += 1
                continue
            job, original, next_stop = [changed.get((d, i, slot), plan[slot]) for slot in (a, b, c)]
            if min(job, original, next_stop) < 0 or any(places[p][2] < 0 for p in (job, original, next_stop)):
                stats["missingPlace"] += 1
                continue
            windows = [(START, there, job, False), (leave, back, next_stop, True)]
            for row, (start, duration, anchor, returning) in zip(booked, windows):
                endpoints = (original, anchor) if returning else (anchor, original)
                if row and row[2:6] != [start, duration, *endpoints]:
                    raise ValueError("A retained booking disagrees with the combined resident plan")
            residents.append((da, i, original, arrive, leave, windows, [bool(r) for r in booked]))
    return day, residents, stats


def find_candidates(residents, sites, named, reach, places, stats):
    destinations = reach.destinations(sites)
    positions = np.asarray([p[:2] for p in places], dtype=np.int32)

    @lru_cache(maxsize=384)
    def query(start, duration, anchor, returning):
        arrival = reach.query(anchor, start, duration, returning, destinations)
        return arrival <= (-start if returning else start + duration) * 60

    site_index = {position: idx for idx, position in enumerate(sites)}
    pending = []
    for record in residents:
        _, _, original, _, _, windows, booked = record
        if any(w[2] not in reach.access for w, prior in zip(windows, booked) if not prior):
            stats["noAnchorAccess"] += 1
            continue
        # A resident with either leg already booked can only use their existing shop.
        if any(booked):
            j = site_index[original]
            available = all(prior or query(*window)[j] for prior, window in zip(booked, windows))
            candidates = [original] if available else []
        else:
            mask = query(*windows[0]) & query(*windows[1])
            candidates = [sites[j] for j in np.flatnonzero(mask)]
        candidates = [site for site in candidates if (site == original or site in named)
                      and all(not np.array_equal(positions[site], positions[w[2]]) for w in windows)]
        if not candidates:
            stats["noSameShopInTimetable"] += 1
            continue
        coords = positions[candidates] - positions[original]
        metres2 = (coords.astype(np.int64)**2).sum(axis=1)
        order = np.lexsort((candidates, metres2))
        pending.append((record, [candidates[k] for k in order]))
    return pending


def assign(pending, planner, service, stats):
    def rank(pair):
        (da, i, _, _, _, windows, _), sites = pair
        return len(sites), priority((da, i, *windows[0][:2]))

    result = defaultdict(list)
    for (da, i, original, arrive, leave, windows, booked), sites in sorted(pending, key=rank):
        missing = [w for w, retained in zip(windows, booked) if not retained]
        for site in sites:
            rows = planner.circuit(da, i, missing, site)
            if not rows:
                continue
            starts = []
            for row in rows:
                board_at, _ = service.ride_times(row[6:])
                start = (board_at - row[10] - BOARDING_MARGIN_SECONDS) // 60
                if not row[2] <= start < row[2] + row[3]:
                    raise ValueError("The scheduled departure is outside the original window")
                starts.append(start)
            result[da].append([i, original, site, arrive, leave, starts, rows])
            stats["completed"] += 1
            stats["changedStore"] += site != original
            stats["additionalLegs"] += len(rows)
            stats["additionalWorkToShop"] += not booked[0]
            stats["additionalShopToNext"] += not booked[1]
            stats["shiftedWorkDepartures"] += not booked[0] and starts[0] > START
            break
        else:
            stats["noBookedPair"] += 1
    return result


def occupancy(result, places, base, scratch, backend):
    cols = len(base[0])
    delta = np.zeros((1441, cols), dtype=np.int32)
    schedules = []
    for rows in result.values():
        for _, original, shop, arrive, leave, starts, legs in rows:
            phases = [(arrive, leave, places[original][2], places[shop][2])]
            phases.extend((leg[2], start, cols - 2, places[leg[4]][2]) for start, leg in zip(starts, legs, strict=True))
            changes = []
            for a, b, before, after in phases:
                if a == b or before == after:
                    continue
                lo, hi = a - 240, b - 240
                delta[lo:hi, before] -= 1
                delta[lo:hi, after] += 1
                changes.append((lo * cols + before, hi * cols + before, after - before))
            if changes:
                schedules.append(tuple(changes))
    return verify_intervals(schedules, delta, base, scratch, backend)


def read_reservations(root, joint_id, joint, incoming_id, outbound_id):
    incoming_dir = root / "incoming-transit" / incoming_id
    outgoing = root / "outbound-transit" / outbound_id
    incoming, outbound = read(incoming_dir / "report.json"), read(outgoing / "report.json")
    if (incoming["joint"] != joint_id or outbound["joint"] != joint_id or outbound["incoming"] != incoming_id
            or incoming["residentRiders"] != joint["riders"] or incoming["versions"] != joint["versions"]
            or outbound["workplaces"] != joint["workplaces"] or outbound["versions"] != joint["versions"]
            or outbound["timetable"] != incoming["timetable"] or outbound["walking"] != incoming["walking"]):
        raise ValueError("The external bookings have a different timetable or weekday")
    reserved = reservations(root, joint, incoming)
    for group, (_, matches) in incoming["groups"].items():
        if matches:
            reserved.extend(leg for row in read(incoming_dir / f"{group}.json") for leg in ride_legs(row[6:]))
    if len(reserved) != outbound["reservedLegs"]:
        raise ValueError("The resident and incoming booking totals disagree")
    for da in outbound["areas"]:
        reserved.extend(leg for _, _, _, rows in read(outgoing / f"{da}.json") for row in rows for leg in ride_legs(row[6:]))
    return incoming, reserved


def publish(root, archive, joint_id, incoming_id, outbound_id, backend):
    joint_dir = root / "joint-weekday" / joint_id
    joint = read(joint_dir / "report.json")
    incoming, reserved = read_reservations(root, joint_id, joint, incoming_id, outbound_id)
    schedule = root / "transit" / incoming["timetable"]
    walk = root / "commuter-walk" / incoming["walking"]
    versions = joint["versions"]
    places = read(root / "cityday" / versions["day"] / "places.json")
    day, residents, stats = cohort(root, joint, places)
    named = set(named_stores(archive, places))
    sites = sorted(named | {r[2] for r in residents})
    endpoints = set(sites) | {w[2] for r in residents for w in r[5]}
    service = DirectService(schedule)
    print("Checking", len(residents), "chains and", len(sites), "shops", flush=True)
    access = access_routes(places, endpoints, service.stations, walk)
    paths = walk_transfers(service, read(schedule / "transfers.json")["pairs"], walk / "network.json", BOARDING_MARGIN_SECONDS)
    reach = Reach(service, access, paths, BOARDING_MARGIN_SECONDS)
    probes = archive / "data/raw/probes"
    profile = bus_capacity_profile(service.route_manifest, probes / TABLE, probes / ANNUAL_TABLE)
    spaces = BusSpaces(profile["limits"])
    spaces.preload(reserved)
    pending = find_candidates(residents, sites, named, reach, places, stats)
    print("Timetable screen accepts", len(pending), "complete chains", flush=True)
    result = assign(pending, Bookings(service, access, paths, spaces), service, stats)
    print(dict(stats), flush=True)
    booked = [leg for rows in result.values() for *_, legs in rows for leg in legs]
    bus = bus_load_evidence(schedule, service.route_manifest, booked, probes / TABLE, profile["limits"], reserved=reserved)
    if bus["above"] or not booked or len(booked) != stats["additionalLegs"]:
        raise ValueError("Expected additional bookings with no increase above modeled bus capacity")
    if (sum(stats[k] for k in ("priorComplete", "outsideWorkplace", "missingPlace", "noAnchorAccess",
                              "noSameShopInTimetable", "completed", "noBookedPair")) != stats["residents"]):
        raise ValueError("Outcomes do not reconcile with the diary cohort")
    walks = passenger_walks(read(walk / "network.json"), service, places, booked)
    dat = {da: d for d, da in enumerate(day["das"])}
    street = []
    for da, rows in result.items():
        for i, _, _, _, _, starts, legs in rows:
            for start, row in zip(starts, legs, strict=True):
                _, _, recorded, duration, a, b, *ride = row
                end = recorded + duration
                extent = bounds([places[a], places[b]], ACCESS)
                for transfer in ride_legs(ride):
                    route, run, board, alight = transfer
                    extent = merge_bounds(extent, bounds([service.stations[service.ride_platforms[route][run][j]]
                                                          for j in (board, alight)], ACCESS))
                street.append(candidate(dat[da], i, start, end, extent, True))
    with tempfile.TemporaryDirectory() as temp:
        change = occupancy(result, places, read(joint_dir / "occupancy.json"), Path(temp), backend)
    example_da, example = max(((da, row) for da, rows in result.items() for row in rows),
                              key=lambda pair: (pair[1][2] != pair[1][1], len(pair[1][-1]),
                                                -pair[1][-2][0], pair[0], -pair[1][0]))
    displacements = [math.dist(places[old][:2], places[site][:2]) for rows in result.values()
                     for _, old, site, *_ in rows if old != site]
    departures = Counter(start for rows in result.values() for *_, starts, legs in rows
                         for start, leg in zip(starts, legs, strict=True) if leg[2] == START)
    report = dict(schema=1, joint=joint_id, versions=versions, workplaces=joint["workplaces"],
                  riders=joint["riders"], incoming=incoming_id, outbound=outbound_id,
                  timetable=incoming["timetable"], walking=incoming["walking"], serviceDate=service.route_manifest["date"],
                  source=GTFS_SOURCE, capacitySources=profile["sources"], bus=bus, reservedLegs=len(reserved),
                  boardingMargin=BOARDING_MARGIN_SECONDS, transferLimit=2, stores=len(named), counts=dict(stats),
                  medianDisplacement=round(float(np.median(displacements)), 1) if displacements else 0,
                  departureMinutes=sorted(departures.items()), population=day["population"],
                  example=[example_da, example[0]], areas=sorted(result), **change)

    def build(folder):
        write_json(folder / "report.json", report)
        write_json(folder / "street.json", sorted(street))
        for da, rows in result.items():
            write_json(folder / f"{da}.json", sorted(rows))
            write_json(folder / f"{da}-walks.json", sorted(walks[da]))

    version = package(root, "transit-shopping", build)
    pointer(root / "transit-shopping" / f"{joint_id}_{incoming_id}_{outbound_id}.json", {"version": version})
    print(version, dict(stats), flush=True)
    return version


def merge_bounds(a, b):
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("joint")
    parser.add_argument("incoming")
    parser.add_argument("outbound")
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--backend", default="jvm")
    args = parser.parse_args()
    publish(args.root, args.archive, args.joint, args.incoming, args.outbound, args.backend)
