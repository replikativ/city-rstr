"""Verify municipal intersection workbooks and score the full paired pedestrian weekday."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from itertools import repeat
import json
from multiprocessing import get_context
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from scripts.vancouver_atlas import write_json
from scripts.vancouver_cityday import xy
from scripts.vancouver_grocery import HOLDOUT, reserved_studies
from scripts.vancouver_region import package
from scripts.vancouver_walks import RADIUS, SURVEYS, can_reach_site, passing_minute, verified_study
from scripts.vancouver_streets import walk_graph


def studies(archive):
    raw = archive / "data/raw"
    records = json.loads((archive / "data/derived/vancouver_ped_counts_mp.json").read_bytes())["counts"]
    by_id = {(r["site"], r["date"]): r for r in records}
    sites = []
    for key, name in SURVEYS.items():
        record = by_id[key]
        sheet = verified_study(raw, record, name)
        hours = [t for start, end in sheet["windows"] for t in range(start, end, 60)]
        observed = sheet["observed"]
        sites.append(dict(name=name, date=sheet["date"], point=xy(record["lon"], record["lat"]),
                          hours=hours, observed=[sum(observed[i:i+12]) for i in range(0, len(observed), 12)],
                          source=sheet["source"], reserved=False))
    for sheet in reserved_studies(raw, records):
        record, = [r for r in records if r["date"] == sheet["date"] and HOLDOUT.get(r["site"]) == sheet["name"]]
        sites.append(dict(sheet, point=xy(record["lon"], record["lat"]), reserved=True))
    return sites


def passage_groups(network, catalog, legs):
    graph, snap = walk_graph(network)
    places = sorted({place for _, a, b, *_ in legs for place in (a, b)})
    nodes, offsets = snap([catalog[p][:2] for p in places], lowest_id_on_ties=True)
    anchors = dict(zip(places, zip(nodes, offsets), strict=True))
    groups = defaultdict(list)
    for leg in legs:
        groups[anchors[leg[1]][0]].append(leg)
    return graph, anchors, list(groups.items())


def group_passages(graph, anchors, nodes, catalog, sites, groups):
    from scipy.sparse.csgraph import dijkstra
    for source, group in groups:
        dist, prev = dijkstra(graph, indices=source, limit=max(v[-1] for v in group), return_predecessors=True)
        for mode, a, b, start, duration, limit in group:
            target, offset = anchors[b]
            length = anchors[a][1] + dist[target] + offset
            if length > limit:
                continue
            origin, dest = catalog[a][:2], catalog[b][:2]
            path = None
            for j, site in enumerate(sites):
                if not can_reach_site(origin, dest, site["point"], length):
                    continue
                if path is None:
                    node = target
                    reverse = [dest, nodes[node]]
                    while node != source:
                        node = prev[node]
                        reverse.append(nodes[node])
                    path = [origin, *reversed(reverse)]
                at = passing_minute(path, site["point"], start, duration)
                if at is not None:
                    yield j, mode, int(at // 60) * 60


def routed_passages(network, catalog, sites, legs):
    """Yield passages through the count circles from grouped shortest-path trees."""
    if legs:
        graph, anchors, groups = passage_groups(network, catalog, legs)
        yield from group_passages(graph, anchors, network["nodes"], catalog, sites, groups)


def count_groups(graph, anchors, nodes, catalog, sites, groups):
    return Counter(group_passages(graph, anchors, nodes, catalog, sites, groups))


def passage_counts(network, catalog, sites, legs, workers=None):
    if not legs:
        return Counter()
    graph, anchors, groups = passage_groups(network, catalog, legs)
    if workers is None:
        processors = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count() or 1
        workers = min(4, processors) if len(groups) >= 1000 else 1
    workers = min(workers, len(groups))
    main_file = getattr(sys.modules["__main__"], "__file__", None)
    if workers <= 1 or not main_file or not Path(main_file).is_file():
        return count_groups(graph, anchors, network["nodes"], catalog, sites, groups)
    partitions = [groups[i::workers] for i in range(workers)]
    totals = Counter()
    with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as pool:
        for counts in pool.map(count_groups, repeat(graph), repeat(anchors), repeat(network["nodes"]),
                               repeat(catalog), repeat(sites), partitions):
            totals.update(counts)
    return totals


def verify_routes(root, report, spool):
    """Check every hourly passing count independently using grouped Dijkstra trees."""
    network = json.loads((root / "streets" / report["streets"] / "network.json").read_bytes())
    catalog = json.loads((root / "cityday" / report["day"] / "places.json").read_bytes())
    catalog.extend(spool["stations"])
    counts = passage_counts(network, catalog, report["sites"], spool["legs"])
    for j, site in enumerate(report["sites"]):
        for mode in report["coverage"]:
            actual = [counts[j, mode, hour] for hour in site["hours"]]
            if actual != site[mode]:
                raise ValueError(f"{site['name']} {mode}: Dijkstra {actual}, replay {site[mode]}")
    print("Verified hourly counts with independent shortest-path trees.", flush=True)


def publish(archive, root, verify=False, versions=None):
    def build(folder):
        spool = folder.parent / "walking-legs.json"
        command = ["node", "scripts/vancouver_pedestrians.mjs", str(root)]
        if verify:
            command.append(str(spool))
        result = subprocess.run(command,
                                input=json.dumps(dict(radius=RADIUS, sites=studies(archive), versions=versions)),
                                stdout=subprocess.PIPE, text=True, check=True)
        report = json.loads(result.stdout)
        if verify:
            verify_routes(root, report, json.loads(spool.read_bytes()))
        write_json(folder / "counts.json", report)
    version = package(root, "pedestrians", build)
    parent = root / "pedestrians"
    report = json.loads((parent / version / "counts.json").read_bytes())
    with tempfile.TemporaryDirectory(dir=parent) as folder:
        pointer = Path(folder) / "release.json"
        write_json(pointer, {"version": version, "tracts": report["tracts"]})
        pointer.replace(parent / (report["day"] + "_" + report["streets"] + ".json"))
    print(version, report["coverage"], flush=True)
    for site in report["sites"]:
        print(site["name"], "observed", sum(site["observed"]), "city", sum(site["city"]), "tracts", sum(site["tracts"]))
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--verify-routes", action="store_true", help="Repeat the walking counts using SciPy Dijkstra")
    args = parser.parse_args()
    publish(args.archive, args.data, args.verify_routes)


if __name__ == "__main__":
    main()
