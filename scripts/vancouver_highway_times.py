"""Map B.C.'s 2022 Highway 1 travel-time observations onto the regional road graph."""
import argparse
import hashlib
import math
from pathlib import Path
import re
import subprocess
import tempfile

import networkx as nx

from scripts.vancouver_atlas import write_json
from scripts.vancouver_cityday import xy
from scripts.vancouver_region import read, rows
from scripts.vancouver_streets import encode_way, permissions


STUDY = "https://www.vmcdn.ca/files/nsnews/files/binnie-iwmb-travel-time-study-final-rev0.pdf"
HOURS = [6, 7, 8, 13, 15, 16, 17]
# Figure 3-4 locates the cuts at the interchanges. Match each carriageway independently.
CUTS = [
    ("Lynn Valley Road", -123.05355, 49.32878),
    ("Mountain Highway", -123.03762, 49.31564),
    ("Mount Seymour Parkway", -123.02845, 49.31175),
    ("Main Street / Dollarton Highway", -123.02747, 49.30486),
    ("McGill Street", -123.02790, 49.28960),
]


def observation_tables(pdf):
    layout = subprocess.check_output(["pdftotext", "-layout", str(pdf), "-"], text=True)
    observation = re.compile(r"\b(\d{2}):00\s*-\s*\d{2}:00\s+\d+\.\d+\s+(\d+\.\d+)")
    tables = {}
    for table, name in enumerate([f"{direction}BD{i}" for direction in ("S", "N") for i in range(1, 5)], 1):
        title = re.search(rf"(?m)^ +Table 5-{table}: 2018 and 2022 Travel Time Comparison for {name} OD Pair *$", layout)
        if title is None:
            raise ValueError(f"Missing travel-time table 5-{table}")
        page = layout[title.end():].split("\f", 1)[0]
        samples = observation.findall(re.split(r"(?m)^ +Table 5-\d+:", page, maxsplit=1)[0])
        if [int(h) for h, _ in samples] != HOURS:
            raise ValueError(f"Unexpected hours in table 5-{table}: {samples}")
        times = [float(value) for _, value in samples]
        if any(value <= 0 for value in times):
            raise ValueError(f"Nonpositive median in table 5-{table}")
        tables[name] = times
    return tables


def mainline(network, profile, roads):
    nodes, ids, names = [], {}, {}
    ordered = iter(zip(network["ways"], profile["kmh"], strict=True))
    graph = nx.DiGraph()
    for way in roads:
        tags = way.get("tags", {})
        bits = permissions(tags)
        if not bits or len(way.get("nodes", [])) < 2:
            continue
        expected, kmh = next(ordered)
        actual = encode_way(way, bits, nodes, ids, names)
        if actual != expected:
            raise ValueError("The archived OSM ways differ from the released street graph")
        if tags.get("highway") != "motorway" or tags.get("ref") != "TCH 1":
            continue
        for a, b in zip(actual[2], actual[2][1:]):
            x, y = nodes[a]
            if not (2700 < x < 7100 and -8800 < y < -2300):
                continue
            length = math.dist(nodes[a], nodes[b])
            if length:
                if bits & 2:
                    graph.add_edge(a, b, minutes=length / (kmh[0] * 1000 / 60))
                if bits & 4:
                    graph.add_edge(b, a, minutes=length / (kmh[1] * 1000 / 60))
    if next(ordered, None) is not None or nodes != network["nodes"] or list(names) != network["names"]:
        raise ValueError("The street network and speed archive have different coverage")
    return graph


def fit_corridors(graph, points, tables):
    corridors, seen = [], set()
    for direction, cuts, signed in (("S", CUTS, 1), ("N", CUTS[::-1], -1)):
        candidates = {i for a, b in graph.edges if signed * (points[b][1] - points[a][1]) > 0 for i in (a, b)}
        anchors = []
        for name, lon, lat in cuts:
            point = xy(lon, lat)
            offset, node = min((math.dist(point, points[i]), i) for i in candidates)
            if offset > 65:
                raise ValueError(f"Missing Highway 1 carriageway near {name} ({direction})")
            anchors.append((name, node, round(offset, 1)))
        for i, (start, end) in enumerate(zip(anchors, anchors[1:]), 1):
            name = f"{direction}BD{i}"
            path = nx.shortest_path(graph, start[1], end[1], weight="minutes")
            arcs = list(zip(path, path[1:]))
            length = sum(math.dist(points[a], points[b]) for a, b in arcs)
            if not 450 < length < 2500 or any(arc in seen for arc in arcs):
                raise ValueError(f"Unexpected Highway 1 path: {name} ({length:.0f} m)")
            seen.update(arcs)
            free = sum(graph[a][b]["minutes"] for a, b in arcs)
            targets = tables[name]
            factors = [max(1, minutes / free) for minutes in targets]
            corridors.append(dict(name=name, start=start, end=end, arcs=arcs, lengthMetres=length,
                                  freeMinutes=free, observedMinutes=targets, factors=factors))
    return corridors


def publish(region, roads, pdf):
    streets = read(region/"current.json")["streets"]
    parent = region/"drive-profile"
    base = parent/(streets+".json")
    profile = read(base)
    with roads.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != profile["sourceDigest"]:
            raise ValueError("The OSM archive differs from the driving speed profile")
    network = read(region/"streets"/streets/"network.json")
    tables = observation_tables(pdf)
    corridors = fit_corridors(mainline(network, profile, rows(roads)), network["nodes"], tables)
    profile["hourly"] = dict(hours=HOURS, corridors=corridors, year=2022, source=STUDY,
                             studyDigest=hashlib.sha256(pdf.read_bytes()).hexdigest(),
                             baselineDigest=hashlib.sha256(base.read_bytes()).hexdigest())
    with tempfile.TemporaryDirectory(dir=parent) as tmp:
        output = Path(tmp)/"profile.json"
        write_json(output, profile)
        output.replace(parent/(streets+"_highway1.json"))
    for c in corridors:
        print(c["name"], round(c["lengthMetres"]), round(c["freeMinutes"], 2),
              [round(c["freeMinutes"]*factor, 2) for factor in c["factors"]])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=Path("data/mobility/ironworkers-travel-times-2022.pdf"))
    parser.add_argument("--roads", type=Path, default=Path("data/region/work/roads.jsonl"))
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    args = parser.parse_args()
    publish(args.region, args.roads, args.pdf)
