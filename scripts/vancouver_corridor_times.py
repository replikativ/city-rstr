"""Publish measured weekday travel speeds on Vancouver's directed street graph."""
import argparse
import hashlib
import math
from pathlib import Path
from statistics import median
import subprocess
import tempfile

import networkx as nx
from PIL import Image

from scripts.vancouver_atlas import write_json
from scripts.vancouver_highway_times import STUDY as HIGHWAY_STUDY
from scripts.vancouver_region import read


STUDY = "https://www.caa.ca/app/uploads/2021/01/16170_Canadian_National_Bottlenecks_Study_EN_1_4_17.pdf"
STUDY_HASH = "20e98df5ac5e8ab64185c7d1ef2c882cc27c720784e50a99cc9d4c68c42e01fd"
HOURS = list(range(24))
# Figure 13 identifies the reaches. Its south Granville cut at West 57th is approximate.
SITES = [
    ("granville-south", "Granville Street", "West 57th Avenue", "Southwest Marine Drive", (1400, 1770)),
    ("georgia", "West Georgia Street", "Seymour Street", "West Pender Street", (1100, 1500)),
    ("granville-broadway", "Granville Street", "West Broadway", "West 16th Avenue", (500, 850)),
]
# Hour 1 and 24 marker centres, 0 and 40 km/h ordinates, and data windows in Figure 14's raster.
AXES = [(87, 529, 326.5, 217.8, 186, 262), (86, 520, 713.4, 607.6, 625, 677),
        (89, 526, 1121.8, 1014.1, 1008, 1077)]


def observations(pdf):
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != STUDY_HASH:
        raise ValueError("The CAA report differs from the Figure 14 source used for digitization")
    with tempfile.TemporaryDirectory() as tmp:
        prefix = Path(tmp)/"figure"
        subprocess.run(["pdfimages", "-f", "24", "-l", "24", "-png", str(pdf), str(prefix)], check=True)
        with Image.open(prefix.with_name("figure-000.png")) as image:
            if image.size != (548, 1212):
                raise ValueError("Unexpected Figure 14 dimensions")
            pixels = image.convert("RGB").load()
    profiles = []
    for first, last, zero, forty, low, high in AXES:
        speeds = []
        for hour in HOURS:
            x = round(first + (last - first) * hour / 23)
            marker = []
            for y in range(low, high):
                for col in range(x-1, x+2):
                    red, green, blue = pixels[col, y]
                    if red < 135 and blue - red >= 15 and green - red >= 9:
                        marker.append(y)
            if not marker or max(marker) - min(marker) > 9:
                raise ValueError(f"Could not isolate the speed marker in hour {hour + 1}")
            speeds.append(round(40 * (zero - median(marker)) / (zero - forty)))
        profiles.append(speeds)
    return profiles


def named_streets(network, profile):
    names = {name for _, name, *_ in SITES}
    cuts = {cut for _, _, a, b, _ in SITES for cut in (a, b)}
    graphs = {name: nx.DiGraph() for name in names}
    cross = {name: set() for name in cuts}
    for (bits, index, path), kmh in zip(network["ways"], profile["kmh"], strict=True):
        name = network["names"][index]
        if name in cross:
            cross[name].update(path)
        if name not in graphs or not bits & 6:
            continue
        for a, b in zip(path, path[1:]):
            length = math.dist(network["nodes"][a], network["nodes"][b])
            if length == 0:
                continue
            for bit, speed, u, v in ((2, kmh[0], a, b), (4, kmh[1], b, a)):
                if bits & bit:
                    minutes = length * .06 / speed
                    graph = graphs[name]
                    if not graph.has_edge(u, v) or graph[u][v]["minutes"] > minutes:
                        graph.add_edge(u, v, length=length, minutes=minutes)
    return graphs, cross


def match_direction(graph, sources, targets, length_range):
    candidates = []
    for a in sorted(sources & graph.nodes):
        for b in sorted(targets & graph.nodes):
            try:
                path = nx.shortest_path(graph, a, b, weight="minutes")
            except nx.NetworkXNoPath:
                continue
            edges = list(zip(path, path[1:]))
            length = sum(graph[u][v]["length"] for u, v in edges)
            if length_range[0] <= length <= length_range[1]:
                candidates.append((sum(graph[u][v]["minutes"] for u, v in edges), path, length))
    if not candidates:
        raise ValueError("No permitted route connects the published corridor cuts")
    return min(candidates)


