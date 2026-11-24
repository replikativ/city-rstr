"""Compare the municipal weekday with Vancouver's 2023 travel survey planning zones."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from matplotlib.path import Path as Polygon
from scipy.spatial import cKDTree

from scripts.artifacts import package, read, write_json
from scripts.vancouver_cityday import ORIGIN, SCALE
from scripts.vancouver_mobility import SOURCE

TAZ_ITEM = "31b1106ca5fb4c91b303e26f446eb173"
SHA256 = "3b8f6ba3c0daea9637807c8eb4c6b4cba72755682c655023be09800d2647538f"
# TAZ group, City zone, Table 18 shares (work, other home-based, non-home-based),
# Table 1 land area (km²) and adult private-household population.
ZONES = [
    (210, "CBD – West End", 29, 53, 19, 6.50, 54800),
    (220, "CBD – False Creek", 32, 47, 37, 3.34, 55200),
    (330, "Vancouver Broadway", 21, 49, 21, 7.16, 58600),
    (340, "Vancouver South", 6, 40, 12, 21.32, 81600),
    (350, "Vancouver Kerrisdale", 13, 46, 13, 22.19, 50900),
    (360, "Vancouver Kitsilano", 12, 54, 19, 10.85, 57800),
    (370, "Vancouver Southeast", 4, 38, 9, 17.58, 86900),
    (380, "Vancouver East", 3, 36, 4, 20.10, 100000),
    (390, "Vancouver Port", 16, 41, 16, 8.08, 39000),
]
BORDER_METRES = 200


def classify(points, polygons, radius):
    """Assign points to a group. Flag proximity to a polygon of another group."""
    xy = np.asarray(points, dtype=float)
    tree = cKDTree(xy)
    codes = np.full(len(xy), -1, dtype=int)
    edges = defaultdict(set)
    for group, rings in polygons:
        outer = rings[0]
        lo, hi = outer.min(axis=0), outer.max(axis=0)
        indices = np.flatnonzero(np.all((xy >= lo) & (xy <= hi), axis=1))
        inside = Polygon(outer).contains_points(xy[indices])
        for hole in rings[1:]:
            inside &= ~Polygon(hole).contains_points(xy[indices])
        hits = indices[inside]
        ambiguous = (codes[hits] != -1) & (codes[hits] != group)
        codes[hits] = np.where(ambiguous, -2, group)
        for ring in rings:
            for start, end in zip(ring, ring[1:]):
                a, b = tuple(start), tuple(end)
                if a != b:
                    edges[group].add(tuple(sorted((a, b))))

    # Shared boundaries within a group do not affect the zone assignment.
    near = np.zeros(len(xy), dtype=bool)
    for group, segments in edges.items():
        for a, b in segments:
            a, b = np.asarray(a), np.asarray(b)
            segment = b - a
            search_radius = radius + np.linalg.norm(segment) / 2
            ids = np.array(tree.query_ball_point((a + b) / 2, search_radius), dtype=int)
            candidates = ids[(codes[ids] >= 0) & (codes[ids] != group) & ~near[ids]]
            if len(candidates):
                delta = xy[candidates] - a
                t = np.clip((delta @ segment) / (segment @ segment), 0, 1)
                distance = np.linalg.norm(delta - t[:, None] * segment, axis=1)
                near[candidates] |= distance <= radius
    return codes, near


def geography(source, places):
    payload = source.read_bytes()
    if hashlib.sha256(payload).hexdigest() != SHA256:
        raise ValueError("The zone crosswalk requires the documented TAZ_GVRD release")
    polygons = []
    areas = defaultdict(float)
    codes = {zone[0]: i for i, zone in enumerate(ZONES)}
    for feature in json.loads(payload)["features"]:
        properties, geometry = feature["properties"], feature["geometry"]
        if properties["MUNI_1"] != "Vancouver":
            continue
        i = codes[properties["gh"]]
        areas[i] += properties["Hectares"] / 100
        if geometry["type"] not in ("MultiPolygon", "Polygon"):
            raise ValueError("Expected areal traffic zones")
        parts = geometry["coordinates"]
        if geometry["type"] == "Polygon":
            parts = [parts]
        for rings in parts:
            projected = [(np.asarray(r)[:, :2] - ORIGIN) * SCALE for r in rings]
            polygons.append((i, projected))
    zone, near = classify([p[:2] for p in places], polygons, BORDER_METRES)
    zones = [
        dict(name=name, code=code, observed=work, other=other, nonhome=nonhome,
             land=land, adults=adults, tazLand=areas[i])
        for i, (code, name, work, other, nonhome, land, adults) in enumerate(ZONES)
    ]
    return dict(zone=zone.tolist(), border=near.tolist(), metres=BORDER_METRES,
                zones=zones, digest=SHA256, source=SOURCE, item=TAZ_ITEM)


def publish(root, source, versions=None):
    if versions is None:
        current = read(root / "cityday/current.json")
        versions = dict(atlas=current["atlas"], day=current["version"])
    atlas = root / "atlas" / versions["atlas"]
    day = root / "cityday" / versions["day"]
    outbound = read(root / "outbound" / f"{atlas.name}_{day.name}.json")["version"]
    worksites = read(root / "worksites" / (outbound + ".json"))["version"]
    with tempfile.TemporaryDirectory() as tmp:
        inputs = Path(tmp) / "geography.json"
        write_json(inputs, geography(source, read(day / "places.json")))

        def build(folder):
            subprocess.run([
                "clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.survey-zones", atlas, day,
                root / "outbound" / outbound, root / "worksites" / worksites,
                inputs, folder / "zones.json",
            ], check=True)

        version = package(root, "survey-zones", build)
    pointer = root / "survey-zones" / (worksites + ".json")
    with tempfile.TemporaryDirectory(dir=pointer.parent) as tmp:
        staged = Path(tmp) / "pointer"
        write_json(staged, dict(version=version))
        staged.replace(pointer)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--zones", type=Path, default=Path("data/mobility/taz-gvrd.geojson"))
    args = parser.parse_args()
    print(publish(args.data, args.zones))
