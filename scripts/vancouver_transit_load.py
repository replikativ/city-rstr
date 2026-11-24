"""Compare modelled bus loads with the 2025 weekday peak-load table."""
from collections import Counter, defaultdict
import csv
import hashlib
import math
from itertools import chain
from statistics import median

from scripts.artifacts import read

TABLE = "transit_translink_tspr2025_bus_peakload_yearlinedaytypeseasontimerangedirection.csv"
ANNUAL_TABLE = "transit_translink_tspr2025_bus_yearline.csv"
SOURCE = "https://www.translink.ca/tspr"


def read_capacity(table, select):
    capacity = defaultdict(list)
    with table.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if not select(row):
                continue
            load, factor = row["Average_Peak_Passenger_Load"], row["Average_Peak_Load_Factor"]
            if load in ("", "NULL") or factor in ("", "NULL"):
                continue
            load, factor = float(load), float(factor)
            if not (math.isfinite(load) and math.isfinite(factor) and load > 0 and factor > 0):
                continue
            for name in row["Lineno_renamed"].split("/"):
                capacity[name.strip().lstrip("0")].append(100 * load / factor)
    return {name: round(median(values), 1) for name, values in capacity.items()}


def reference_capacities(table):
    """Invert the published load factors to obtain a route-level capacity proxy."""
    return read_capacity(table, lambda row: (row["SeasonYear"], row["DayType"], row["Season"]) == ("2025", "MF", "Fall"))


def source_digest(table):
    with table.open("rb") as stream:
        return dict(dataset=table.name, digest=hashlib.file_digest(stream, "sha256").hexdigest())


def bus_capacity_profile(manifest, table, annual):
    fall = reference_capacities(table)
    if not fall:
        raise ValueError("The fall peak-load table has no reference capacities")
    full_year = read_capacity(annual, lambda row: row["CalendarYear"] == "2025") if annual else {}
    fallback = math.floor(min(fall.values()))
    sources = [source_digest(path) for path in (table, annual) if path]
    routes, basis = {}, {}
    for route in manifest["routes"]:
        if route.get("type") != 3:
            continue
        label, route_id = route["name"], route["id"]
        routes[route_id] = math.floor(fall.get(label, full_year.get(label, fallback)))
        basis[route_id] = "fall" if label in fall else "annual" if label in full_year else "fallback"
    return dict(limits=routes, basis=basis, fallback=fallback, sources=sources)


def observed_spare_capacity(manifest, table, limits):
    """Reserve the highest observed average fall weekday peak on each bus route."""
    background = {}
    with table.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if (row["SeasonYear"], row["Season"], row["DayType"]) != ("2025", "Fall", "MF"):
                continue
            n = row["Average_Peak_Passenger_Load"]
            if n in ("", "NULL"):
                continue
            n = float(n)
            if not math.isfinite(n) or n < 0:
                continue
            for name in row["Lineno_renamed"].split("/"):
                label = name.strip().lstrip("0")
                background[label] = max(background.get(label, 0), math.ceil(n))
    reserved = {r["id"]: background.get(r["name"].lstrip("0"))
                for r in manifest["routes"] if r["id"] in limits}
    spare = {route: max(0, limits[route]-n) if n is not None else 0 for route, n in reserved.items()}
    return dict(observedReserve=reserved, spare=spare)


def ride_legs(ride):
    """The reservation fields of each leg, following the published itinerary schema."""
    yield ride[:4]
    next_ride = ride[6] if len(ride) > 6 else None
    while next_ride:
        yield next_ride[:4]
        next_ride = next_ride[7] if len(next_ride) > 7 else None


class BusSpaces:
    """Reserve capacity on every segment between boarding and alighting."""

    def __init__(self, limits, closed=()):
        self.limits = limits
        self.closed = frozenset(closed)
        self.loads = defaultdict(Counter)
        self.full = defaultdict(int)
        if any(n <= 0 for n in limits.values()):
            raise ValueError("Bus capacities must be positive")

    def available(self, route, run, board, alight):
        if route in self.closed:
            return False
        mask = ((1 << (alight-board)) - 1) << board
        return not (self.full.get((route, run), 0) & mask)

    def fits(self, itinerary):
        return all(self.available(*leg) for leg in ride_legs(itinerary))

    def reserve(self, itinerary):
        legs = list(ride_legs(itinerary))
        if len({tuple(leg[:2]) for leg in legs}) != len(legs) or not self.fits(itinerary):
            raise ValueError("Trip segments would exceed the seat reservation")
        self.preload(legs)

    def preload(self, legs):
        """Carry an earlier timetable as background, including already full segments."""
        for route, run, board, alight in legs:
            if route not in self.limits:
                continue
            key = route, run
            load, limit = self.loads[key], self.limits[route]
            for segment in range(board, alight):
                load[segment] += 1
                if load[segment] >= limit:
                    self.full[key] |= 1 << segment


