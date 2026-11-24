"""Route complete discretionary driver outings on Vancouver's directed bicycle network."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from scipy.sparse.csgraph import dijkstra

from scripts.vancouver_atlas import write_json
from scripts.vancouver_cycling import FORWARD, REVERSE
from scripts.vancouver_inbound import read
from scripts.vancouver_mobility import travel_bouts
from scripts.vancouver_region import package
from scripts.vancouver_streets import access_graph
from scripts.vancouver_survey_zones import geography
from scripts.vancouver_trip_demand import destination

SPEED = 220  # The municipal replay's bicycle speed ceiling, metres/minute.
ACCESS = {"210": 59, "220": 53, "330": 72, "340": 69, "350": 67, "360": 69,
          "370": 59, "380": 68, "390": 72, "unmapped": 65}  # City survey Table 8, person access.
SEED = 20261122


def assign_access(free, riders, percent, rng):
    """Match the zonal marginal among known adults, retaining recorded cyclists."""
    target = round((len(free) + len(riders)) * percent / 100)
    if len(riders) > target:
        raise ValueError("Recorded cyclist count exceeds the adult bicycle access target")
    drawn = rng.choice(free, size=target-len(riders), replace=False)
    return np.concatenate((riders, drawn)).astype(int)


def bicycle_access(atlas_dir, day_dir, geo, diaries):
    atlas = read(atlas_dir/"atlas.json")
    ids = read(day_dir/"day.json")["das"]
    recorded = [any(ep[3] == "bike" for ep in t["episodes"]) for t in diaries]
    offsets, size = [], 0
    pool = defaultdict(list)
    codes = [str(z["code"]) for z in geo["zones"]]
    for da in ids:
        people = read(atlas_dir/(da+".json"))["people"]
        home = read(day_dir/(da+".json"))["home"]
        offsets.append(size)
        for i in range(atlas["das"][da]["private"]):
            p = people[i]
            if 4 <= p[0] <= 13:
                z = geo["zone"][home[i]]
                pool[codes[z] if z >= 0 else "unmapped", recorded[p[-1]]].append(size+i)
        size += len(people)
    flags = np.zeros(size, dtype=np.uint8)  # outside cohort / no access / access
    coverage = {}
    for code, rate in ACCESS.items():
        free, riders = pool[code, False], pool[code, True]
        selected = assign_access(free, riders, rate, np.random.default_rng([SEED, 0 if code=="unmapped" else int(code)]))
        flags[free] = 1
        flags[selected] = 2
        coverage[code] = dict(adults=len(free)+len(riders), access=len(selected), retainedCyclists=len(riders))
    return offsets, flags, coverage


def route_tours(candidates, coords, network):
    graph, snap = access_graph(network, FORWARD, REVERSE)
    nodes, access = snap(coords, lowest_id_on_ties=True)
    pairs = {}
    groups = defaultdict(list)
    stats = defaultdict(Counter)
    located = []
    for d, i, tpl, zone, purpose, legs in candidates:
        s = stats[zone]
        s["candidates"] += 1
        if any(min(a, b) < 0 or np.array_equal(coords[a], coords[b]) for _, _, a, b in legs):
            s["unlocatedOrColocated"] += 1
            continue
        if any(np.linalg.norm(coords[a]-coords[b]) > n*SPEED for _, n, a, b in legs):
            s["straightLineExceeded"] += 1
            continue
        located.append((d, i, tpl, zone, purpose, legs))
        for _, n, a, b in legs:
            pairs[a, b] = max(pairs.get((a, b), 0), n*SPEED)
    # Many tours share shops and other destinations. Root each search at the
    # more frequent end, reversing the directed graph for a destination root.
    origins = Counter(nodes[a] for a, _ in pairs)
    destinations = Counter(nodes[b] for _, b in pairs)
    for (a, b), limit in pairs.items():
        reverse = destinations[nodes[b]] > origins[nodes[a]]
        root, end = (nodes[b], nodes[a]) if reverse else (nodes[a], nodes[b])
        groups[reverse, root].append((a, b, end, limit))
    graphs = [graph, graph.transpose().tocsr()]
    lengths = {}
    for (rev, root), rows in groups.items():
        dist = dijkstra(graphs[rev], indices=root, limit=max(r[3] for r in rows))
        for a, b, end, limit in rows:
            metres = access[a] + dist[end] + access[b]
            if metres <= limit:
                lengths[a, b] = metres
    accepted = []
    for d, i, tpl, zone, purpose, legs in located:
        if any(lengths.get((a, b), np.inf) > n*SPEED for _, n, a, b in legs):
            stats[zone]["streetTimeExceededOrDisconnected"] += 1
            continue
        accepted.append([d, i, tpl, zone, purpose, legs])
        stats[zone]["feasible"] += 1
        stats[zone]["legs"] += len(legs)
    return accepted, stats


def publish(root, boundaries, backend="jvm", *, joint=None):
    if joint:
        versions = read(root/"joint-weekday"/joint/"report.json")["versions"]
        atlas, day, streets = (versions[key] for key in ("atlas", "day", "streets"))
    else:
        ptr = read(root/"cityday/current.json")
        atlas, day = ptr["atlas"], ptr["version"]
        streets = read(root/"streets/current.json")["version"]
    cycling = read(root/"cycling"/(streets+".json"))["version"]
    if read(root/"cycling"/cycling/"source.json")["streets"] != streets:
        raise ValueError("The bicycle graph uses a different street release")
    demand = read(root/"trip-demand"/(atlas+"_"+day+".json"))["version"]
    audit = read(root/"trip-demand"/demand/"demand.json")
    places = read(root/"cityday"/day/"places.json")
    geo = geography(boundaries, places)
    if (audit["atlas"], audit["day"], audit["geography"]) != (atlas, day, geo["digest"]):
        raise ValueError("Population or survey geography mismatch")
    diaries = read(root/"atlas"/atlas/"atlas.json")["templates"]
    terms = [[[s, destination(a, b)] for s, _, a, b in travel_bouts(t["episodes"])] for t in diaries]
    versions = dict(atlas=atlas, day=day, streets=streets, cycling=cycling, demand=demand)
    def build(folder):
        inputs, candidates = folder.parent/"inputs.json", folder.parent/"candidates.jsonl"
        write_json(inputs, dict(zone=geo["zone"], codes=[str(z["code"]) for z in geo["zones"]], purposes=terms))
        subprocess.run(["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.cycle-tours",
                        root/"atlas"/atlas, root/"cityday"/day, inputs, candidates], check=True)
        with candidates.open() as stream:
            tours, stats = route_tours(map(json.loads, stream), np.array([p[:2] for p in places]),
                                       read(root/"cycling"/cycling/"network.json"))
        offsets, flags, coverage = bicycle_access(root/"atlas"/atlas, root/"cityday"/day, geo, diaries)
        flags.tofile(folder/"access.bin")
        for row in tours:
            d, i = row[:2]
            row.append(bool(flags[offsets[d]+i] == 2))
        rows = []
        for zone in [dict(code="all", name="Whole city", shares=audit["cityShares"]), *audit["zones"],
                     dict(code="unmapped", name="Unmapped homes", shares={})]:
            code = zone["code"]
            cells = [r for r in audit["cells"] if code == "all" or r[0] == code]
            selected = [r for r in tours if code == "all" or r[3] == code]
            has_bike = [r for r in selected if r[6]]
            counts = sum(stats.values(), Counter()) if code == "all" else stats[code]
            if counts["candidates"] != sum(counts[k] for k in ("unlocatedOrColocated", "straightLineExceeded", "streetTimeExceededOrDisconnected", "feasible")):
                raise ValueError("Unaccounted driver outings")
            rows.append(dict(code=code, name=zone["name"], survey=zone["shares"].get("Cycling"),
                             trips=sum(r[3] for r in cells)/5, bikes=sum(r[3] for r in cells if r[1]=="Cycling")/5,
                             residents=len({(r[0], r[1]) for r in selected}), accessTours=len(has_bike),
                             accessResidents=len({(r[0], r[1]) for r in has_bike}), accessLegs=sum(len(r[5]) for r in has_bike),
                             accessRate=ACCESS.get(code, 65), accessPopulation=(coverage[code] if code != "all"
                                 else dict(sum((Counter(v) for v in coverage.values()), Counter()))), **counts))
        write_json(folder/"report.json", dict(versions=versions, zones=rows, speed=SPEED, tours=len(tours),
                                               offsets=offsets, seed=SEED))
        write_json(folder/"tours.json", tours)
    version = package(root, "cycle-tours", build)
    parent = root/"cycle-tours"
    raster = root/"raster"
    raster.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=raster) as tmp:
        clock = Path(tmp)/"clock.json"
        subprocess.run(["clojure", "-J--add-modules=jdk.incubator.vector", "-J--enable-native-access=ALL-UNNAMED",
                        "-M", "-m", "city.vancouver.cycle-tour-clock", parent/version, clock, backend], check=True)
        clock.replace(raster/(version+"-cycle-tours.json"))
    with tempfile.TemporaryDirectory(dir=parent) as tmp:
        f = Path(tmp)/"pointer"
        write_json(f, dict(version=version))
        f.replace(parent/("_".join([atlas, day, streets, cycling])+".json"))
    return version


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    p.add_argument("--boundaries", type=Path, default=Path("data/mobility/taz-gvrd.geojson"))
    p.add_argument("--backend", default="jvm", help="Raster target for the minute-by-minute mode projection")
    p.add_argument("--joint", help="Use the atlas, day and street releases of this combined weekday")
    args = p.parse_args()
    print(publish(args.root, args.boundaries, args.backend, joint=args.joint))
