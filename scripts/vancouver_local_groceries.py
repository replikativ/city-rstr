"""Compare Canadian food access observations and walkable alternatives to home-based grocery drives."""
import argparse
import json
from bisect import bisect_right
from pathlib import Path
import tempfile

import numpy as np
from scipy.sparse.csgraph import dijkstra
import duckdb

from scripts.vancouver_atlas import write_json
from scripts.vancouver_census_geography import compare, digest, records, publish as publish_boundary
from scripts.vancouver_cityday import xy
from scripts.vancouver_market import grocery_draw, publish_market, read, windows
from scripts.vancouver_streets import walk_graph

# City of Vancouver, Equitable Access to Healthy Food Retail, Appendix C.
PACE = 3870 / 60
MINUTES = 15
RADII = [1000, 3000]


def observations(replay_ids, canfed, geographic):
    ids, points, boundary = compare(replay_ids, geographic, "5915022")
    selected = set(ids)
    classes = {}
    for limit in RADII:
        rows = {}
        for r in records(canfed, f"canfed_public_data/dens_thresholds_{limit//1000}km.csv"):
            da = r["DAuid"]
            if da in selected:
                if da in rows:
                    raise ValueError(f"Duplicate Can-FED record for {da}")
                rows[da] = [int(r[k]) for k in ("cls_02_grocery_stores", "cls_03_superstores")]
                if any(x not in range(5) for x in rows[da]):
                    raise ValueError(f"Unknown grocery density class for {da}")
        classes[limit] = [rows.get(da) for da in ids]
    return ids, points, classes, boundary


def outings(adir, ddir, atlas, day, share):
    by_template = []
    for diary, template in zip(atlas["templates"], day["templates"], strict=True):
        by_template.append([w for w in windows(diary, template, "car-driver")
                            if all(template["slots"][k] == "home" for k in w[3:5])])
    possible = 0
    rows = []
    for d, da in enumerate(day["das"]):
        roster = read(adir/(da+".json"))["people"]
        shard = read(ddir/(da+".json"))
        if not len(shard["plans"]) == len(shard["home"]) == len(roster):
            raise ValueError(f"Day shard and roster disagree for {da}")
        for i, p in enumerate(roster[:atlas["das"][da]["private"]]):
            if not 4 <= p[0] <= 13:
                continue
            for slot, start, dwell, a, b, inward, back in by_template[p[-1]]:
                possible += 1
                if not grocery_draw(da, i+1, slot, share):
                    continue
                plan = shard["plans"][i]
                home = shard["home"][i]
                band = 4 if p[3] is None else bisect_right((30000, 60000, 100000), p[3])
                if not 0 <= home == plan[a] == plan[b]:
                    raise ValueError("Incomplete home-based driving tour")
                rows.append([d, i, slot, start, dwell, inward, back, home, plan[slot], band, p[-1]])
    return possible, rows


def venue_distances(graph, snap, points, ends, limit):
    """One search from a store serves all residents and census reference points."""
    nodes, offsets = ends
    for node, connector in zip(*snap(points, lowest_id_on_ties=True), strict=True):
        dist = dijkstra(graph, indices=node, limit=limit)
        yield connector + dist[nodes] + offsets


def score(graph, snap, centres, homes, occasions, stores, sites):
    points = np.vstack((centres, homes))
    ends = snap(points, lowest_id_on_ties=True)
    das = len(centres)
    counts = np.zeros((len(RADII), das), dtype=int)
    best = np.full(len(occasions), np.inf)
    winner = np.full(len(occasions), -1, dtype=int)
    start, dwell, inward, back = np.asarray([r[3:7] for r in occasions]).reshape(-1, 4).T
    open_ = (start >= 480) & (start + dwell <= 1200)
    budget = np.minimum(np.minimum(inward, back), MINUTES) * PACE
    def costs(dist, point):
        # A home and shop at exactly the same mapped point cannot establish a walk.
        return np.where(np.any(homes != point, axis=1) & (dist[das:] <= budget), dist[das:], np.inf)
    for j, dist in enumerate(venue_distances(graph, snap, [s["point"] for s in stores], ends, max(RADII))):
        for k, radius in enumerate(RADII):
            counts[k] += dist[:das] <= radius
        cost = costs(dist, stores[j]["point"])
        use = open_ & (cost < best - 1e-8)
        best[use], winner[use] = cost[use], j
    results = {}
    for s, dist in zip(sites, venue_distances(graph, snap, [s["point"] for s in sites], ends, max(RADII)), strict=True):
        cost = costs(dist, s["point"])
        matches = np.flatnonzero(cost < best - 1e-8)
        results[s["id"]] = dict(
            visits=[[int(i), round(cost[i], 2)] for i in matches],
            newDA=[np.flatnonzero((dist[:das] <= radius) & (counts[k] == 0)).tolist()
                   for k, radius in enumerate(RADII)])
    for r, w, metres in zip(occasions, winner, best, strict=True):
        r.extend([int(w), round(metres, 2) if np.isfinite(metres) else None])
    return counts.tolist(), results