def rider_order(da, person, start, duration):
    draw = hashlib.blake2b(f"{da}/{person}".encode(), digest_size=8, person=b"city-20261121")
    return start + duration, draw.digest(), da, person


def book_direct(planned, spaces, alternative):
    """Keep direct riders in earliest-closing-window order, with deterministic ties."""
    booked, denied, rerouted = [], [], 0
    for row in sorted(planned, key=lambda row: rider_order(*row[:4])):
        ride = row[6:]
        if not spaces.fits(ride):
            ride = alternative(*row[2:6])
            if ride is None:
                denied.append(row[:6])
                continue
            row = [*row[:6], *ride]
            rerouted += 1
        spaces.reserve(ride)
        booked.append(row)
    return booked, denied, rerouted


def book_connections(candidates, planner, spaces, denied):
    """Try feasible one-transfer windows, then reserve every leg together."""
    windows = {(start, start + duration, a, b) for _, _, start, duration, a, b in candidates}
    ordered = sorted(windows, key=lambda window: (window[3], window[1], window[2], window[0]))
    print(f"Checking {len(ordered):,} distinct rider windows", flush=True)
    routes = {}
    for i, (start, end, a, b) in enumerate(ordered, 1):
        option = planner.latest(end * 60, a, b, earliest_minute=start)
        if option:
            routes[start, end, a, b] = option[2]
        if i % 5000 == 0:
            print(f"Checked {i:,} of {len(ordered):,} windows", flush=True)

    booked, missing, full, recovered = [], 0, 0, 0
    for row in sorted(candidates, key=lambda row: rider_order(*row[:4])):
        _, _, start, duration, a, b = row
        option = routes.get((start, start + duration, a, b))
        was_denied = tuple(row[:3]) in denied
        if option is None:
            full += was_denied
            missing += not was_denied
            continue
        if not spaces.fits(option):
            alternate = planner.latest((start + duration) * 60, a, b, spaces.available, earliest_minute=start)
            if alternate is None:
                full += 1
                continue
            option = alternate[2]
        spaces.reserve(option)
        booked.append([*row, *option])
        recovered += was_denied
    if len(booked) + missing + full != len(candidates):
        raise ValueError("The eligible transfer outcomes do not reconcile")
    return booked, missing, full, recovered


def bus_load_evidence(schedule, manifest, rides, table, limits=None, *, reserved=()):
    """Count riders on each bus segment, including second boardings."""
    buses = {r["id"]: r["name"] for r in manifest["routes"] if r.get("type") == 3}
    if limits is None:
        reference = reference_capacities(table)
        limits = {route: reference[name] for route, name in buses.items() if name in reference}
    segments = defaultdict(Counter)
    legs = (leg for row in rides for leg in ride_legs(row[6:]))
    for route, trip, board, alight in chain(reserved, legs):
        if route in buses:
            segments[route, trip][board] += 1
            segments[route, trip][alight] -= 1

    loads = []
    for (route, trip), changes in sorted(segments.items()):
        if route not in limits:
            continue
        on_board = peak = at = 0
        for stop, difference in sorted(changes.items()):
            on_board += difference
            if on_board > peak:
                at, peak = stop, on_board
        if on_board:
            raise ValueError("Bus load did not return to zero after the final alighting")
        loads.append((route, trip, at, peak, limits[route]))

    result = dict(busTrips=len(segments), compared=len(loads),
                  above=sum(peak > size for _, _, _, peak, size in loads), source=SOURCE, **source_digest(table))
    result["atLimit"] = sum(peak >= size for _, _, _, peak, size in loads)
    if loads:
        route, trip, at, peak, size = max(loads, key=lambda row: row[3])
        asset = read(schedule / (route + ".json"))
        pattern, start, times, _ = asset["rides"][trip]
        stop = asset["patterns"][pattern]["stops"][at]
        result["highest"] = dict(route=buses[route], stop=asset["stations"][stop][2],
                                 minute=(start+times[2*at+1])//60, riders=peak, capacityProxy=size)
    return result
