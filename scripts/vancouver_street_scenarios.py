"""Index the published scenario trips for discovery in Vancouver's street view."""
import argparse
from functools import lru_cache
import hashlib
from pathlib import Path
import re

from scripts.vancouver_atlas import write_json
from scripts.vancouver_region import read
from scripts.vancouver_transit_commutes import pointer

ACCESS = 800
RECREATION = "recreation-loops"
SCHOOLS = "school-escorts"
ATTENDANCE = "weekday-attendance"
OUTINGS = "discretionary-outings"
WORK_TRANSIT = "work-transit"
PERSONAL_TRANSIT = "personal-transit"
CITY_TRANSIT = "transit-riders"
VEHICLE_ACCESS = "vehicle-access"
PASSENGERS = (WORK_TRANSIT, PERSONAL_TRANSIT, CITY_TRANSIT)
SHORT_WALKS = "short-walks"
VERSION = re.compile(r"[a-f0-9]{20}")


def bounds(points, pad=0):
    x, y = zip(*(p[:2] for p in points), strict=True)
    return [min(x) - pad, min(y) - pad, max(x) + pad, max(y) + pad]


def candidate(d, i, start, end, extent, enabled):
    if not 240 <= start < end <= 1680 or extent[0] > extent[2] or extent[1] > extent[3]:
        raise ValueError("Invalid time or route bounds for a street actor")
    return [d, i, start, end, *extent, int(enabled)]


@lru_cache(maxsize=256)
def scheduled_rides(file):
    return read(file)["rides"]


def alight(timetable, ride):
    route, run, _, stop, *_ = ride
    _, start, offsets, *_ = scheduled_rides(timetable / (route + ".json"))[run]
    return start + offsets[2 * stop]


def transit_walks(timetable, d, i, start, end, a, b, trip):
    access, egress = trip[4:6]
    arriving = trip[6] if len(trip) > 6 else trip
    stop_seconds = alight(timetable, arriving)
    if access:
        yield candidate(d, i, start, min(end, start + access / 60), bounds([a], ACCESS), True)
    if len(trip) > 6:
        transfer = trip[6]
        moment = alight(timetable, trip)
        if transfer[4]:
            yield candidate(d, i, moment / 60, min(end, (moment + transfer[4]) / 60), bounds(transfer[6]), True)
    if egress and stop_seconds / 60 < end:
        yield candidate(d, i, stop_seconds / 60, min(end, (stop_seconds + egress) / 60), bounds([b], ACCESS), True)


def movements(kind, row, places, timetable):
    if kind == RECREATION:
        d, i, _, start, duration, added, _, path, *_ = row
        yield candidate(d, i, start, start + duration, bounds(path), added)
    elif kind == SCHOOLS:
        d, adult, _, _, _, _, _, start, there, dwell, back, go, come, *_ = row
        arrive = start + there
        leave = arrive + dwell
        yield candidate(d, adult, start, arrive, bounds(go[0]), True)
        yield candidate(d, adult, leave, leave + back, bounds(come[0]), True)
    elif kind in PASSENGERS:
        d, i, start, duration, a, b, *trip = row
        yield from transit_walks(timetable, d, i, start, start + duration, places[a], places[b], trip)
    elif kind == VEHICLE_ACCESS:
        d, i, start, duration, a, b, mode, route, *_ = row
        if mode == "transit":
            yield from transit_walks(timetable, d, i, start, start + duration, places[a], places[b], route)
        else:
            yield candidate(d, i, start, start+duration, bounds(route), True)
    elif kind == OUTINGS:
        d, i, home, site, _, mode, start, there, dwell, back, _, rides = row
        if mode == "transit":
            leave = start + there + dwell
            yield from transit_walks(timetable, d, i, start, start + there, places[home], places[site], rides[0][:6])
            yield from transit_walks(timetable, d, i, leave, leave + back, places[site], places[home], rides[1][:6])
    else:
        d, i, home, site, mode, start, work, leave, end, go, back, *_, arrived = row
        if mode == "transit":
            departure, back = back
            yield from transit_walks(timetable, d, i, start, arrived, places[home], places[site], go)
            yield from transit_walks(timetable, d, i, departure, end, places[site], places[home], back)
        else:
            yield candidate(d, i, start, work, bounds(go[0]), True)
            yield candidate(d, i, leave, end, bounds(back[0]), True)


