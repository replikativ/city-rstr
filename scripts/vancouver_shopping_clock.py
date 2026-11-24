"""Spread feasible bicycle shopping tours on the combined weekday."""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import hashlib
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_discretionary_outings import verify_intervals
from scripts.vancouver_region import package, read
from scripts.vancouver_shopping_outings import protected_activities
from scripts.vancouver_transit_commutes import BOARDING_MARGIN_SECONDS, pointer
from scripts.vancouver_trip_demand import destination, linked_trips

RADIUS = 7
MIN_ACTIVITY = 5
SEED = 20261122


def tours_in_template(diary, template):
    episodes = {row[0]: row for row in diary["episodes"]}
    parts, slots = template["parts"], template["slots"]
    for left, there, visit, back, right in zip(parts, parts[1:], parts[2:], parts[3:], parts[4:]):
        start, inward, mode, origin, shop = there
        leave, outward, return_mode, _, home = back
        arrival, dwell, stop_mode, _, _ = visit
        end = leave + outward
        prior = next((row for row in diary["episodes"] if row[0] + row[1] == start), None)
        next_activity = episodes.get(end)
        if (
            mode != "bike" or return_mode != "bike" or stop_mode != "stop"
            or left[2] != "stop" or right[2] != "stop" or slots[home] != "home" or slots[origin] == "job"
            or episodes.get(arrival) != [arrival, dwell, "shopping", "store"]
            or not prior or prior[2] not in {"sports", "leisure-out"}
            or not next_activity or next_activity[2] not in {"housework", "media", "personal-care"}
            or any(row[3] != "bike" for row in diary["episodes"] if start <= row[0] < arrival or leave <= row[0] < end)
        ):
            continue
        lo = max(-RADIUS, MIN_ACTIVITY - prior[1], -(start % 60), -(leave % 60))
        hi = min(RADIUS, next_activity[1] - MIN_ACTIVITY, 59 - start % 60, 59 - leave % 60)
        if lo < 0 or hi > 0:
            yield start, inward, dwell, outward, origin, shop, home, lo, hi


def transit_templates(atlas, day):
    return {i for i, (diary, template) in enumerate(zip(atlas["templates"], day["templates"], strict=True))
            if any(start == 990 and display == "transit" and before and before[2] == "paid-work"
                   and destination(before, after) == "Shopping"
                   for start, _, _, display, _, _, before, after in linked_trips(diary, template))}


def gather(root, joint, day, atlas, atlas_dir, day_dir, periods):
    variants = [list(tours_in_template(d, t)) for d, t in zip(atlas["templates"], day["templates"], strict=True)]
    transit = transit_templates(atlas, day)
    rider_dir = root / "transit-riders" / joint["riders"]
    schedule = root / "transit" / joint["transit"]
    rider_areas = set(read(rider_dir / "riders.json")["das"])
    services = {}
    candidates, transit_counts = [], Counter()
    for d, da in enumerate(day["das"]):
        file = da + ".json"
        people = read(atlas_dir / file)["people"][:atlas["das"][da]["private"]]
        plans = read(day_dir / file)["plans"]
        boarded = {r[1]: r for r in read(rider_dir / file) if r[2] == 990} if da in rider_areas else {}
        for i, p in enumerate(people):
            age, tpl = p[0], p[-1]
            if not 3 <= age <= 13:
                continue
            weight = 2 if age == 3 else 5
            if tpl in transit:
                transit_counts["recorded"] += weight
                if r := boarded.get(i):
                    transit_counts["booked"] += weight
                    route, run, board, _, access = r[6:11]
                    if route not in services:
                        services[route] = read(schedule / (route + ".json"))["rides"]
                    ride = services[route][run]
                    board_at = ride[1] + ride[2][2 * board + 1]
                    if board_at - 990 * 60 - access >= BOARDING_MARGIN_SECONDS + 60:
                        transit_counts["slack"] += weight
            for start, there, dwell, back, a, b, c, lo, hi in variants[tpl]:
                period = next((row for row in periods if row["start"] <= start < row["end"]), None)
                if not period:
                    continue
                origin, shop, home = (plans[i][slot] for slot in (a, b, c))
                candidates.append([d, i, start, there, dwell, back, origin, shop, home, weight, lo, hi, period["key"]])
    return candidates, {key: n / 5 for key, n in transit_counts.items()}


def route_check(records, root, cycling, places_file, places, scratch):
    requests, indices = [], []
    for index, (_, _, _, there, _, back, a, b, c, *_) in enumerate(records):
        if min(a, b, c) < 0 or any(places[i][2] < 0 for i in (a, b, c)):
            continue
        if places[a][:2] == places[b][:2] or places[b][:2] == places[c][:2]:
            continue
        requests.append([a, b, c, there, back])
        indices.append(index)
    request, output = scratch / "routes.json", scratch / "fit.json"
    write_json(request, requests)
    subprocess.run(["node", "scripts/vancouver_shopping_clock_routes.mjs", root / "cycling" / cycling / "network.json",
                    places_file, request, output], check=True)
    fit = read(output)
    return fit["speed"], {index for index, ok in zip(indices, fit["result"], strict=True) if ok}


