"""Fit dated, direct TransLink rides to the Vancouver resident weekday."""
import argparse
import csv
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import date
from functools import lru_cache
from itertools import chain
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from scripts.artifacts import package, read, write_json
from scripts.vancouver_downtown import resident_flows, station_counts
from scripts.vancouver_campus import ACCESS_METRES, WALK_METRES_PER_SECOND, access_routes
from scripts.vancouver_transit import build as build_timetable
from scripts.vancouver_transit_load import TABLE, BusSpaces, book_connections, book_direct, bus_capacity_profile, bus_load_evidence
from scripts.vancouver_transit_transfers import MAX_TRANSFER_METRES, OneTransfer, walk_transfers


def transit_parts(template, source):
    for start, duration, mode, a, b in template["parts"]:
        if mode == "stop":
            continue
        modes = {ep[3] for ep in source["episodes"] if start <= ep[0] < start + duration}
        if "transit" in modes:
            yield start, duration, a, b, modes <= {"transit", "walk"}


def resident_trips(atlas_dir, day_dir):
    atlas, day = read(atlas_dir / "atlas.json"), read(day_dir / "day.json")
    templates = [list(transit_parts(t, s)) for t, s in zip(day["templates"], atlas["templates"], strict=True)]
    bouts = []
    excluded = Counter()
    for da in day["das"]:
        people = read(atlas_dir / (da + ".json"))["people"]
        plans = read(day_dir / (da + ".json"))["plans"]
        for i, (person, plan) in enumerate(zip(people, plans, strict=True)):
            for start, duration, origin, dest, pure in templates[person[7]]:
                if not pure:
                    excluded["mixed"] += 1
                elif min(origin, dest) < 0 or min(plan[origin], plan[dest]) < 0:
                    excluded["unlocated"] += 1
                else:
                    bouts.append((da, i, start, duration, plan[origin], plan[dest]))
    return bouts, excluded


