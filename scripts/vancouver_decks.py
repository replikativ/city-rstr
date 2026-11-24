"""Fit Vancouver bridge-deck profiles to NRCan surface heights along mapped routes."""
import argparse
from collections import defaultdict
import hashlib
import math
from pathlib import Path
import shutil
import tempfile
from urllib.request import urlopen

import numpy as np
from scipy.interpolate import CubicHermiteSpline, PchipInterpolator
from scipy.ndimage import median_filter
from scipy.signal import savgol_filter
from scipy.spatial import cKDTree

from scripts.vancouver_atlas import write_json
from scripts.vancouver_cityday import xy
from scripts.vancouver_region import package, rows
from scripts.vancouver_terrain import Elevation, hrdem_url, mercator, WORLD, INPUTS, composite


BRIDGES = {
    "lions": ("Lions Gate Bridge", (-123.1428, 49.3111, -123.1299, 49.3246),
              (70954668, 70954672), (127433137,)),
    "ironworkers": ("Ironworkers Memorial Second Narrows Crossing", (-123.0285, 49.291, -123.0252, 49.3043),
                    (35260598, 62125826), (48608391, 682010971)),
    "burrard": ("Burrard Street Bridge", (-123.1448, 49.2726, -123.1323, 49.2774),
                (74263733, 74263736, 302351831, 750371206), (684320952, 74094190)),
    "granville": ("Granville Bridge", (-123.1438, 49.2642, -123.1269, 49.2771),
                  (538616396, 538616397, 871038539, 871038545, 871038551, 871038563, 1316244489,
                   1316244491, 1383685288, 1417439065, 1417439066, 1419312043, 1533457403), (26440580, 341691672)),
    "cambie": ("Cambie Street Bridge", (-123.118, 49.2653, -123.1136, 49.2762),
               (374640036, 113244334, 113244337, 972113593, 972113595), (56864237, 56864248, 46906475, 46906477, 46906479)),
}


def surface_url(frame):
    lower, upper = mercator(*frame[:2]), mercator(*frame[2:])
    return hrdem_url((*map(math.floor, lower), *map(math.ceil, upper)), "dsm", 2)


def acquire(folder):
    folder.mkdir(parents=True, exist_ok=True)
    for key, (_, frame, _, _) in BRIDGES.items():
        file = folder/(key + ".tif")
        receipt = file.with_suffix(".url")
        url = surface_url(frame)
        if file.is_file() and receipt.is_file() and receipt.read_text().strip() == url:
            continue
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            staged = Path(tmp)/file.name
            with urlopen(url, timeout=120) as response, staged.open("wb") as output:
                shutil.copyfileobj(response, output)
            Elevation(staged)
            staged.replace(file)
            receipt.write_text(url + "\n")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def survey_coordinates(points):
    lon = points[..., 0] / 72600 - 123.1
    lat = 49.26 - points[..., 1] / 111195
    return lon * WORLD / 180, np.arcsinh(np.tan(np.deg2rad(lat))) * WORLD / math.pi


def lengths(points):
    return np.r_[0, np.linalg.norm(np.diff(points, axis=0), axis=1).cumsum()]


def alignment(way):
    data = [(ref, tuple(xy(p["lon"], p["lat"]))) for ref, p in zip(way["nodes"], way["geometry"], strict=True)]
    nodes, vertices = zip(*(item for i, item in enumerate(data) if not i or item[1] != data[i-1][1]))
    vertices = np.asarray(vertices)
    cuts = lengths(vertices)
    steps = np.unique(np.r_[np.arange(0, cuts[-1], 3), cuts])
    points = np.column_stack([np.interp(steps, cuts, values) for values in vertices.T])
    return nodes, np.searchsorted(steps, cuts), steps, points