def lnglat(point):
    x, y = point
    return [x / 72600 - 123.1, 49.26 - y / 111195]


def fit(network, profile, speeds):
    graphs, cross = named_streets(network, profile)
    corridors, sites = [], []
    for (key, name, a, b, bounds), kmh in zip(SITES, speeds, strict=True):
        directions = []
        for start, end in ((a, b), (b, a)):
            free, path, length = match_direction(graphs[name], cross[start], cross[end], bounds)
            observed = [length * .06 / speed for speed in kmh]
            corridors.append(dict(name=f"{key}/{start}", arcs=list(zip(path, path[1:])),
                                  factors=[max(1, value / free) for value in observed]))
            directions.append(dict(start=start, end=end, lengthMetres=round(length), freeMinutes=round(free, 3),
                                   modeledMinutes=[round(max(free, value), 3) for value in observed],
                                   line=[lnglat(network["nodes"][node]) for node in path]))
        sites.append(dict(id=key, street=name, start=a, end=b, observedKmh=kmh, directions=directions))
    return corridors, sites


def highway_corridors(hourly):
    for corridor in hourly["corridors"]:
        factors = dict(zip(hourly["hours"], corridor["factors"], strict=True))
        yield dict(name=corridor["name"], arcs=corridor["arcs"], factors=[factors.get(hour, 1) for hour in HOURS])


def publish(root, streets, speeds, regional=False):
    parent = root/"drive-profile"
    baseline = parent/(streets + ".json")
    base_digest = hashlib.sha256(baseline.read_bytes()).hexdigest()
    profile = read(baseline)
    if profile["streets"] != streets:
        raise ValueError("The driving speeds belong to another street release")
    network = read(root/"streets"/streets/"network.json")
    corridors, sites = fit(network, profile, speeds)
    sources = [dict(url=STUDY, year=2015, digest=STUDY_HASH, figures=[13, 14])]
    if regional:
        old = read(parent/(streets + "_highway1.json"))
        highway = old["hourly"]
        if old["streets"] != streets or highway["baselineDigest"] != base_digest or highway["source"] != HIGHWAY_STUDY:
            raise ValueError("The Highway 1 observations belong to a different baseline")
        corridors.extend(highway_corridors(highway))
        sources.append(dict(url=highway["source"], year=highway["year"], digest=highway["studyDigest"]))
    arcs = [tuple(arc) for corridor in corridors for arc in corridor["arcs"]]
    if len(arcs) != len(set(arcs)):
        raise ValueError("An observed road edge appears in more than one corridor")

    profile["hourly"] = dict(hours=HOURS, corridors=corridors, baselineDigest=base_digest, sources=sources)
    affected = [[network["nodes"][a], network["nodes"][b]]
                for corridor in corridors if max(corridor["factors"]) > 1 for a, b in corridor["arcs"]]
    report = dict(streets=streets, sources=sources, sites=sites, affected=affected, baselineDigest=base_digest)
    releases = parent/"corridor-times"
    releases.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as tmp:
        temporary = Path(tmp)
        build = temporary/"build"
        build.mkdir()
        profile_file = build/"profile.json"
        write_json(profile_file, profile)
        report["profileDigest"] = hashlib.sha256(profile_file.read_bytes()).hexdigest()
        report_file = build/"report.json"
        write_json(report_file, report)
        version = hashlib.sha256(report_file.read_bytes()).hexdigest()[:20]
        destination = releases/version
        if not destination.exists():
            try:
                build.rename(destination)
            except OSError:
                if not destination.exists():
                    raise
        pointer = temporary/"current.json"
        write_json(pointer, dict(version=version, streets=streets))
        pointer.replace(parent/(streets + "_corridor-times.json"))
    print(root, version, [(site["id"], [d["lengthMetres"] for d in site["directions"]]) for site in sites])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=Path("data/mobility/caa-bottlenecks-2015.pdf"))
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    args = parser.parse_args()
    profiles = observations(args.pdf)
    publish(args.data, read(args.data/"streets/current.json")["version"], profiles)
    region = args.data/"region"
    publish(region, read(region/"current.json")["streets"], profiles, regional=True)
