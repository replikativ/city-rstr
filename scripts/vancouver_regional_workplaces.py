"""Fit regional workplace destinations with a fixed resident roster and weekday clock."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from scripts.artifacts import package, read, write_json
from scripts.vancouver_atlas import largest_remainder
from scripts.vancouver_bridge_traffic import IRONWORKERS, IRONWORKERS_FILE, REGIONAL_BRIDGES, MAX_CONNECTOR, screen_arcs
from scripts.vancouver_cityday import SPEED
from scripts.vancouver_streets import access_graph

CENSUS = (
    ("5915022", "Vancouver (CY), B.C."),
    ("5915051", "North Vancouver (CY), B.C."),
    ("5915046", "North Vancouver (DM), B.C."),
    ("5915055", "West Vancouver (DM), B.C."),
)
SOURCE = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810045901"
TABLE = Path("data/mobility/workplace-matrix-2021.csv")
ROAD = {"car-driver", "car-passenger", "taxi", "ridehail", "motorcycle"}


def census_matrix(path):
    sources = {f"2021A0005{csd}": i for i, (csd, _) in enumerate(CENSUS)}
    targets = {name: i for i, (_, name) in enumerate(CENSUS)}
    values = np.full((len(CENSUS), len(CENSUS)), -1, dtype=int)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        records = csv.reader(stream)
        header = next(records)
        residence, workplace, year = map(header.index, ["DGUID", "Place of work", "REF_DATE"])
        total = header.index("Gender (3):Total - Gender[1]")
        for row in records:
            i, j = sources.get(row[residence]), targets.get(row[workplace])
            if i is None or j is None:
                continue
            if row[year] != "2021" or row[total+1] or values[i, j] >= 0:
                raise ValueError("Invalid or repeated workplace matrix cell")
            values[i, j] = int(row[total])
    if (values < 0).any() or (values.sum(axis=1) == 0).any():
        raise ValueError("Incomplete 2021 workplace matrix")
    return values


def bridge_distances(network, coords):
    bridges = [*REGIONAL_BRIDGES, IRONWORKERS]
    sites = [{"name": site[1]} for site in bridges]
    arcs = screen_arcs(network, sites, bridges)
    graph, snap = access_graph(network, 2, 4)
    nodes, offsets = snap(coords, lowest_id_on_ties=True)
    reverse = graph.T.tocsr()
    entering, exiting, length = [], [], []
    for a, b in arcs:
        entering.append(dijkstra(reverse, indices=a)[nodes])
        exiting.append(dijkstra(graph, indices=b)[nodes])
        length.append(graph[a, b])
    return np.asarray(entering), np.asarray(exiting), np.asarray(length)[:, None], offsets


def paired_distance(anchor, sites, north, coords, roads, mode):
    straight = np.linalg.norm(coords[sites] - coords[anchor], axis=1)
    across = north[sites] != north[anchor]
    if mode in ROAD and across.any():
        entering, exiting, length, offsets = roads
        xs = sites[across]
        there = np.min(entering[:, [anchor]] + length + exiting[:, xs], axis=0)
        back = np.min(entering[:, xs] + length + exiting[:, [anchor]], axis=0)
        straight[across] = np.maximum(there, back) + offsets[anchor] + offsets[xs]
        straight[across & ((offsets[anchor] > MAX_CONNECTOR) | (offsets[sites] > MAX_CONNECTOR))] = np.inf
    return straight


def alternative(row, options, coords, north, roads):
    _, _, _, _, original, _, legs = row
    if not legs or any(anchor < 0 or mode not in SPEED or duration <= 0 for anchor, duration, mode in legs):
        return None
    home, allowance, tightest_mode = min(legs, key=lambda leg: SPEED[leg[2]] * leg[1])
    nearby, tree = options
    delta = coords[original] - coords[home]
    metres = np.linalg.norm(delta)
    # Look near the old direction of travel and near the tightest commitment.
    center = coords[home] + delta * min(0.8, (SPEED[tightest_mode] * allowance * 0.6) / max(metres, 1))
    k = min(24, len(nearby))
    _, found = tree.query([center, coords[home]], k=k)
    candidates = nearby[np.unique(found)]
    ratio = np.zeros(len(candidates))
    original_ratio = 0
    for anchor, duration, mode in legs:
        budget = SPEED[mode] * duration
        before = paired_distance(anchor, np.array([original]), north, coords, roads, mode)[0] / budget
        after = paired_distance(anchor, candidates, north, coords, roads, mode) / budget
        ratio = np.maximum(ratio, after)
        original_ratio = max(original_ratio, before)
    viable = np.flatnonzero(ratio <= 1)
    if not len(viable):
        return None
    j = viable[np.argmin(np.abs(ratio[viable] - min(original_ratio, 0.8)))]
    return int(candidates[j]), original_ratio, float(ratio[j])


def allocate(workers, place_groups, coords, census, roads):
    n = len(CENSUS)
    by_pair = defaultdict(list)
    before = np.zeros((n, n), dtype=int)
    for row in workers:
        by_pair[row[2], row[3]].append(row)
        before[row[2], row[3]] += 1
    target = np.array([largest_remainder(stock / stock.sum(), int(total))
                       for stock, total in zip(census, before.sum(axis=1), strict=True)]).astype(int)
    if not np.array_equal(target.sum(axis=1), before.sum(axis=1)):
        raise ValueError("Workplace targets do not conserve the resident worker margin")
    inventory = np.unique([row[4] for row in workers])
    pools = [inventory[place_groups[inventory] == group] for group in range(n)]
    if any(not len(pool) for pool in pools):
        raise ValueError("Every regional municipality needs at least one workplace anchor")
    options = [(pool, cKDTree(coords[pool])) for pool in pools]
    north = place_groups > 0
    after = before.copy()
    moves = defaultdict(list)
    for home in range(n):
        movable = set()
        shortages = np.flatnonzero(target[home] > after[home])
        surpluses = np.flatnonzero(target[home] < after[home])
        for dest in sorted(shortages, key=lambda j: (after[home, j] - target[home, j], j)):
            candidates = []
            for origin in surpluses:
                if after[home, origin] <= target[home, origin]:
                    continue
                for row in by_pair[home, origin]:
                    d, person, _, _, original, slots, _ = row
                    if (d, person) in movable:
                        continue
                    option = alternative(row, options[dest], coords, north, roads)
                    if option is not None:
                        site, previous_ratio, ratio = option
                        candidates.append((previous_ratio <= 1, -min(previous_ratio, 10), ratio, d, person,
                                           origin, original, slots, site))
            for _, _, _, d, person, origin, original, slots, site in sorted(candidates):
                if after[home, dest] == target[home, dest]:
                    break
                if after[home, origin] <= target[home, origin]:
                    continue
                after[home, origin] -= 1
                after[home, dest] += 1
                movable.add((d, person))
                moves[d].append([person, slots, original, site])
    if not np.array_equal(before.sum(axis=1), after.sum(axis=1)):
        raise ValueError("Workplace moves changed a home worker margin")
    return dict(before=before.tolist(), target=target.tolist(), after=after.tolist()), moves


def variant_day(base, day, places, moves, roster, out, *, destinations=()):
    if destinations:
        index = len(day["areas"])
        day["areas"] = [*day["areas"], *destinations]
        # Travel and unresolved occupancy remain the final two columns.
        zero = [0] * len(destinations)
        day["occupancy"] = [row[:index] + zero + row[index:] for row in day["occupancy"]]
    area_count = len(day["areas"])
    area = np.asarray([p[2] if p[2] >= 0 else area_count + 1 for p in places])
    delta = np.zeros((1441, area_count+2), dtype=int)
    sample = {(d, i): plan for d, i, _, plan, _ in day["sample"]}
    for d, da in enumerate(day["das"]):
        file = da + ".json"
        if d not in moves:
            os.link(base/file, out/file)
            continue
        population = read(roster/file)["people"]
        record = read(base/file)
        for person, slots, original, dest in moves[d]:
            plan = record["plans"][person]
            for slot in slots:
                if plan[slot] != original:
                    raise ValueError("Workplace no longer matches its source plan")
                plan[slot] = dest
            if (d, person) in sample:
                sample[d, person][:] = plan
            for start, duration, mode, slot, _ in day["templates"][population[person][7]]["parts"]:
                if mode != "stop" or slot not in slots:
                    continue
                a, b = start - 240, start - 240 + duration
                delta[a, area[original]] -= 1
                delta[b, area[original]] += 1
                delta[a, area[dest]] += 1
                delta[b, area[dest]] -= 1
        write_json(out/file, record)
    checks = delta.cumsum(axis=0)
    counts = np.array(day["occupancy"]) + checks[:-1]
    if checks[-1].any() or (counts < 0).any() or (counts.sum(axis=1) != day["population"]).any():
        raise ValueError("Paired workplace day does not conserve the population")
    day["occupancy"] = counts.tolist()
    write_json(out/"day.json", day)
    if destinations:
        write_json(out/"places.json", places)
    else:
        os.link(base/"places.json", out/"places.json")
    os.link(base/"mobility.json", out/"mobility.json")


def publish(root, table):
    versions = read(root/"current.json")
    base, roster = root/"cityday"/versions["day"], root/"atlas"/versions["atlas"]
    day, places = read(base/"day.json"), read(base/"places.json")
    with tempfile.TemporaryDirectory() as tmp:
        file = Path(tmp)/"workers.json"
        subprocess.run(["clojure", "-M", "-m", "city.vancouver.regional-workplaces", roster, base, file], check=True)
        extracted = read(file)
    print(f"Allocating workplaces for {len(extracted['workers']):,} scheduled workers.", flush=True)
    coords = np.asarray([p[:2] for p in places])
    network = read(root/"streets"/versions["streets"]/"network.json")
    roads = bridge_distances(network, coords)
    del network
    census = census_matrix(table)
    matrix, moves = allocate(extracted["workers"], np.asarray(extracted["placeGroups"]), coords, census, roads)
    del extracted["workers"]
    count = sum(map(len, moves.values()))
    print(f"Moved {count:,} workplaces. {matrix}", flush=True)
    variant = package(root, "cityday", lambda out: variant_day(base, day, places, moves, roster, out), versions["day"])
    summary = dict(versions=versions, **matrix, day=variant, moved=count,
                   municipalities=extracted["municipalities"], census=census.tolist(),
                   source=SOURCE, sourceDigest=hashlib.sha256(table.read_bytes()).hexdigest())
    report = package(root, "regional-workplaces", lambda out: write_json(out/"report.json", summary))
    return summary, report


def publish_companions(root, archive, inputs, summary, release, backend="jvm", *, timed_roads=False):
    from scripts.vancouver_bridge_traffic import publish_region
    from scripts.vancouver_campus import publish as publish_campus
    from scripts.vancouver_departures import publish as publish_departures
    from scripts.vancouver_raster import publish as publish_raster
    from scripts.vancouver_street_walks import publish as publish_walks
    from scripts.vancouver_visitors import publish as publish_visitors

    parent = summary["versions"]
    version = {**parent, "day": summary["day"]}
    metrics = ({}, {"road_speeds": True}, {"observed_highway1": True}) if timed_roads else ({},)
    with ThreadPoolExecutor(max_workers=len(metrics)) as worker:
        bridge_reports = [
            worker.submit(publish_region, archive, root.parent, Path("data/mobility")/IRONWORKERS_FILE,
                          weekday_versions=version, **metric)
            for metric in metrics
        ]
        publish_raster(root, version["atlas"], version["day"], backend=backend)
        publish_walks(root, version)
        publish_campus(root, version)
        publish_visitors(archive, root, version, inputs)
        publish_departures(root.parent, archive, scope="region", region_versions=version)
        for report in bridge_reports:
            report.result()
    directory = root/"regional-workplaces"
    parent_key = "_".join(parent[k] for k in ("atlas", "day", "streets"))
    with tempfile.TemporaryDirectory(dir=directory) as tmp:
        pointer = Path(tmp)/"pointer.json"
        write_json(pointer, {"version": release})
        pointer.replace(directory/(parent_key + ".json"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--table", type=Path, default=TABLE)
    parser.add_argument("--inputs", type=Path, default=Path("data/region"))
    parser.add_argument("--backend", default="jvm")
    args = parser.parse_args()
    root = args.data/"region"
    result, release = publish(root, args.table)
    publish_companions(root, args.archive, args.inputs, result, release, args.backend)
    print(release, result, flush=True)
