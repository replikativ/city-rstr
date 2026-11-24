"""Route a Granville Island visitor scenario using the City's tourist-market estimate."""
import argparse
from collections import Counter
import hashlib
import math
from pathlib import Path

import numpy as np
from scipy.sparse.csgraph import dijkstra

from scripts.vancouver_atlas import write_json
from scripts.vancouver_cityday import xy
from scripts.vancouver_cycle_counts import SUMMER, screen_fraction
from scripts.vancouver_cycling import FORWARD, REVERSE
from scripts.vancouver_recreation_loops import LoopRouter
from scripts.vancouver_region import package, read
from scripts.vancouver_streets import access_graph, walk_graph
from scripts.vancouver_transit_commutes import pointer


STUDY = "https://vancouver.ca/files/cov/2025-020-release.pdf"
LICENCES = "https://opendata.vancouver.ca/explore/dataset/business-licences/"
MARKET = "https://granvilleisland.com/public-market"
PARKING = "https://www.openstreetmap.org/node/1692226725"
ANNUAL = 1_300_000  # City streetcar report Table 6.4, 2019 estimate
RESPONSES, CYCLISTS = 120, 2  # Intercept travel-market characteristics, FOI page 238
ANDERSON_TOTAL, ANDERSON_DAYS = 49454, 31  # June 12–July 12, 2024, Table D.5
OPEN, CLOSE = 540, 1080
BIKE_PACE, WALK_PACE, MAX_CONNECTOR = 180, 80, 80
SEED = 202024


def point_named(places, label):
    points = {tuple(p[:2]) for p in places if p[3] == label}
    if len(points) != 1:
        raise ValueError(f"Expected one mapped point for {label}")
    return next(iter(points))


def hotels(path):
    rows = read(path)
    if rows["total_count"] != len(rows["results"]):
        raise ValueError("The municipal hotel snapshot is incomplete")
    by_coordinate = {}
    for row in rows["results"]:
        staff = row.get("numberofemployees") or 0
        if staff < 10 or row["localarea"] not in {"Downtown", "West End", "Fairview"}:
            continue
        point = row["geo_point_2d"]
        pos = tuple(xy(point["lon"], point["lat"]))
        name = row["businesstradename"] or row["businessname"]
        if pos not in by_coordinate or staff > by_coordinate[pos][1]:
            by_coordinate[pos] = (name, staff)
    return [(pos, name, staff) for pos, (name, staff) in sorted(by_coordinate.items())]


def return_routes(network, graph, snap, anchor, origins, pace):
    """Get both directed paths from the same attached origin to the destination."""
    points = network["nodes"]
    root, tail = snap(anchor, lowest_id_on_ties=True)
    if tail > MAX_CONNECTOR:
        raise ValueError("The destination is too far from its legal network")
    outward, before = dijkstra(graph.T.tocsr(), indices=int(root), return_predecessors=True)
    inward, after = dijkstra(graph, indices=int(root), return_predecessors=True)
    origin_nodes, legs = snap(origins, lowest_id_on_ties=True)
    for start, node, access in zip(origins, origin_nodes, legs, strict=True):
        if access > MAX_CONNECTOR or not math.isfinite(outward[node] + inward[node]):
            yield None
            continue
        there = LoopRouter.stem(before, root, int(node))[::-1]
        back = LoopRouter.stem(after, root, int(node))
        result = []
        for sequence, a, b, length in ((there, start, anchor, outward[node]), (back, anchor, start, inward[node])):
            path = [a, *(points[i] for i in sequence), b]
            vertices = [p for i, p in enumerate(path) if i == 0 or tuple(p) != tuple(path[i-1])]
            result.append([max(1, math.ceil((length + tail + access) / pace)), vertices])
        yield result


