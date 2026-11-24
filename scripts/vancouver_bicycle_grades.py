"""Add measured uphill grades to the municipal bicycle route preference."""
import argparse
from collections import Counter, defaultdict
import hashlib
from pathlib import Path
import tempfile

import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_cityday import ORIGIN, SCALE
from scripts.vancouver_cycling import directions, FORWARD, REVERSE
from scripts.vancouver_region import package, read
from scripts.vancouver_streets import encode_way
from scripts.vancouver_terrain import Elevation, composite, INPUTS, WORLD


GRADE_CUTOFFS = (.02, .04, .06)
GRADE_COSTS = [0, *(coefficient / 8.98 for coefficient in (2.85, 7.11, 13))]
STUDY = "https://doi.org/10.1016/j.tra.2012.07.005"


def surface(tags):
    return (tags.get("layer", "0") == "0" and
            all(tags.get(key, "no") == "no" for key in ("bridge", "tunnel", "covered")))


def heights(sources, points):
    lon, lat = (points / SCALE + ORIGIN).T
    z, source = composite(sources, lon * WORLD / 180, np.arcsinh(np.tan(np.deg2rad(lat))) * WORLD / np.pi)
    return np.where(source, z, np.nan)


def estimate(sources, points):
    """Average directed rise/run over the segment or a 40 m window on its way."""
    chain = np.r_[0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    if chain[-1] < 25:
        return np.full(len(chain) - 1, np.nan)
    width = np.minimum(chain[-1], np.maximum(40, np.diff(chain)))
    start = np.clip((chain[:-1] + chain[1:] - width) / 2, 0, chain[-1] - width)
    stations, inverse = np.unique(np.r_[start, start + width], return_inverse=True)
    sampled = heights(sources, np.column_stack([np.interp(stations, chain, axis) for axis in points.T]))
    lower, upper = np.split(sampled[inverse], 2)
    return (upper - lower) / width


def build(net, ways, sources):
    nodes, ids, names = [], {}, {}
    matches = defaultdict(set)
    ordered = iter(net["ways"])
    for way in ways:
        tags = way.get("tags", {})
        bits = directions(tags)
        if not bits or len(way.get("nodes", [])) < 2:
            continue
        encoded = encode_way(way, bits, nodes, ids, names)
        if encoded != next(ordered, None):
            raise ValueError("OSM source does not match the released bicycle graph")
        node_ids = encoded[2]
        points = np.asarray([nodes[i] for i in node_ids], dtype=float)
        slopes = estimate(sources, points) if surface(tags) else np.full(len(node_ids)-1, np.nan)
        for a, b, grade in zip(node_ids[:-1], node_ids[1:], slopes, strict=True):
            if a == b or nodes[a] == nodes[b]:
                continue
            for bit, start, end, slope in ((FORWARD, a, b, grade), (REVERSE, b, a, -grade)):
                if bits & bit:
                    band = int(np.searchsorted(GRADE_CUTOFFS, slope, side="right")) if np.isfinite(slope) else None
                    matches[start, end].add(band)
    if next(ordered, None) is not None or nodes != net["nodes"] or list(names) != net["names"]:
        raise ValueError("The bicycle graph and the OSM source have different coverage")
    ascent, coverage = [], Counter()
    for (a, b), bands in sorted(matches.items()):
        if len(bands) != 1 or None in bands:
            coverage["unknown"] += 1
            continue
        band = bands.pop()
        coverage[str(band)] += 1
        if band:
            ascent.append([a, b, band])
    return ascent, dict(coverage)


def publish(root, archive, inputs):
    streets = read(root/"streets/current.json")["version"]
    cycling = read(root/"cycling"/(streets+".json"))["version"]
    base = read(root/"bikeways"/(cycling+".json"))["version"]
    profile = read(root/"bikeways"/base/"profile.json")
    terrain = read(root/"terrain/current.json")["version"]
    manifest = read(root/"terrain"/terrain/"manifest.json")
    sources = []
    for name, item in zip(INPUTS, manifest["inputs"], strict=True):
        path = inputs/(name+".tif")
        with path.open("rb") as stream:
            if item["name"] != name or item["sha256"] != hashlib.file_digest(stream, "sha256").hexdigest():
                raise ValueError("The raw elevation extract differs from the published terrain")
        sources.append(Elevation(path))
    net = read(root/"cycling"/cycling/"network.json")
    source = archive/"data/raw/osm-overpass/vancouver_highways.json"
    with source.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != read(root/"cycling"/cycling/"source.json")["sha256"]:
            raise ValueError("The OSM extract differs from the cycling graph")
    ascents, coverage = build(net, read(source)["elements"], sources)
    profile.update(parentBikeways=base, terrain=terrain, uphillArcs=ascents, uphillCosts=GRADE_COSTS,
                   gradeCutoffs=GRADE_CUTOFFS, gradeCoverage=coverage, gradeEvidence=STUDY)
    version = package(root, "bikeways", lambda folder: write_json(folder/"profile.json", profile))
    parent = root/"bikeways"
    with tempfile.TemporaryDirectory(dir=parent) as tmp:
        pointer = Path(tmp)/"pointer"
        write_json(pointer, dict(version=version))
        pointer.replace(parent/(cycling+"-hills.json"))
    print(version, coverage, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--inputs", type=Path, default=Path("data/region/terrain"))
    args = parser.parse_args()
    publish(args.data, args.archive, args.inputs)