def publish(root, canfed, geographic):
    ptr = read(root/"cityday/current.json")
    atlas_id, day_id = ptr["atlas"], ptr["version"]
    streets = read(root/"streets/current.json")["version"]
    cycling = read(root/"cycling"/(streets+".json"))["version"]
    tours = read(root/"cycle-tours"/("_".join([atlas_id, day_id, streets, cycling])+".json"))["version"]
    market_dir = root/"market"
    choices = read(market_dir/("choices-"+tours+"_"+streets+".json"))
    adir, ddir = root/"atlas"/atlas_id, root/"cityday"/day_id
    atlas, day, places = read(adir/"atlas.json"), read(ddir/"day.json"), read(ddir/"places.json")
    graph, snap = walk_graph(read(root/"streets"/streets/"network.json"))
    ids, points, observed, boundary = observations(day["das"], canfed, geographic)
    publish_boundary(root/"atlas", atlas_id, boundary)
    centres = [xy(*p) for p in points]
    geo = {da: day["areas"].index(area) for area, r in atlas["areas"].items() for da in r["das"]}
    with duckdb.connect() as db:
        db.execute("LOAD spatial")
        db.execute("create table areas (id integer, polygon geometry)")
        db.executemany("insert into areas values (?, ST_GeomFromGeoJSON(?))",
                       [(k, json.dumps(atlas["areas"][area]["geometry"])) for k, area in enumerate(day["areas"])])
        for da, point in zip(ids, points, strict=True):
            if da not in geo:
                result = db.execute("select min(id) from areas where ST_Covers(polygon, ST_Point(?,?))", point).fetchone()[0]
                geo[da] = result if result is not None else -1
    alternatives = {}
    # A whole outing already switched to cycling is ineligible for the walking alternative.
    cyclist = {(d, i, start): 2 if access else 1
               for d, i, _, _, _, legs, access in read(root/"cycle-tours"/tours/"tours.json")
               for start, _, _, _ in legs}
    for rule in ("fixed", "bc2010"):
        market = choices[rule]
        path = market_dir/"archive"/market/"market.json"
        if digest(path) != market:
            raise ValueError("Market catalogue and archive identifier disagree")
        catalog = read(path)
        versions = dict(atlas=atlas_id, day=day_id, streets=streets)
        if any(catalog[k] != v for k,v in versions.items()) or catalog["bicycle"]["tours"] != tours:
            raise ValueError("Market uses a different resident day")
        share = catalog.get("purchase", {}).get("driverShare", catalog["share"])
        total, rows = outings(adir, ddir, atlas, day, share)
        homes = np.asarray([places[r[7]][:2] for r in rows]).reshape(-1, 2)
        counts, sites = score(graph, snap, centres, homes, rows, catalog["stores"], catalog["sites"])
        local = []
        for d, i, slot, start, dwell, inward, back, home, old, band, tpl, winner, distance in rows:
            area = places[home][2]
            local.append([d, i, slot, start, dwell, winner, None if distance is None else round(2*distance/PACE, 3),
                          band, area, places[old][2] if old >= 0 else -1, area, inward, back, home, home, tpl,
                          "walk", "local", cyclist.get((d, i, start-inward), 0)])
        catalog["localWalk"] = dict(base=market, radii=RADII, speed=PACE, limit=MINUTES,
                                    canfed=digest(canfed), geography=digest(geographic), areas=day["areas"],
                                    homeArea=[geo[d] for d in ids], das=ids, boundary=boundary, observed=observed,
                                    counts=counts, possible=total, occasions=local, sites=sites)
        alternatives[rule] = publish_market(root, catalog)
        print(rule, total, len(rows), sum(r[5]>=0 for r in local), alternatives[rule], flush=True)
    with tempfile.TemporaryDirectory(dir=market_dir) as tmp:
        out = Path(tmp)/"choices.json"
        write_json(out, dict(tours=tours, streets=streets, bases={k: choices[k] for k in alternatives}, **alternatives))
        out.replace(market_dir/("choices-"+tours+"_"+streets+"_walk.json"))



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--canfed", type=Path, default=Path("data/mobility/canfed_2024.zip"))
    parser.add_argument("--geography", type=Path, default=Path("data/mobility/2021_92-151_X.zip"))
    args = parser.parse_args()
    publish(args.root, args.canfed, args.geography)
