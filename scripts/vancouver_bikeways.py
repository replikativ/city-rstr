"""Match pre-2024 City bikeways to the directed municipal bicycle graph."""
import argparse
from collections import Counter
import hashlib
import math
from pathlib import Path
import tempfile

import numpy as np
from scipy.spatial import cKDTree

from scripts.vancouver_atlas import write_json
from scripts.vancouver_cycling import FORWARD, REVERSE
from scripts.vancouver_region import package, read

SOURCE = "https://opendata.vancouver.ca/explore/dataset/bikeways/"
ALIGN = math.cos(math.radians(25))
SHORT = dict(west="w", east="e", north="n", south="s", avenue="ave", street="st",
             drive="dr", boulevard="blvd", road="rd", lane="ln", highway="hwy", crescent="cres")


def street_name(name):
    return " ".join(SHORT.get(word, word) for word in (name or "").lower().replace(".", "").split())


def matches_street(osm, municipal, route):
    if not osm or osm in (municipal, route):
        return True
    base, _, suffix = osm.rpartition(" ")
    return base == municipal and suffix in {"st", "ave", "rd", "dr", "ln", "cres", "blvd", "way", "pl"}


def eligible(props):
    year = props["year_of_construction"]
    return (props["status"] == "Active" and year and int(year) < 2024
            and int(props["upgrade_year"] or 0) < 2024)


def project(coords):
    return np.asarray([[(x+123.1)*72600, (49.26-y)*111195] for x, y in coords])


def match(net, features):
    # Subdivide City lines so a midpoint query with radius 16 m finds every
    # piece whose line is within 10 m of the probe (piece length <= 10 m).
    starts, ends, sources = [], [], []
    props = [f["properties"] for f in features]
    for uid, f in enumerate(features):
        if not eligible(props[uid]):
            continue
        coords = project(f["geometry"]["coordinates"])
        for a, b in zip(coords, coords[1:]):
            n = math.ceil(math.dist(a, b)/10)
            if n:
                pts = np.linspace(a, b, n+1)
                starts.extend(pts[:-1]); ends.extend(pts[1:])
                sources.extend([uid]*n)
    starts, ends, sources = np.array(starts), np.array(ends), np.array(sources)
    vectors = ends-starts
    lengths = np.linalg.norm(vectors, axis=1)
    units = vectors/lengths[:, None]
    tree = cKDTree((starts+ends)/2)
    names = [street_name(p["street_name"]) for p in props]
    routes = [street_name(p["bike_route_name"]) for p in props]
    edges = {}
    for bits, name, ids in net["ways"]:
        for a, b in zip(ids, ids[1:]):
            if a != b:
                edges[a,b,name] = edges.get((a,b,name), 0) | bits
    keys = list(edges)
    points = np.asarray(net["nodes"])
    a, b, name_ids = np.asarray(keys).T
    start, end = points[a], points[b]
    delta = end-start
    length = np.linalg.norm(delta, axis=1)
    tangent = delta/np.maximum(length, 1)[:, None]
    name_keys = [street_name(n) for n in net["names"]]
    # Match in both directions. Require agreement at 15%, 50% and 85% so a
    # perpendicular crossing or a lone matching endpoint cannot label an edge.
    supported = np.ones((len(keys), 2), dtype=bool)
    matched_sources = [set() for _ in keys]
    for fraction in (0.15, 0.5, 0.85):
        probes = start+fraction*delta
        for k, candidates in enumerate(tree.query_ball_point(probes, 16)):
            if not candidates or not supported[k].any() or not length[k]:
                supported[k] = False
                continue
            candidates = np.asarray(candidates)
            candidates = candidates[np.abs(units[candidates] @ tangent[k]) >= ALIGN]
            off = probes[k]-starts[candidates]
            along = np.clip(np.sum(off*units[candidates], axis=1), 0, lengths[candidates])
            errors = np.linalg.norm(off-along[:, None]*units[candidates], axis=1)
            choices = [False, False]
            for j in np.argsort(errors):
                if errors[j] > 10:
                    break
                uid = sources[candidates[j]]
                osm = name_keys[name_ids[k]]
                if not matches_street(osm, names[uid], routes[uid]):
                    continue
                p = props[uid]
                axis = p["overall_direction"]
                if axis not in ("NS", "EW", "E"):
                    continue
                # Local graph axes point east and south, both in e_s_bound_type.
                es = delta[k][1 if axis == "NS" else 0] > 0
                choices = [bool(p["e_s_bound_type" if es else "w_n_bound_type"]),
                           bool(p["w_n_bound_type" if es else "e_s_bound_type"])]
                matched_sources[k].add(uid)
                break
            supported[k] &= choices
    arcs, used = set(), set()
    for k, ((a,b,name), bits) in enumerate(edges.items()):
        matched = False
        if supported[k,0] and bits & FORWARD:
            arcs.add((a,b)); matched = True
        if supported[k,1] and bits & REVERSE:
            arcs.add((b,a)); matched = True
        if matched:
            used.update(matched_sources[k])
    undirected = {tuple(sorted(pair)) for pair in arcs}
    return dict(arcs=sorted(arcs), cityFeatures=len(props), eligible=sum(bool(eligible(p)) for p in props),
                matchedFeatures=len(used), matchedTypes=dict(Counter(props[i]["bikeway_type"] for i in used)),
                matchedKm=round(sum(math.dist(points[a], points[b]) for a,b in undirected)/1000, 2))


def publish(root, source, cycling=None):
    if not cycling:
        street = read(root/"streets/current.json")["version"]
        cycling = read(root/"cycling"/(street+".json"))["version"]
    def build(folder):
        data = match(read(root/"cycling"/cycling/"network.json"), read(source)["features"])
        write_json(folder/"profile.json", dict(**data, cycling=cycling, offBikewayCost=1.25,
                                              source=SOURCE, sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    version = package(root, "bikeways", build)
    folder = root/"bikeways"
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        p = Path(tmp)/"pointer.json"
        write_json(p, dict(version=version))
        p.replace(folder/(cycling+".json"))
    print(version, {k:v for k,v in read(folder/version/"profile.json").items() if k!="arcs"})
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--source", type=Path, default=Path("data/mobility/vancouver-bikeways.geojson"))
    args = parser.parse_args()
    publish(args.data, args.source)