class DirectService:
    def __init__(self, directory):
        self.route_manifest = read(directory / "transit.json")
        stations = {}
        self.board = defaultdict(list)
        self.alight = defaultdict(list)
        self.patterns = []
        self.mapped = []
        self.platforms = {}
        self.pattern_platforms = []
        self.access_rules = []
        self.run_clocks = {}
        self.ride_platforms = {}
        for route in self.route_manifest["routes"]:
            data = read(directory / (route["id"] + ".json"))
            self.run_clocks[route["id"]] = [(start, offsets) for _, start, offsets, _ in data["rides"]]
            station_ids = [stations.setdefault(tuple(s[:2]), len(stations)) for s in data["stations"]]
            platform_patterns = [tuple(station_ids[s] for s in p["stops"]) for p in data["patterns"]]
            self.ride_platforms[route["id"]] = [platform_patterns[p] for p, *_ in data["rides"]]
            stop_ids = data.get("stopIds")
            if stop_ids is not None:
                for stop_id, station in zip(stop_ids, station_ids, strict=True):
                    if self.platforms.setdefault(stop_id, station) != station:
                        raise ValueError("A transit platform has inconsistent coordinates")
            by_pattern = defaultdict(list)
            for ride, (pattern, start, offsets, _) in enumerate(data["rides"]):
                by_pattern[pattern].append((ride, np.asarray(offsets, dtype=np.int32) + start))
            for pi, pattern in enumerate(data["patterns"]):
                pid = len(self.patterns)
                stops = [station_ids[s] for s in pattern["stops"]]
                rides, timetable = zip(*by_pattern[pi])
                times = np.stack(timetable)
                self.patterns.append((route["id"], stops, np.asarray(rides), times))
                self.mapped.append(pattern.get("mapped", False))
                self.pattern_platforms.append(tuple(stop_ids[s] for s in pattern["stops"]) if stop_ids is not None else None)
                self.access_rules.append(pattern["access"])
                for j, (stop, rule) in enumerate(zip(stops, pattern["access"], strict=True)):
                    if j + 1 < len(stops) and rule & 1:
                        self.board[stop].append((pid, j))
                    if j and rule & 2:
                        self.alight[stop].append((pid, j))
        self.stations = list(stations)

    def ride_times(self, itinerary):
        route, trip, board, alight, *_ = itinerary
        start, seconds = self.run_clocks[route][trip]
        return start + seconds[2*board+1], start + seconds[2*alight]

    @lru_cache(maxsize=32768)
    def connections(self, pid, board, alight):
        # Overtaking is possible. For each departure, cache the best arrival
        # among it and all later departures, independently for each stop pair.
        _, _, ids, times = self.patterns[pid]
        dep, arr = times[:, 2 * board + 1], times[:, 2 * alight]
        valid = np.flatnonzero(arr > dep)
        order = valid[np.argsort(dep[valid], kind="stable")]
        best = [None] * len(order)
        winner = None
        for j in reversed(range(len(order))):
            k = order[j]
            option = (int(arr[k]), int(ids[k]))
            winner = min(winner, option) if winner else option
            best[j] = winner
        return dep[order].tolist(), best

    def accessible_positions(self, access):
        @lru_cache(maxsize=8192)
        def positions(place, boarding):
            options = defaultdict(list)
            index = self.board if boarding else self.alight
            for station, seconds in access.get(place, {}).items():
                for pid, pos in index[station]:
                    options[pid].append((pos, station, seconds))
            return options

        return positions

    def matcher(self, access, *, boarding_margin=0, mapped_only=False, available=None, arrival_time=False):
        positions = self.accessible_positions(access)

        def match(start, duration, a, b):
            first, end = start * 60, (start + duration) * 60
            boards, alights = positions(a, True), positions(b, False)
            best = None
            for pid in boards.keys() & alights.keys():
                if mapped_only and not self.mapped[pid]:
                    continue
                route = self.patterns[pid][0]
                for board, origin, walk in boards[pid]:
                    for alight, dest, egress in alights[pid]:
                        if alight <= board or dest == origin or first + walk + egress >= end:
                            continue
                        ready = first + walk + boarding_margin
                        departures, arrivals = self.connections(pid, board, alight)
                        j = bisect_left(departures, ready)
                        if j < len(arrivals):
                            arrive, trip = arrivals[j]
                            if available is not None and not available(route, trip, board, alight):
                                next_ride = min(((-arr, run) for dep, arr, run in self.rides_by_departure(pid, board, alight)
                                                 if dep >= ready and -arr+egress <= end and available(route, run, board, alight)),
                                                default=None)
                                if next_ride is None:
                                    continue
                                arrive, trip = next_ride
                            option = (arrive + egress, walk + egress, route, trip, board, alight, walk, egress)
                            if option[0] <= end and (best is None or option < best):
                                best = option
            if best:
                return (best[0], best[2:]) if arrival_time else best[2:]
        return match

    @lru_cache(maxsize=32768)
    def arrivals(self, pattern, board, alight):
        _, _, ids, times = self.patterns[pattern]
        dep, arr = times[:, 2 * board + 1], times[:, 2 * alight]
        valid = np.flatnonzero(arr > dep)
        order = valid[np.argsort(arr[valid], kind="stable")]
        best = []
        winner = None
        for i in order:
            option = (int(dep[i]), -int(arr[i]), int(ids[i]))
            winner = max(winner, option) if winner else option
            best.append(winner)
        return arr[order].tolist(), best

    @lru_cache(maxsize=8192)
    def rides_by_departure(self, pid, board, alight):
        _, _, ids, times = self.patterns[pid]
        return sorted(((int(dep), -int(arr), int(trip))
                       for dep, arr, trip in zip(times[:, 2*board+1], times[:, 2*alight], ids, strict=True)
                       if arr > dep), reverse=True)

    def ride_before(self, pid, board, alight, deadline, available=None, excluded=None, *, also_excluded=()):
        arrivals, choices = self.arrivals(pid, board, alight)
        j = bisect_right(arrivals, deadline)
        if not j:
            return None
        winner = choices[j-1]
        if available is None and excluded is None and not also_excluded:
            return winner
        route = self.patterns[pid][0]

        def usable(trip):
            return (route, trip) != excluded and (route, trip) not in also_excluded and (
                available is None or available(route, trip, board, alight))

        if usable(winner[2]):
            return winner
        return next((choice for choice in self.rides_by_departure(pid, board, alight)
                     if -choice[1] <= deadline and usable(choice[2])), None)

    def ride_after(self, pid, board, alight, ready, available=None, excluded=()):
        departures, arrivals = self.connections(pid, board, alight)
        i = bisect_left(departures, ready)
        if i == len(departures):
            return None
        route = self.patterns[pid][0]
        arrival, trip = arrivals[i]
        if (route, trip) not in excluded and (available is None or available(route, trip, board, alight)):
            return arrival, trip
        return min(((-arr, run) for dep, arr, run in self.rides_by_departure(pid, board, alight)
                    if dep >= ready and (route, run) not in excluded and
                    (available is None or available(route, run, board, alight))), default=None)

    def latest_departure(self, access, margin, available=None):
        """Find a mapped direct ride arriving by the fixed job start, including both walks."""
        positions = self.accessible_positions(access)

        def match(deadline, a, b):
            boards, alights = positions(a, True), positions(b, False)
            best = None
            for pid in boards.keys() & alights.keys():
                if not self.mapped[pid]:
                    continue
                route = self.patterns[pid][0]
                for board, origin, walk in boards[pid]:
                    for alight, destination, egress in alights[pid]:
                        if alight <= board or origin == destination:
                            continue
                        option = self.ride_before(pid, board, alight, deadline - egress, available)
                        if option:
                            board_at, neg_arrival, trip = option
                            start = (board_at - walk - margin) // 60
                            option = (-start, -neg_arrival + egress, walk + egress,
                                      route, trip, board, alight, walk, egress)
                            if best is None or option < best:
                                best = option
            if best is not None:
                start, arrival, _, *ride = best
                return -start, arrival, ride
        return match