def passage_sites(routes, visits):
    # The Anderson reference marks the entrance approach. The source gives the
    # street but does not publish the position of the counter.
    sites = {"anderson": ([-2708, -1086], [37, -40, 10], dict(name="Anderson entrance approach",
              observed=ANDERSON_TOTAL / ANDERSON_DAYS, source=STUDY+"#page=274"))}
    for key, name, year, count, position, screen, page in SUMMER:
        sites[key] = (xy(*position), screen, dict(name=name, observed=count,
                      source=f"https://vancouver.ca/files/cov/{year}-transportation-snapshot.pdf#page={page}"))
    counts = Counter(t[0] for t in visits)
    result = {}
    for key, (point, [dx, dy, width], reference) in sites.items():
        length = math.hypot(dx, dy)
        screen = [dx/length, dy/length, width]
        hit_counts = [0, 0]
        for route, n in counts.items():
            for k, (_, path) in enumerate(routes[route]["cycling"]):
                hit_counts[k] += n * sum(screen_fraction(a, b, point, screen, min_alignment=.5) is not None
                                          for a, b in zip(path, path[1:]))
        result[key] = dict(reference, inbound=hit_counts[0], outbound=hit_counts[1])
    return result


def publish(root, licence_file):
    base = read(root / "cityday/current.json")
    streets = read(root / "streets/current.json")["version"]
    bike = read(root / "cycling" / (streets + ".json"))["version"]
    parents = dict(atlas=base["atlas"], day=base["version"], streets=streets, cycling=bike)
    places = read(root / "cityday" / parents["day"] / "places.json")
    market = point_named(places, "Granville Island Public Market")
    parking = xy(-123.1357183, 49.2726569)  # Mapped bicycle rack by the market courtyard
    lodging = hotels(licence_file)
    network = read(root / "cycling" / bike / "network.json")
    cycling, snap = access_graph(network, FORWARD, REVERSE)
    routes, weights = [], []
    for (origin, name, staff), route in zip(lodging, return_routes(network, cycling, snap, parking,
                             [p for p, _, _ in lodging], BIKE_PACE), strict=True):
        if route is not None:
            routes.append(dict(origin=name, cycling=route))
            weights.append(staff)
    walk_network = read(root / "streets" / streets / "network.json")
    walking, walk_snap = walk_graph(walk_network)
    walk = next(return_routes(walk_network, walking, walk_snap, market, [parking], WALK_PACE))
    if not routes or not walk:
        raise ValueError("The hotel and Granville Island networks have no complete visitor itinerary")
    count = round(ANNUAL * CYCLISTS / RESPONSES / 365)
    rng = np.random.default_rng(SEED)
    visits = []
    for idx in rng.choice(len(routes), size=count, p=np.array(weights)/sum(weights)):
        dwell = int(rng.integers(45, 91))
        arrival = int(rng.integers(OPEN, CLOSE - dwell + 1))
        departure = arrival - walk[0][0] - routes[idx]["cycling"][0][0]
        visits.append([int(idx), departure, arrival, dwell])
    visits.sort(key=lambda v: (v[1], v[0]))
    presence = np.zeros(1441, dtype=int)
    for idx, departure, arrival, dwell in visits:
        end = arrival + dwell + walk[1][0] + routes[idx]["cycling"][1][0]
        if not 240 <= departure < arrival < arrival+dwell < end <= 1680:
            raise ValueError("A visitor itinerary falls outside the day")
        presence[arrival-240] += 1
        presence[arrival+dwell-240] -= 1
    report = dict(versions=parents, market=market, parking=parking, routes=routes, walk=walk, visits=visits,
                  presence=presence.cumsum()[:-1].tolist(), passages=passage_sites(routes, visits),
                  samples=dict(eligibleHotels=len(lodging), routedHotels=len(routes), hotelDigest=hashlib.sha256(licence_file.read_bytes()).hexdigest(),
                               annualTouristVisits=ANNUAL, responses=RESPONSES, cyclists=CYCLISTS, andersonDays=ANDERSON_DAYS),
                  sources=dict(estimate=STUDY+"#page=147", survey=STUDY+"#page=238", licences=LICENCES, hours=MARKET, parking=PARKING))
    version = package(root, "granville-visitors", lambda out: write_json(out / "visits.json", report))
    pointer(root / "granville-visitors" / (streets + "_" + bike + ".json"), {"version": version})
    print(version, count, len(routes), {s: (r["inbound"], r["outbound"]) for s, r in report["passages"].items()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--hotels", type=Path, default=Path("data/mobility/vancouver-hotels-2025.json"))
    args = parser.parse_args()
    publish(args.root, args.hotels)
