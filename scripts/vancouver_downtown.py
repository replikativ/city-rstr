"""Hourly modelled Downtown trips and an independent six-station SkyTrain benchmark."""
from collections import defaultdict
import csv
import json
import math

import numpy as np

from scripts.vancouver_transit_load import ride_legs

STATIONS = {"Burrard Station", "Granville Station", "Stadium-Chinatown Station", "Waterfront Station",
            "Vancouver City Centre Station", "Yaletown-Roundhouse Station"}
MODES = ["Car driver", "Car passenger", "Ride-hail", "Taxi", "Bicycle", "Public transit", "Walking", "Other"]
MODE_INDEX = {m: i for i, m in enumerate(["car-driver", "car-passenger", "ridehail", "taxi", "bike", "transit", "walk"])}


def hour(label):
    # The shared AM/PM suffix appears only at the end except across noon and midnight.
    start, end = label.split(" to ")
    meridiem = start.split()[-1] if " " in start else end.split()[-1]
    return int(start.split(":")[0]) % 12 + 12 * (meridiem == "PM")


def station_counts(table, transit, manifest, by_da, *, by_origin=False):
    survey = np.zeros((24, 2), dtype=int)
    seen = set()
    with table.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = row["StationName"]
            if row["CalendarYear"] != "2025" or row["DayType"] != "MF" or name not in STATIONS:
                continue
            h = hour(row["Hour"])
            if (name, h) in seen:
                raise ValueError(f"Duplicate station record for {name} at {h}")
            seen.add((name, h))
            survey[h] += [int(row["Average_Daily_Station_Alightings"]), int(row["Average_Daily_Station_Boardings"])]
    if len(seen) != 24 * len(STATIONS):
        raise ValueError("Missing downtown SkyTrain observations")
    rail = {r["id"]: json.loads((transit / (r["id"] + ".json")).read_bytes())
            for r in manifest["routes"] if r["type"] == 1}
    fare_zone = {r["id"]: "Canada Line" if "canada" in r["name"].lower() else "Expo and Millennium"
                 for r in manifest["routes"] if r["type"] == 1}
    modeled = np.zeros_like(survey)
    origins = {}
    for origin, bouts in by_da.items():
        matched = np.zeros_like(survey) if by_origin else modeled
        for row in bouts:
            gates = []
            for route, trip, board, alight in ride_legs(row[6:]):
                if route not in rail:
                    gates.extend([None, None])
                    continue
                route_data = rail[route]
                pattern, start, times, _ = route_data["rides"][trip]
                stops = route_data["patterns"][pattern]["stops"]
                for direction, pos in ((1, board), (0, alight)):
                    name = route_data["stations"][stops[pos]][2].split(" @ ")[0]
                    gates.append((name, fare_zone[route], start + times[2 * pos + direction], direction))
            # Cancel intermediate crossings for consecutive vehicles in the same paid zone.
            for i in range(1, len(gates)-1, 2):
                if gates[i] and gates[i+1] and gates[i][:2] == gates[i+1][:2]:
                    gates[i:i+2] = [None, None]
            for name, _, seconds, direction in (gate for gate in gates if gate):
                if name in STATIONS:
                    matched[(seconds // 3600) % 24, direction] += 1
        if by_origin:
            modeled += matched
            origins[origin] = matched.tolist()
    result = {"observed": survey.tolist(), "matched": modeled.tolist(), "stations": sorted(STATIONS)}
    if by_origin:
        result["byOrigin"] = origins
    return result


def shared_minute_offset(agent):
    """Observe the shared regional diary phase at a whole minute."""
    return math.ceil(5 * (((agent + 1) * 7919 % 10007) + 0.5) / 10007 - 2.5)


def resident_flows(day_dir, atlas_dir, places, *, workplace_ends=False, shared_clock=False):
    day = json.loads((day_dir / "day.json").read_bytes())
    atlas = json.loads((atlas_dir / "atlas.json").read_bytes())
    areas = day["areas"]
    zone = np.array([p[2] for p in places])
    core = areas.index("Downtown")
    home_area = {d: areas.index(name) for name, area in atlas["areas"].items() for d in area["das"]}
    counts = np.zeros((24, len(areas), 2, len(MODES)), dtype=int)
    work = np.zeros((24, 2), dtype=int) if workplace_ends else None
    morning = defaultdict(lambda: np.zeros((2, len(areas)), dtype=int))
    ordinal = 0
    for da in day["das"]:
        roster = json.loads((atlas_dir / (da + ".json")).read_bytes())["people"]
        plans = json.loads((day_dir / (da + ".json")).read_bytes())["plans"]
        groups = defaultdict(list)
        for index, (person, plan) in enumerate(zip(roster, plans, strict=True), ordinal):
            offset = shared_minute_offset(index) if shared_clock else 0
            groups[person[7], offset].append(plan)
        ordinal += len(roster)
        for (template, offset), rows in groups.items():
            anchors = np.asarray(rows)
            for start, duration, mode, i, j in day["templates"][template]["parts"]:
                if mode == "stop" or min(i, j) < 0:
                    continue
                a, b = anchors[:, i], anchors[:, j]
                valid = (a >= 0) & (b >= 0) & (zone[a] >= 0) & (zone[b] >= 0)
                origin, dest = zone[a] == core, zone[b] == core
                inbound = np.count_nonzero(valid & ~origin & dest)
                outbound = np.count_nonzero(valid & origin & ~dest)
                m = MODE_INDEX.get(mode, len(MODES) - 1)
                arrive_hour = (start + duration + offset) // 60 % 24
                leave_hour = (start + offset) // 60 % 24
                counts[arrive_hour, home_area[da], 0, m] += inbound
                counts[leave_hour, home_area[da], 1, m] += outbound
                if workplace_ends:
                    slots = day["templates"][template]["slots"]
                    if outbound and 7 <= leave_hour < 9:
                        destinations = zone[b[valid & origin & ~dest]]
                        morning[slots[j]][int(home_area[da] == core)] += np.bincount(destinations, minlength=len(areas))
                    if slots[j] == "job":
                        work[arrive_hour, 0] += inbound
                    if slots[i] == "job":
                        work[leave_hour, 1] += outbound
    result = {"areas": areas, "modes": MODES, "counts": counts.tolist()}
    if workplace_ends:
        result["morningDepartures"] = {purpose: counts.tolist() for purpose, counts in sorted(morning.items())}
        result["workplaceEnds"] = work.tolist()
    return result