def observed_boardings(table, routes):
    with table.open(encoding="utf-8-sig") as handle:
        weekday = {row["Lineno_renamed"]: round(float(row["AVG_Daily_Boardings_MF"]))
                   for row in csv.DictReader(handle) if row["CalendarYear"] == "2025" and row["AVG_Daily_Boardings_MF"] not in ("", "NULL")}
    return {r["id"]: weekday[r["name"]] for r in routes if r["type"] == 3 and r["name"] in weekday}


def assign(root, versions, observations, out, *, legs=None, downtown=None, transfer_margin=None, book_capacity=False):
    atlas_dir = root / "atlas" / versions["atlas"]
    day_dir = root / "cityday" / versions["day"]
    schedule = root / "transit" / versions["transit"]
    service = DirectService(schedule)
    bouts, excluded = resident_trips(atlas_dir, day_dir) if legs is None else (legs[0], Counter(legs[1]))
    places = read(day_dir / "places.json")
    identifiable = [row for row in bouts if places[row[-2]][:2] != places[row[-1]][:2]]
    excluded["samePlace"] = len(bouts) - len(identifiable)
    bouts = identifiable
    endpoints = {p for row in bouts for p in row[-2:]}
    print(f"{len(bouts):,} located transit bouts, {len(endpoints):,} distinct endpoints", flush=True)
    access = access_routes(places, endpoints, service.stations, root / "streets" / versions["streets"])
    match = service.matcher(access)
    by_da = defaultdict(list)
    by_route = Counter()
    examples = {}
    unmatched = []
    transfer_example = None

    def retain(row):
        da, _, start = row[:3]
        by_da[da].append(row)
        routes = (row[6], row[12][0]) if len(row) > 12 else (row[6],)
        for route in routes:
            by_route[route] += 1
            if route not in examples or abs(720 - start) < abs(720 - examples[route][2]):
                examples[route] = row

    for row in bouts:
        _, _, start, duration, a, b = row
        if a not in access or b not in access:
            excluded["access"] += 1
            continue
        result = match(start, duration, a, b)
        if result is None:
            if transfer_margin is None:
                excluded["schedule"] += 1
            else:
                unmatched.append(row)
        else:
            retain([*row, *result])
    capacity_report = None
    if book_capacity:
        table = observations.with_name(TABLE)
        profile = bus_capacity_profile(service.route_manifest, table, observations)
        spaces = BusSpaces(profile["limits"])
        planned = list(chain.from_iterable(by_da.values()))
        booked, denied, rerouted = book_direct(planned, spaces, service.matcher(access, available=spaces.available))
        capacity_report = dict(kept=len(booked)-rerouted, rerouted=rerouted, rejected=len(denied),
                               planned=len(planned), admitted=len(booked))
        by_da.clear()
        by_route.clear()
        examples.clear()
        for row in booked:
            retain(row)
        if transfer_margin is None:
            excluded["capacity"] = len(denied)
        else:
            unmatched.extend(denied)
    direct = sum(map(len, by_da.values()))
    if transfer_margin is not None:
        rules = read(schedule / "transfers.json")["pairs"]
        paths = walk_transfers(service, rules, root / "streets" / versions["streets"] / "network.json", transfer_margin)
        planner = OneTransfer(service, access, paths, transfer_margin)
        if book_capacity:
            connections, missing, full, recovered = book_connections(unmatched, planner, spaces, {tuple(r[:3]) for r in denied})
            excluded["schedule"], excluded["capacity"] = missing, full
        else:
            latest = lru_cache(maxsize=65536)(planner.latest)
            print(f"Checking {len(unmatched):,} unmatched trips and {sum(map(len, paths.values())):,} transfer pairs", flush=True)
            connections = []
            for row in sorted(unmatched, key=lambda row: (row[5], row[2] + row[3], row[4], row[0], row[1])):
                _, _, start, duration, a, b = row
                choice = latest((start + duration) * 60, a, b)
                if choice is None or choice[0] < start:
                    excluded["schedule"] += 1
                else:
                    connections.append([*row, *choice[2]])
        for ride in connections:
            retain(ride)
            if transfer_example is None or (ride[12][4] == 0, abs(ride[2] - 480), ride[:3]) < (
                    transfer_example[12][4] == 0, abs(transfer_example[2] - 480), transfer_example[:3]):
                transfer_example = ride
    if transfer_margin is not None or book_capacity:
        for rows in by_da.values():
            rows.sort(key=lambda row: (row[1], row[2]))
    for da, rows in by_da.items():
        write_json(out / (da + ".json"), rows)
    matched = sum(map(len, by_da.values()))
    total = len(bouts) + excluded["mixed"] + excluded["unlocated"] + excluded["samePlace"]
    if sum(excluded.values()) + matched != total:
        raise ValueError("Transit episodes were lost or counted more than once")
    report = dict(versions=versions, total=total, matched=matched, excluded=excluded, das=sorted(by_da),
                  walking=dict(maxMetres=ACCESS_METRES, metresPerMinute=60*WALK_METRES_PER_SECOND,
                               nearestNodeTie="lowest network ID"),
                  byRoute=by_route, examples=examples, date=service.route_manifest["date"],
                  observedWeekday=observed_boardings(observations, service.route_manifest["routes"]))
    if transfer_margin is not None:
        report["transfers"] = dict(direct=direct, added=matched-direct, candidates=len(unmatched),
                                   marginSeconds=transfer_margin, maxWalkMetres=MAX_TRANSFER_METRES,
                                   stopPairs=sum(map(len, paths.values())), example=transfer_example)
        if book_capacity:
            report["transfers"].update(bookedDirect=True, recoveredDirect=recovered, capacity=excluded["capacity"])
    station_table = observations.with_name("transit_translink_tspr2025_skytrainavgalightsbrdgs_yearstationdaytypehourly.csv")
    if downtown is None:
        downtown = resident_flows(day_dir, atlas_dir, places)
    if book_capacity:
        baseline = bus_load_evidence(schedule, service.route_manifest, planned, table, profile["limits"])
        after = bus_load_evidence(schedule, service.route_manifest, chain.from_iterable(by_da.values()), table, profile["limits"])
        if after["above"]:
            raise ValueError("The booked rider release exceeded modeled bus capacity")
        capacity_report.update(busBefore=baseline["above"], busAfter=after["above"])
        report.update(capacityComparison=capacity_report, bus=dict(before=baseline, after=after), capacitySources=profile["sources"])
        downtown["capacityChecked"] = True
    downtown["rail"] = station_counts(station_table, schedule, service.route_manifest, by_da)
    write_json(out / "downtown.json", downtown)
    write_json(out / "riders.json", report)
    print(f"{matched:,} scheduled trips ({direct:,} direct) among {total:,} transit bouts; {dict(excluded)}", flush=True)


