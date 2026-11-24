"""Execute incoming workers' work stops and commutes with the resident weekday Raster phase."""
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from scripts.artifacts import write_json


def daily_segments(start, length):
    """Split an interval at civil midnight on the representative periodic weekday."""
    if not 0 < length <= 1440:
        raise ValueError("Invalid length for a daily interval")
    start %= 1440
    end = start + length
    if end > 1440:
        return [(start, 1440), (0, end - 1440)]
    return [(start, end)]


def schedule(row, spans, base):
    _, _, _, _, _, start, duration, span, attending, template = row
    if not attending:
        return ()
    arrival = start + duration
    intervals = [(start, duration, 0), (arrival + span, duration, 2)]
    intervals.extend((arrival + a, b - a, 1) for a, b in spans[template])
    return tuple((a, b, base + kind) for t, length, kind in intervals for a, b in daily_segments(t, length))


def reference(roster, spans, core, zones):
    """Count individual workers by clock minute directly from elapsed tour time."""
    ref = np.zeros((1440, 2, 3), dtype=int)
    rows = roster[roster[:, 8] == 1]
    area = (zones[rows[:, 1]] == core).astype(int)
    # Independent pointwise evaluation avoids relying on the event encoder's wrapping rules.
    for tpl in np.unique(rows[:, 9]):
        take = rows[:, 9] == tpl
        for group in range(2):
            batch = rows[take & (area == group)]
            for k in range(0, len(batch), 256):
                block = batch[k:k + 256]
                elapsed = (np.arange(1440)[:, None] - block[:, 5]) % 1440
                duration, span = block[:, 6], block[:, 7]
                ref[:, group, 0] += (elapsed < duration).sum(axis=1)
                offset = elapsed - duration
                ref[:, group, 2] += ((offset >= span) & (offset < span + duration)).sum(axis=1)
                for a, b in spans[tpl]:
                    ref[:, group, 1] += ((offset >= a) & (offset < b)).sum(axis=1)
    return ref


def raster_presence(schedules, expected, backend, verify):
    cols = int(np.prod(expected.shape[1:]))
    ids, weights, offsets, starts, ends = [], [], [0], [], []
    lookup = {}
    for events in schedules:
        g = lookup.get(events)
        if g is None:
            g = len(weights)
            lookup[events] = g
            weights.append(0)
            for a, b, zone in events:
                starts.append(a * cols + zone)
                ends.append(b * cols + zone)
            offsets.append(len(starts))
        ids.append(g)
        weights[g] += 1
    execution = dict(backend=backend, checkedWorkers=verify, groups=len(weights), workers=len(ids))
    if not starts:
        if expected.any():
            raise ValueError("The empty Raster schedule differs from the expected clock")
        return expected, execution
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        columns = {"population": ids, "group-sizes": weights, "starts": starts, "ends": ends, "offsets": offsets,
                   "shifts": np.zeros(len(starts)), "ranks": np.zeros(len(weights))}
        for name, values in columns.items():
            np.asarray(values, dtype="<i4").tofile(work / (name + ".i32"))
        write_json(work / "shape.json", dict(zones=cols, steps=int(max(np.diff(offsets))), levels=[0]))
        fidelities = ["groups", "agents"] if verify else ["groups"]
        subprocess.run(["clojure", "-J--enable-native-access=ALL-UNNAMED", "-J--add-modules=jdk.incubator.vector",
                        "-M", "-m", "city.vancouver.occupancy-run", str(work), backend, *fidelities], check=True)
        for fidelity in fidelities:
            changes = np.fromfile(work / (fidelity + "-0.i32"), dtype="<i4").reshape(1441, *expected.shape[1:])
            counts = changes.cumsum(axis=0)
            if counts[-1].any() or not np.array_equal(counts[:-1], expected):
                raise ValueError(f"Raster differs from the per-worker clock in {fidelity} mode")
    return counts[:-1], execution


def publish_presence(out, groups, spans, zones, core, backend, verify):
    cities = sorted(groups)
    expected = np.zeros((1440, len(cities), 2, 3), dtype=int)

    def schedules():
        for i, city in enumerate(cities):
            people = json.loads((out / (city + ".json")).read_bytes())["people"]
            expected[:, i] = reference(np.asarray(people), spans, core, zones)
            for person in people:
                base = 6 * i + 3 * int(zones[person[1]] == core)
                yield schedule(person, spans, base)

    counts, execution = raster_presence(schedules(), expected, backend, verify)
    write_json(out / "presence.json", dict(cities=cities, counts=counts.tolist()))
    return execution
