"""Compare workplace addresses using the same directed driving costs as the browser."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from scipy.sparse.csgraph import dijkstra

from scripts.artifacts import package, pointer, read, write_json
from scripts.vancouver_mobility import PRIORITY, REPORT
from scripts.vancouver_streets import access_graph


def arc_weights(hourly):
    weights = {}
    for corridor in hourly["corridors"]:
        factors = dict(zip(hourly["hours"], corridor["factors"], strict=True))
        if any(not np.isfinite(factor) or factor < 1 for factor in factors.values()):
            raise ValueError("The observed profile must preserve or increase road costs")
        for arc in map(tuple, corridor["arcs"]):
            if arc in weights:
                raise ValueError("Observed road sections cannot overlap")
            weights[arc] = factors
    return weights


def corridor_hours(endpoint, parents, masks, known):
    path = []
    while endpoint not in known:
        parent = int(parents[endpoint])
        if parent < 0:
            raise ValueError("The shortest path to a reachable address is incomplete")
        path.append((parent, endpoint))
        endpoint = parent
    hours = known[endpoint]
    for parent, stop in reversed(path):
        hours |= masks.get((parent, stop), 0)
        known[stop] = hours
    return hours


def score(routes, places, network, profile, hourly, on_paths=None):
    graph, snap = access_graph(network, 2, 4, speeds=profile["kmh"])
    graphs = (graph, graph.T.tocsr())
    coords = np.asarray([place[:2] for place in places])
    nodes, offsets = snap(coords, lowest_id_on_ties=True)
    access = offsets / (profile["connectorKmh"] * 1000 / 60)
    weights = arc_weights(hourly)
    masks = {arc: sum(1 << h for h, factor in factors.items() if factor > 1) for arc, factors in weights.items()}
    marked = (masks, {(b, a): value for (a, b), value in masks.items()})
    hourly_graphs = {}

    def affected_graph(hour, reverse):
        key = hour, reverse
        if key not in hourly_graphs:
            adjusted = graphs[reverse].copy()
            for (a, b), factors in weights.items():
                factor = factors.get(hour, 1)
                if factor == 1:
                    continue
                if reverse:
                    a, b = b, a
                lo, hi = adjusted.indptr[a:a+2]
                index = lo + np.searchsorted(adjusted.indices[lo:hi], b)
                if index >= hi or adjusted.indices[index] != b:
                    raise ValueError("A measured road edge is absent from the directed graph")
                adjusted.data[index] *= factor
            hourly_graphs[key] = adjusted
        return hourly_graphs[key]

    routes = np.asarray(routes, dtype=int).reshape(-1, 9)
    times = np.full((len(routes), 3), np.inf)
    impediment = np.full((len(routes), 2), "clock", dtype="U10")
    groups = defaultdict(list)
    slowed = np.zeros(len(routes), dtype=bool)
    for column in range(2):
        ends = routes[:, 4+2*column:6+2*column]
        a, b = ends.T
        same = (coords[a] == coords[b]).all(axis=1)
        outside = (offsets[ends] > profile["connectorMetres"]).any(axis=1)
        connectors = access[ends].sum(axis=1)
        remaining = routes[:, 3] - connectors + 1e-7
        impediment[outside, column] = "connector"
        impediment[same, column] = "samePlace"
        for i in np.flatnonzero(~same & ~outside & (remaining >= 0)):
            origin, destination = nodes[a[i]], nodes[b[i]]
            reverse = not routes[i, 8]
            if reverse:
                origin, destination = destination, origin
            groups[origin, reverse].append((i, column, destination, remaining[i], connectors[i]))

    for number, ((node, reverse), group) in enumerate(groups.items(), 1):
        cost, parents = dijkstra(graphs[reverse], indices=node, return_predecessors=True,
                                 limit=max(available for _, _, _, available, _ in group))
        if on_paths:
            on_paths(routes, group, node, reverse, cost, parents, nodes, access)
        corridor = {node: 0}
        variants = defaultdict(list)
        for i, column, dest, budget, connectors in group:
            if cost[dest] > budget:
                continue
            times[i, column] = connectors + cost[dest]
            impediment[i, column] = ""
            if column == 1:
                hour = (routes[i, 2] // 60) % 24
                if masks and corridor_hours(dest, parents, marked[reverse], corridor) & (1 << hour):
                    variants[hour].append((i, dest, budget, connectors))
                    slowed[i] = True
                else:
                    times[i, 2] = times[i, 1]
        for hour, trips in variants.items():
            revised = dijkstra(affected_graph(hour, reverse), indices=node,
                               limit=max(budget for _, _, budget, _ in trips))
            for i, dest, budget, connectors in trips:
                if revised[dest] <= budget:
                    times[i, 2] = connectors + revised[dest]
        if number % 500 == 0:
            print(f"Checked {number:,} of {len(groups):,} directed workplace stops", flush=True)
    feasible = np.isfinite(times)
    if np.any(feasible[:, 2] & ~feasible[:, 1]) or np.any(times[feasible[:, 2], 2] < times[feasible[:, 2], 1] - 1e-6):
        raise ValueError("A slower road profile made a trip faster or newly feasible")
    return routes, times, impediment, slowed


def summarize(rows, times, impediment, slowed, das):
    feasible = np.isfinite(times)
    changed = np.any(rows[:, 4:6] != rows[:, 6:8], axis=1)
    hour = rows[:, 2] // 60 % 24

    def totals(keep):
        old, new, measured = feasible[keep].T
        return dict(trips=int(keep.sum()), changed=int((keep & changed).sum()),
                    feasible=feasible[keep].sum(axis=0).tolist(), gained=int((~old & new).sum()),
                    lost=int((old & ~new).sum()), affected=int((keep & slowed).sum()),
                    samePlace=(impediment[keep] == "samePlace").sum(axis=0).tolist(),
                    connector=(impediment[keep] == "connector").sum(axis=0).tolist(),
                    timeOrConnectivity=(impediment[keep] == "clock").sum(axis=0).tolist(),
                    meanMinutes=[round(float(np.mean(times[keep & feasible[:, i], i])), 3)
                                 if np.any(keep & feasible[:, i]) else None for i in range(3)])

    selectable = np.flatnonzero(changed & slowed & feasible[:, 2] & (times[:, 2] > times[:, 1]+1e-6))
    example = None
    if len(selectable):
        i = min(selectable, key=lambda i: (abs(hour[i] - 8), -(times[i, 2]-times[i, 1]), i))
        d, person, start, duration, *_ = rows[i].tolist()
        example = dict(da=das[d], index=person, start=start, duration=duration, baseline=round(times[i, 1], 4),
                       measured=round(times[i, 2], 4), endpoints=rows[i, 6:8].tolist())
    return dict(day=totals(np.ones(len(rows), dtype=bool)), hourly=[totals(hour == h) for h in range(24)], example=example)


def road_regressions(rows, times, das):
    """Retain the synthetic leg keys used to repair dropped driving trips."""
    failed = np.flatnonzero(np.isfinite(times[:, 0]) & ~np.isfinite(times[:, 2]))
    regressions = []
    for i in failed:
        d, resident, start, duration, a, b, c, e, from_work = rows[i].tolist()
        regressions.append(dict(da=das[d], index=resident, start=start, duration=duration,
                                diary=[a, b], revised=[c, e], fromWork=bool(from_work),
                                stage="corridor" if np.isfinite(times[i, 1]) else "workplace"))
    return regressions


def road_profiles(directory, streets, traffic):
    corridor = directory/"corridor-times"/traffic
    traffic_report = read(corridor/"report.json")
    baseline = (directory/(streets+".json")).read_bytes()
    measured = (corridor/"profile.json").read_bytes()
    if (traffic_report["streets"] != streets or hashlib.sha256(baseline).hexdigest() != traffic_report["baselineDigest"]
            or hashlib.sha256(measured).hexdigest() != traffic_report["profileDigest"]):
        raise ValueError("The directed road profiles do not match the corridor evidence")
    free, observed = json.loads(baseline), json.loads(measured)
    if any(observed[key] != free[key] for key in ("streets", "kmh", "connectorMetres", "connectorKmh")):
        raise ValueError("The corridor times must use the same free-flow reference graph and connectors")
    return free, observed, traffic_report


def publish(root, tract_id):
    tract = read(root/"tract-workplaces"/tract_id/"worksites.json")
    if not tract.get("preserveDiaryModes"):
        raise ValueError("Choose a workplace release that preserves diary modes")
    atlas, day, streets = (tract[k] for k in ("atlas", "day", "streets"))
    outings = read(root/"discretionary-outings"/f"{atlas}_{day}.json")["version"]
    street = root/"streets"/streets
    directory = root/"drive-profile"
    traffic = read(directory/(streets+"_corridor-times.json"))["version"]
    free, observed, traffic_report = road_profiles(directory, streets, traffic)

    versions = dict(atlas=atlas, day=day, streets=streets, tracts=tract_id)
    with tempfile.TemporaryDirectory() as tmp:
        request, result = (Path(tmp)/name for name in ("input.json", "legs.json"))
        write_json(request, dict(versions, outbound=tract["outbound"], worksites=tract["worksites"], outings=outings,
                                 priority=PRIORITY, surveyModes=REPORT, workplaceDrives=True))
        subprocess.run(["node", "scripts/vancouver_joint_trips.mjs", root, request, result], check=True)
        legs = read(result)["drives"]
    routes = legs.pop("trips")
    if len(routes) + sum(legs[k] for k in ("external", "unlocated", "mixed")) != legs["all"]:
        raise ValueError("Driving trip coverage does not reconcile")
    print(f"Checking {len(routes):,} single-mode workplace driving legs at both addresses", flush=True)
    day_dir = root/"cityday"/day
    values = score(routes, read(day_dir/"places.json"), read(street/"network.json"), free, observed["hourly"])
    das = read(day_dir/"day.json")["das"]
    summary = summarize(*values, das)
    regressions = road_regressions(*values[:2], das)
    if summary["day"]["trips"] != sum(row["trips"] for row in summary["hourly"]):
        raise ValueError("The hourly driving totals do not reconcile")
    if sum(row["stage"] == "workplace" for row in regressions) != summary["day"]["lost"]:
        raise ValueError("The driving trips lost after the workplace fit do not reconcile")
    report = dict(versions=versions, traffic=traffic, baselineDigest=traffic_report["baselineDigest"],
                  profileDigest=traffic_report["profileDigest"], sources=traffic_report["sources"], coverage=legs, **summary)
    family = "workplace-drives"
    def build(out):
        write_json(out/"report.json", report)
        write_json(out/"regressions.json", regressions)

    version = package(root, family, build)
    pointer(root/family/(tract_id+".json"), {"version": version})
    print(version, summary["day"], summary["example"], flush=True)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tract_release")
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    args = parser.parse_args()
    publish(args.root, args.tract_release)