def publish_walks(root, riders):
    def index(out):
        subprocess.run(["node", "scripts/vancouver_rider_walks.mjs", str(root), riders, str(out)], check=True)
    version = package(root, "rider-walks", index)
    parent = root / "rider-walks"
    with tempfile.TemporaryDirectory(dir=parent) as tmp:
        staged = Path(tmp) / "pointer.json"
        write_json(staged, {"version": version})
        staged.replace(parent / (riders + ".json"))
    return version


def publish_riders(archive, root, versions):
    observations = archive / "data/raw/probes/transit_translink_tspr2025_bus_yearline.csv"
    riders = package(root, "transit-riders", lambda out: assign(root, versions, observations, out))
    publish_walks(root, riders)
    pointer = root / "transit-riders" / "{atlas}_{day}_{streets}.json".format(**versions)
    with tempfile.TemporaryDirectory(dir=pointer.parent) as tmp:
        staged = Path(tmp) / "pointer.json"
        write_json(staged, dict(transit=versions["transit"], riders=riders))
        staged.replace(pointer)
    return riders


def publish(archive, root, service_date, day_id=None):
    day = read(root / "cityday/current.json")
    if day_id:
        day["version"] = day_id
    atlas = read(root / "atlas" / day["atlas"] / "atlas.json")
    areas = {name: group["geometry"] for name, group in atlas["areas"].items()}
    feed = archive / "data/raw/probes/transit_translink_gtfs_static.zip"
    transit = package(root, "transit", lambda out: build_timetable(feed, areas, service_date, out, passenger_rules=True))
    versions = dict(day=day["version"], atlas=day["atlas"], streets=read(root / "streets/current.json")["version"], transit=transit)
    return publish_riders(archive, root, versions)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--date", type=date.fromisoformat, default=date(2026, 9, 15))
    parser.add_argument("--day", help="Use a published weekday under the current atlas")
    parser.add_argument("--index-walks-only", action="store_true", help="Build route walking intervals for the current rider release")
    args = parser.parse_args()
    if args.index_walks_only:
        day = read(args.data / "cityday/current.json")
        streets = read(args.data / "streets/current.json")["version"]
        pointer = args.data / "transit-riders" / f"{day['atlas']}_{args.day or day['version']}_{streets}.json"
        print(publish_walks(args.data, read(pointer)["riders"]))
    else:
        publish(args.archive, args.data, args.date, args.day)