def spread(records, feasible, das, protected):
    assigned, counts, placed = [], defaultdict(Counter), Counter()
    order = sorted(feasible, key=lambda i: hashlib.blake2b(
        f"{SEED}/{das[records[i][0]]}/{records[i][1]}/{records[i][2]}".encode(), digest_size=8).digest())
    for i, row in enumerate(records):
        key, weight = row[-1], row[9]
        counts[key]["candidate"] += weight
        if i in feasible:
            counts[key]["connected"] += weight
    for i in order:
        d, person, start, there, dwell, back, *_, weight, lo, hi, key = records[i]
        end = start + there + dwell + back
        available = [delta for delta in range(lo, hi + 1) if not any(
            min(start, start + delta) < b and a < max(end, end + delta) for a, b in protected[das[d], person])]
        if not available:
            continue
        delta = min(available, key=lambda n: (placed[key, start, n], abs(n), n))
        placed[key, start, delta] += weight
        if delta:
            counts[key]["changed"] += weight
            assigned.append([*records[i][:10], delta, key])
            protected[das[d], person].append((min(start, start + delta), max(end, end + delta)))
    return sorted(assigned), {key: {name: n / 5 for name, n in row.items()} for key, row in counts.items()}


def boundaries(start, there, dwell, back):
    return [start, start + there, start + there + dwell, start + there + dwell + back]


def occupancy_delta(rows, places, baseline, areas, scratch, backend):
    cols = len(areas) + 2
    edits, schedules = np.zeros((1441, cols), dtype=np.int32), []
    for _, _, start, there, dwell, back, origin, shop, home, _, shift, _ in rows:
        old, new = [boundaries(start + n, there, dwell, back) for n in (0, shift)]
        areas_at = [places[origin][2], cols - 2, places[shop][2], cols - 2, places[home][2]]
        fragments = []
        times = sorted(set(old + new))
        for minute, stop in zip(times, times[1:]):
            previous, current = (areas_at[bisect_right(edge, minute)] for edge in (old, new))
            if previous == current:
                continue
            lo, hi = minute - 240, stop - 240
            fragments.append((lo * cols + previous, hi * cols + previous, current - previous))
            edits[lo:hi, previous] -= 1
            edits[lo:hi, current] += 1
        if fragments:
            schedules.append(tuple(fragments))
    return verify_intervals(schedules, edits, baseline, scratch, backend)


def publish(root, joint_id, backend):
    joint_dir = root / "joint-weekday" / joint_id
    joint = read(joint_dir / "report.json")
    versions = joint["versions"]
    atlas_dir, day_dir = root / "atlas" / versions["atlas"], root / "cityday" / versions["day"]
    atlas, day = read(atlas_dir / "atlas.json"), read(day_dir / "day.json")
    places_file = day_dir / "places.json"
    places = read(places_file)
    timing_root = root / "trip-timing"
    timing_id = read(timing_root / f"{joint_id}.json")["version"]
    timing = read(timing_root / timing_id / "report.json")
    if timing["versions"] != versions or timing["joint"] != joint_id or timing["outings"] != joint["outings"]:
        raise ValueError("The shopping timing comparison was built for a different weekday")
    period_rows = timing["periods"]
    protected, companions = protected_activities(root, versions, day)
    for d, i, start, length, *_ in read(joint_dir / "short-walks.json")["walks"]:
        protected[day["das"][d], i].append((start, start + length))
    for d, i, _, _, _, _, start, there, dwell, back, *_ in read(
            root / "discretionary-outings" / joint["outings"] / "tours.json"):
        protected[day["das"][d], i].append((start, start + there + dwell + back))
    candidates, transit = gather(root, joint, day, atlas, atlas_dir, day_dir, period_rows)
    cycling = read(root / "cycling" / (versions["streets"] + ".json"))["version"]
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        speed, feasible = route_check(candidates, root, cycling, places_file, places, scratch)
        records, counts = spread(candidates, feasible, day["das"], protected)
        if not records:
            raise ValueError("No bicycle shopping tours can be moved within the published schedules")
        timing_delta = occupancy_delta(records, places, read(joint_dir / "occupancy.json"), day["areas"], scratch, backend)
    peaks = {}
    for period in period_rows:
        first, key = period["start"], period["key"]
        before = [round(n * 5) for n in period["shoppingDepartures"]]
        after = before.copy()
        for _, _, start, _, _, _, _, _, _, weight, shift, k in records:
            if k == key:
                after[start - first] -= weight
                after[start + shift - first] += weight
        if sum(before) != sum(after) or min(after) < 0:
            raise ValueError("A bicycle shopping tour changed its two-hour trip count")
        peak = lambda row: [first + row.index(max(row)), max(row) / 5]
        peaks[key] = dict(before=peak(before), after=peak(after), atOriginal=after[before.index(max(before))] / 5,
                          departures=[n / 5 for n in after])
    example = min((r for r in records if r[2] == 880), key=lambda r: (-abs(r[-2]), r[:2]), default=records[0])
    report = dict(schema=1, joint=joint_id, versions=versions, cycling=cycling, tripTiming=timing_id, radius=RADIUS,
                  speed=speed, counts=counts, tripPeaks=peaks, transitAt1630=transit, population=day["population"],
                  protections=companions, outings=joint["outings"], example=example, **timing_delta)

    def build(folder):
        write_json(folder / "report.json", report)
        write_json(folder / "tours.json", records)

    version = package(root, "shopping-clock", build)
    pointer(root / "shopping-clock" / f"{joint_id}.json", {"version": version})
    print(version, counts, {key: (p["before"], p["after"], p["atOriginal"]) for key, p in peaks.items()}, transit)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("joint")
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--backend", default="jvm")
    args = parser.parse_args()
    publish(args.root, args.joint, args.backend)
