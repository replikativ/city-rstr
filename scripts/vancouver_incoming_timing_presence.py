"""Replay extra commuter travel intervals through Raster's occupancy phase."""
import argparse
from collections import Counter
from pathlib import Path

import numpy as np

from scripts.artifacts import pointer, read
from scripts.vancouver_commuter_presence import daily_segments, raster_presence


def extension(row, worker, home, maximum):
    """Return the added interval and travel direction, keeping the whole work shift fixed."""
    _, _, start, duration, a, b = row[:6]
    _, workplace, _, _, _, leave, elapsed, span, attends, _ = worker
    work_start, work_end = leave+elapsed, leave+elapsed+span
    if not attends:
        raise ValueError("An incoming trip was assigned to a worker who stays home")
    if (a, b) == (home, workplace) and start+duration == work_start:
        first, last, direction = start, leave, 0
    elif (a, b) == (workplace, home) and start == work_end:
        first, last, direction = work_end+elapsed, start+duration, 2
    else:
        raise ValueError("An incoming trip changed a home, workplace or paid shift")
    if not 0 <= last-first <= maximum:
        raise ValueError("An incoming trip went beyond the timing comparison allowance")
    return first, last, direction


def publish(root, release, backend):
    folder = root / "incoming-transit" / release
    report = read(folder / "report.json")
    timing = report["timing"]
    original = root / "incoming-transit" / timing["version"]
    prior = read(original / "report.json")
    if any(report[k] != prior[k] for k in ("joint", "workerRelease", "residentRiders", "timetable", "walking", "homeIndex")):
        raise ValueError("The timing comparison uses different weekday inputs")
    worker_dir = root / "commuters" / report["workerRelease"]
    workers = read(worker_dir / "commuters.json")
    presence = read(worker_dir / "presence.json")
    day = root / "cityday" / report["versions"]["day"]
    core = read(day / "day.json")["areas"].index("Downtown")
    places = read(day / "places.json")
    baseline = np.asarray(presence["counts"])
    expected = np.zeros_like(baseline)
    homes = report["homeIndex"]
    maximum = timing["stages"][-1]["extraMinutes"]
    events, durations = [], Counter()
    modified = {}
    seen = 0
    for i, group in enumerate(presence["cities"]):
        cohort = read(worker_dir / f"{group}.json")
        previous = read(original / f"{group}.json") if prior["groups"].get(group, [0, 0])[1] else []
        earlier = {tuple(row[:3]): row for row in previous}
        revised = read(folder / f"{group}.json") if report["groups"].get(group, [0, 0])[1] else []
        for trip in revised:
            new = tuple(trip[:3]) not in earlier
            if not new and earlier.pop(tuple(trip[:3])) != trip:
                raise ValueError("The timing comparison changed an existing booking")
            if not new:
                continue
            seen += 1
            person = cohort["people"][trip[1]]
            a, b, direction = extension(trip, person, homes+person[0], maximum)
            durations[b-a] += 1
            if a == b:
                continue
            overrides = modified.setdefault(group, {}).setdefault(trip[1], [None, None])
            overrides[direction//2] = a if direction == 0 else b
            downtown = int(places[person[1]][2] == core)
            col = 6*i + 3*downtown + direction
            events.append(tuple((first, last, col) for first, last in daily_segments(a, b-a)))
            for minute in range(a, b):
                expected[minute % 1440, i, downtown, direction] += 1
        if earlier:
            raise ValueError("The timing comparison lost existing bookings")
        homes += len(cohort["homes"])
    if seen != timing["added"] or homes != report["homeIndex"]+len(read(folder / "homes.json")):
        raise ValueError("Incoming workers or extended bookings did not reconcile")
    attending = np.array([workers["groups"][city]["attending"] for city in presence["cities"]])
    delta, execution = raster_presence(events, expected, backend, True)
    if np.any((baseline + delta).sum(axis=(2,3)) > attending) or delta[:, :, :, 1].any():
        raise ValueError("The timing comparison exceeded attendance or changed paid work")
    data = dict(joint=report["joint"], incoming=release, workerRelease=report["workerRelease"], cities=presence["cities"],
                occupancyDelta=delta.tolist(), windows=modified, extendedMinutes=dict(sorted(durations.items())), execution=execution)
    result = root / "incoming-timing-presence" / f"{release}.json"
    pointer(result, data)
    print(release, seen, sum(durations.values())-durations[0], int(delta.sum()), execution, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release")
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--backend", default="jvm")
    args = parser.parse_args()
    publish(args.root, args.release, args.backend)