def referenced_rows(root, kind, release):
    folder = root / kind / release
    report = read(folder / ("riders.json" if kind == CITY_TRANSIT else "report.json"))
    versions = {key: report["versions"][key] for key in ("atlas", "day", "streets")}
    day_root = root / "cityday" / versions["day"]
    das = read(day_root / "day.json")["das"]
    places = read(day_root / "places.json") if kind in (ATTENDANCE, OUTINGS, VEHICLE_ACCESS, *PASSENGERS) else None
    service = report["transit"]["release"] if kind == OUTINGS else report["versions"].get("transit")
    timetable = root / "transit" / service if service else None
    indexes = {da: d for d, da in enumerate(das)}
    legs = []
    if kind == OUTINGS:
        for source in read(folder / "tours.json"):
            if source[5] == "transit":
                legs.extend(movements(kind, source, places, timetable))
    else:
        areas = (report["das"] if kind == CITY_TRANSIT else
                 report["coverage"]["areas"] if kind in PASSENGERS else report["areas"])
        for da in areas:
            for source in read(folder / (da + ".json")):
                if kind in PASSENGERS:
                    if source[0] != da:
                        raise ValueError("Scheduled transit has a different resident identity")
                    source = [indexes[da], *source[1:]]
                if source[0] != indexes[da]:
                    raise ValueError("Scenario actors have a different resident identity")
                legs.extend(movements(kind, source, places, timetable))
    unique = {tuple(row[:4]) for row in legs}
    if len(unique) != len(legs):
        raise ValueError("Duplicate movement interval in the scenario street index")
    return versions, sorted(legs, key=lambda leg: (leg[2], leg[0], leg[1]))


def inferred_rows(root, report):
    versions = {key: report[key] for key in ("atlas", "day", "streets")}
    day_root = root / "cityday" / report["day"]
    day = read(day_root / "day.json")
    legs = []
    plans = {}
    for d, i, start, duration, a, b in report["walks"]:
        if d not in plans:
            plans[d] = read(day_root / (day["das"][d] + ".json"))["plans"]
        plan = plans[d][i]
        if min(plan[a], plan[b]) < 0:
            raise ValueError("An inferred walk has unlocated endpoints")
        legs.append([d, i, start, duration, plan[a], plan[b]])
    return versions, legs


def publish_index(root, kind, version):
    output = root / "street-scenarios"
    output.mkdir(exist_ok=True)
    versions, records = referenced_rows(root, kind, version)
    pointer(output / (kind + "_" + version + ".json"),
            dict(schema=1, kind=kind, release=version, versions=versions, records=records))
    print(kind, version, len(records), flush=True)


def publish(root):
    output = root / "street-scenarios"
    output.mkdir(exist_ok=True)
    for kind in (RECREATION, SCHOOLS, ATTENDANCE, OUTINGS, WORK_TRANSIT, PERSONAL_TRANSIT):
        source = root / kind
        if not source.is_dir():
            continue
        # Only index releases reachable from a published replay, including
        # explicit version links that bypass the current day pointer.
        for folder in sorted(source.iterdir()):
            if not folder.is_dir() or not VERSION.fullmatch(folder.name):
                continue
            if kind == OUTINGS and not read(folder / "report.json").get("transit"):
                continue
            publish_index(root, kind, folder.name)
    for source in sorted((root / SHORT_WALKS).glob("*.json")):
        report = read(source)
        versions, records = inferred_rows(root, report)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        pointer(output / (SHORT_WALKS + "_" + source.stem + ".json"),
                dict(schema=1, kind=SHORT_WALKS, release=source.stem, versions=versions, sourceDigest=digest, records=records))
        print(SHORT_WALKS, source.stem, len(records), flush=True)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    args = cli.parse_args()
    for root in (args.root, args.root / "region"):
        publish(root)