def interpolate_surface(steps, heights, omit=None):
    measured = np.isfinite(heights)
    if omit is not None:
        measured &= ~omit
    if np.count_nonzero(measured) < 2:
        return None
    preliminary = np.interp(steps, steps[measured], heights[measured])
    nearby = median_filter(preliminary, size=19, mode="nearest")
    measured &= abs(heights - nearby) <= 1.75
    if np.count_nonzero(measured) < 2:
        return None
    corrected = np.interp(steps, steps[measured], heights[measured])
    interpolator = PchipInterpolator(steps[measured], heights[measured], extrapolate=False)
    internal = (steps >= steps[measured][0]) & (steps <= steps[measured][-1])
    corrected[internal] = interpolator(steps[internal])
    if omit is not None and np.any(omit):
        gap = steps[omit]
        support = [np.flatnonzero(measured & (steps < gap[0]) & (steps > gap[0]-45)),
                   np.flatnonzero(measured & (steps > gap[-1]) & (steps < gap[-1]+45))]
        if all(len(indices) >= 2 for indices in support):
            a, b = ends = [support[0][-1], support[1][0]]
            grades = [np.polyfit(steps[indices], heights[indices], 1)[0] for indices in support]
            arch = CubicHermiteSpline(steps[ends], heights[ends], grades)
            corrected[a:b+1] = arch(steps[a:b+1])
    smooth = savgol_filter(corrected, min(11, (len(steps)-1)//2*2+1), 2) if len(steps) >= 5 else corrected
    # Bound the grade through isolated non-road objects in the surface raster.
    bound = .12 * np.diff(steps)
    forward, backward = smooth.copy(), smooth[::-1].copy()
    for grade, limits in ((forward, bound), (backward, bound[::-1])):
        for i, change in enumerate(limits, 1):
            grade[i] = np.clip(grade[i], grade[i-1]-change, grade[i-1]+change)
    return (forward + backward[::-1]) / 2


def observed_height(surface, points):
    tangent = np.gradient(points, axis=0)
    perpendicular = np.column_stack((-tangent[:, 1], tangent[:, 0]))
    perpendicular /= np.linalg.norm(perpendicular, axis=1)[:, None]
    offsets = np.array([-1.4, 0, 1.4])
    x, y = survey_coordinates(points[None, :, :] + offsets[:, None, None] * perpendicular)
    heights = surface.sample(x.ravel(), y.ravel()).reshape(x.shape)
    # Strip out cable, rail and sign returns on a single sample across the lane.
    with np.errstate(invalid="ignore"):
        masked = np.ma.masked_invalid(heights)
        return np.ma.median(masked, axis=0).filled(np.nan)


def road_width(key, tags):
    if key == "lions":
        return 16.2 if tags.get("bridge") else 11
    if key == "burrard":
        return 23 if tags.get("bridge") else 16
    try:
        lanes = min(8, max(1, int(tags.get("lanes", 2))))
    except ValueError:
        lanes = 2
    return lanes * 3.5 + (1 if tags.get("oneway") == "yes" else 3.5)


def is_bridge(tags):
    return tags.get("bridge", "no") != "no"


def relevant_ways(roads):
    by_bridge = defaultdict(list)
    for way in rows(roads):
        tags = way["tags"]
        for key, (name, _, paths, ramps) in BRIDGES.items():
            side = way["id"] in paths
            if side or way["id"] in ramps or tags.get("name") == name and is_bridge(tags):
                by_bridge[key].append((way, side))
                break
    return by_bridge


def extract(key, ways, surface, terrain):
    routes, witnesses = [], defaultdict(list)
    south = np.array(xy(-123.143869, 49.273243))
    burrard = np.array(xy(-123.133193, 49.276687)) - south
    for way, side in sorted(ways, key=lambda row: (row[1], row[0]["id"])):
        nodes, vertices, steps, points = alignment(way)
        if side:
            continue
        raw = observed_height(surface, points)
        omit = None
        if key == "burrard" and is_bridge(way["tags"]):
            fraction = (points - south) @ burrard / (burrard @ burrard)
            omit = (.589 < fraction) & (fraction < .735)
        heights = interpolate_surface(steps, raw, omit)
        if heights is None:
            raise ValueError(f"No visible road surface on {key} way {way['id']}")
        routes.append((way, nodes, vertices, steps, points, heights, road_width(key, way["tags"]), False))
        for node, index in zip(nodes, vertices, strict=True):
            witnesses[node].append(heights[index])
    cores = [route for route in routes if is_bridge(route[0]["tags"])]
    samples = np.concatenate([route[4] for route in cores])
    measured = np.concatenate([route[5] for route in cores])
    tree = cKDTree(samples)
    for way, side in sorted(ways, key=lambda row: row[0]["id"]):
        if not side:
            continue
        nodes, vertices, steps, points = alignment(way)
        near, index = tree.query(points)
        along_road = measured[index]
        raw = observed_height(surface, points)
        # Near the route, transfer its deck height past towers and railings.
        valid = np.where(near <= 18, along_road, raw)
        heights = interpolate_surface(steps, valid)
        if heights is None:
            raise ValueError(f"No path surface on {key} way {way['id']}")
        routes.append((way, nodes, vertices, steps, points, heights, 2.7, True))
        for node, index in zip(nodes, vertices, strict=True):
            witnesses[node].append(heights[index])
    geometry = []
    for way, nodes, vertices, steps, points, heights, width, side in routes:
        # Match mapped junction heights across ways so a turn has one surface.
        joined = [float(np.median(witnesses[node])) for node in nodes]
        heights += np.interp(steps, steps[vertices], joined - heights[vertices])
        tagged = is_bridge(way["tags"])
        if not tagged:
            edge = [i for i in (0, -1) if len(witnesses[nodes[i]]) == 1]
            ground, _ = composite(terrain, *survey_coordinates(points))
            taper = np.zeros(len(points))
            for end in edge:
                dist = steps if end == 0 else steps[-1] - steps
                span = min(max(30, abs(heights[end]-ground[end])*16), steps[-1])
                weight = 1 - np.minimum(1, dist / span)
                taper = np.maximum(taper, weight * weight * (3 - 2 * weight))
            heights += taper * (ground - heights)
        coords = np.column_stack((points, heights)).round(2).tolist()
        geometry.append(dict(way=way["id"], name=way["tags"].get("name", ""), walk=side, width=width,
                             vertices=vertices.tolist(), points=coords))
    return geometry


def build(roads, folder, ground, payload):
    routes = relevant_ways(roads)
    sources = {key: dict(sha256=digest(folder/(key + ".tif")), url=(folder/(key + ".url")).read_text().strip()) for key in BRIDGES}
    terrain = [Elevation(ground/(key + ".tif")) for key in INPUTS]
    results = []
    for key, (name, _, _, _) in BRIDGES.items():
        geometry = extract(key, routes[key], Elevation(folder/(key + ".tif")), terrain)
        maximum = max(p[2] for route in geometry if not route["walk"] for p in route["points"])
        if not 10 <= maximum <= 75:
            raise ValueError(f"Unlikely road-deck height on {name}: {maximum}")
        results.append(dict(id=key, name=name, maximum=maximum, ways=geometry))
        print(name, len(geometry), "mapped ways, maximum road height", maximum, flush=True)
    write_json(payload/"decks.json", dict(verticalDatum="CGVD2013", roads=digest(roads), sources=sources, bridges=results))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roads", type=Path, default=Path("data/region/work/roads.jsonl"))
    parser.add_argument("--elevation", type=Path, default=Path("data/region/bridge-elevation"))
    parser.add_argument("--ground", type=Path, default=Path("data/region/terrain"))
    parser.add_argument("--output", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    if args.fetch:
        acquire(args.elevation)
    version = package(args.output, "bridge-decks", lambda out: build(args.roads, args.elevation, args.ground, out))
    pointer = args.output/"bridge-decks/current.json"
    with tempfile.TemporaryDirectory(dir=pointer.parent) as tmp:
        temporary = Path(tmp)/"current.json"
        write_json(temporary, dict(version=version))
        temporary.replace(pointer)
    print(version)
