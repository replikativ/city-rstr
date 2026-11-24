"""Build a paired municipal weekday with census workplace-tract employment shares."""
import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile

import duckdb
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.sparse import eye, kron, vstack
from scipy.sparse.csgraph import dijkstra
from scipy.spatial.distance import cdist
from scipy.spatial import cKDTree

from scripts.vancouver_atlas import largest_remainder, write_json
from scripts.vancouver_cityday import SPEED, licensed_jobs, xy
from scripts.vancouver_cycling import FORWARD, REVERSE
from scripts.vancouver_inbound import read
from scripts.vancouver_region import package
from scripts.vancouver_streets import access_graph
from scripts.vancouver_survey_zones import geography
from scripts.vancouver_transit_commutes import pointer as publish_pointer
from scripts.vancouver_workplace_tracts import census_counts

SEED = 98100498
TRACT_COMMAND = ["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.tract-workplaces"]


def workplace_geography(data, archive, places, atlas):
    table = data / "98100498-eng.zip"
    tracts = data / "vancouver-tracts-2021.geojson"
    counts = census_counts(table)
    jobs = sorted(licensed_jobs(archive / "data/raw/vancouver-ods").items())
    indices = [i for i, p in enumerate(places) if p[3] == "Workplace"]
    rows = []
    for i, ((lon, lat), weight) in zip(indices, jobs, strict=True):
        if places[i][:2] != xy(lon, lat):
            raise ValueError("Licensed coordinates differ from the city release")
        if places[i][2] >= 0:
            rows.append((i, lon, lat, weight))
    points = pd.DataFrame(rows, columns=["i", "lon", "lat", "weight"])
    with duckdb.connect() as db:
        db.execute("load spatial")
        db.register("points", points)
        db.execute("""create temp table tracts as select DGUID as id,
            ST_Transform(geom, 'EPSG:4326', 'EPSG:26910', always_xy := true) as g from ST_Read(?)""", [str(tracts)])
        if {r[0] for r in db.execute("select id from tracts").fetchall()} != set(counts):
            raise ValueError("Workplace table and tract boundaries differ")
        db.execute("create temp table boundaries (geometry varchar)")
        das = read(atlas / "atlas.json")["das"]
        db.executemany("insert into boundaries values (?)",
                       [(json.dumps(read(atlas / (da + ".json"))["geometry"]),) for da in das])
        db.execute("""create temp table city as select ST_Union_Agg(ST_MakeValid(
            ST_Transform(ST_GeomFromGeoJSON(geometry::JSON), 'EPSG:4326', 'EPSG:26910', always_xy := true))) as g
            from boundaries""")
        covered = db.execute("""select t.id from tracts t join city c on ST_Intersects(t.g, c.g)
            where ST_Area(ST_Intersection(t.g, c.g)) >= 0.99 * ST_Area(t.g) order by t.id""").fetchnumpy()["id"]
        mapping = db.execute("""select i, first(id) from tracts t join
            (select i, ST_Transform(ST_Point(lon, lat), 'EPSG:4326', 'EPSG:26910', always_xy := true) g
             from points) p on ST_Covers(t.g, p.g) group by i having count(*)=1""").fetchall()
    observed = {k: counts[k] for k in covered if counts[k] is not None}
    supported = sorted(set(observed) & {tract for _, tract in mapping})
    index = {tract: i for i, tract in enumerate(supported)}
    site_tract = np.full(len(places), -1, dtype=int)
    for site, tract in mapping:
        site_tract[site] = index.get(tract, -1)
    weights = np.zeros(len(places))
    for site, _, _, weight in rows:
        weights[site] = weight
    provenance = dict(tableDigest=hashlib.sha256(table.read_bytes()).hexdigest(),
                      geometryDigest=hashlib.sha256(tracts.read_bytes()).hexdigest(),
                      unrepresentedTracts={k: n for k, n in observed.items() if k not in index},
                      suppressedTracts=[k for k in covered if counts[k] is None])
    return supported, np.array([observed[k] for k in supported]), site_tract, weights, provenance


def targets(weights, fixed, total):
    """Proportional integer quotas subject to the fixed workers already present."""
    target = np.array(fixed, dtype=int)
    free = np.ones(len(target), dtype=bool)
    while free.any():
        remaining = total - target[~free].sum()
        if not remaining:
            break
        if not weights[free].sum():
            if remaining != target[free].sum():
                raise ValueError("No employment evidence to distribute the remaining cohort")
            break
        quotas = largest_remainder(weights[free], remaining)
        short = quotas < target[free]
        if not short.any():
            target[free] = quotas
            break
        free[np.flatnonzero(free)[short]] = False
    if target.sum() != total or (target < fixed).any():
        raise ValueError("Infeasible workplace quotas")
    return target


def transfers(stock, target, centres):
    """Transport surplus to deficit tracts at minimum total between-centre distance."""
    donors = np.flatnonzero(stock > target)
    recipients = np.flatnonzero(target > stock)
    if not len(donors):
        return {}
    a, b = len(donors), len(recipients)
    constraints = vstack([kron(eye(a), np.ones((1, b))), kron(np.ones((1, a)), eye(b))])
    supply = stock[donors] - target[donors]
    demand = target[recipients] - stock[recipients]
    solution = linprog(cdist(centres[donors], centres[recipients]).ravel(), A_eq=constraints,
                       b_eq=np.r_[supply, demand], bounds=(0, None), method="highs")
    if not solution.success:
        raise ValueError(solution.message)
    flows = np.rint(solution.x.reshape(a, b)).astype(int)
    if not np.array_equal(flows.sum(axis=0), demand) or not np.array_equal(flows.sum(axis=1), supply):
        raise ValueError("Workplace flows do not conserve the tract margins")
    return {src: {dst: n for dst, n in zip(recipients, row) if n} for src, row in zip(donors, flows)}


def active_route_check(networks, coords):
    """Search from the job node, reversing the directed bike graph on trips to work."""
    graphs, snaps = {}, {}
    for mode, network in networks.items():
        bits = (1, 1) if mode == "walk" else (FORWARD, REVERSE)
        graph, snap = access_graph(network, *bits)
        graphs[mode] = (graph, graph.T.tocsr() if mode == "bike" else graph)
        snaps[mode] = snap(coords, lowest_id_on_ties=True)

    @lru_cache(maxsize=96)
    def from_job(mode, node, reverse, limit):
        return dijkstra(graphs[mode][reverse], indices=node, limit=limit)

    def reachable(jobs, routes):
        fits = np.ones(len(jobs), dtype=bool)
        searches = defaultdict(list)
        for i, (job, legs) in enumerate(zip(jobs, routes, strict=True)):
            for anchor, minutes, mode, from_work in legs:
                if mode not in graphs or (anchor == job or np.array_equal(coords[anchor], coords[job])):
                    continue
                nodes, offsets = snaps[mode]
                budget = minutes * SPEED[mode]
                if np.linalg.norm(coords[anchor] - coords[job]) > budget:
                    fits[i] = False
                    break
                allowed = budget - offsets[anchor] - offsets[job] + 1e-6
                if allowed < 0:
                    fits[i] = False
                    break
                key = mode, nodes[job], mode == "bike" and not from_work
                searches[key].append((i, nodes[anchor], allowed))
        for key, group in searches.items():
            live = [(i, endpoint, limit) for i, endpoint, limit in group if fits[i]]
            if live:
                # Nearby windows reuse a search radius while each rider retains their own distance limit.
                radius = 1000 * math.ceil(max(limit for _, _, limit in live) / 1000)
                dist = from_job(*key, radius)
                for i, endpoint, limit in live:
                    fits[i] &= dist[endpoint] <= limit
        return fits

    return reachable


def check_move_distances(coords, moves, *, active):
    checks = {}
    for legs, origin, destination in moves:
        for leg in legs:
            anchor, minutes, mode = leg[:3]
            if (not active and mode in ("walk", "bike")) or anchor < 0:
                raise ValueError("An active or unlocated work leg moved")
            old = np.linalg.norm(coords[origin] - coords[anchor])
            new = np.linalg.norm(coords[destination] - coords[anchor])
            budget = minutes * SPEED[mode]
            if new > max(budget, old) + 1e-6:
                raise ValueError("A workplace change exceeded the paired leg's distance limit")
            checks.setdefault(mode, Counter()).update(legs=1, before=int(old > budget), after=int(new > budget))
    return checks


def allocate(rows, places, tract_ids, observed, site_tract, weights, *, networks=None):
    rng = np.random.default_rng(SEED)
    workers = np.array([row[:5] for row in rows], dtype=int)
    coords = np.array([p[:2] for p in places])
    ids = site_tract[workers[:, 3]]
    covered = ids >= 0
    fixed = workers[:, 4].astype(bool)
    # Constraints are per individual leg. An already excessive distance cannot grow further.
    max_legs = max((len(row[5]) for row in rows), default=0)
    anchors = np.zeros((len(rows), max_legs), dtype=int)
    limits = np.full(anchors.shape, np.inf)
    active = [[] for _ in rows]
    for w, row in enumerate(rows):
        if fixed[w]:
            continue
        for j, leg in enumerate(row[5]):
            anchor, minutes, mode = leg[:3]
            if anchor < 0 or mode not in SPEED:
                fixed[w] = True
                break
            anchors[w, j] = anchor
            before = np.linalg.norm(coords[anchor] - coords[row[3]])
            limits[w, j] = max(before, minutes * SPEED[mode]) ** 2 + 1e-6
            if networks is not None and mode in networks:
                active[w].append(leg)
    n = len(tract_ids)
    stock = np.bincount(ids[covered], minlength=n)
    floor = np.bincount(ids[covered & fixed], minlength=n)
    target = targets(observed, floor, stock.sum())
    sites = [np.flatnonzero(site_tract == j) for j in range(n)]
    centres = np.array([np.average(coords[s], weights=weights[s], axis=0) for s in sites])
    excess = stock - target
    need = target - stock
    movable = [np.flatnonzero((ids == j) & ~fixed) for j in range(n)]
    after = ids.copy()
    assigned = workers[:, 3].copy()
    routed = None
    active_workers = [w for w in np.flatnonzero(covered & ~fixed) if active[w]]
    if networks is not None:
        routed = active_route_check(networks, coords)

    def check(available, draw, feasible):
        if routed is not None:
            tested = [i for i in np.flatnonzero(feasible) if active[available[i]]]
            feasible[tested] = routed(draw[tested], [active[available[i]] for i in tested])
        return feasible

    def propose(available, dst):
        home = coords[workers[available, 2]]
        initial = np.linalg.norm(coords[workers[available, 3]] - home, axis=1)
        candidates = sites[dst]
        prob = weights[candidates] / weights[candidates].sum()
        cost = np.full(len(available), np.inf)
        best = np.full(len(available), -1)
        locations = coords[anchors[available]]
        # Four licence-weighted draws per resident and tract allow multiple addresses
        # without constructing a citywide individual-by-workplace distance matrix.
        for _ in range(4):
            draw = rng.choice(candidates, size=len(available), p=prob)
            delta = coords[draw, None, :] - locations
            feasible = (np.sum(delta * delta, axis=2) <= limits[available]).all(axis=1)
            change = abs(np.linalg.norm(coords[draw] - home, axis=1) - initial)
            better = check(available, draw, feasible & (change < cost))
            best[better], cost[better] = draw[better], change[better]
        return best, cost

    def fill(src, dst, quota):
        pool = movable[src]
        available = pool[after[pool] == src]
        best, costs = propose(available, dst)
        eligible = np.flatnonzero(best >= 0)
        take = eligible[np.argsort(costs[eligible], kind="stable")[:quota]]
        after[available[take]] = dst
        assigned[available[take]] = best[take]
        excess[src] -= len(take)
        need[dst] -= len(take)

    # First use the minimum-distance transport between tracts. If a time constraint
    # prevents a transfer, try other surplus tracts in order of distance.
    for src, recipients in transfers(stock, target, centres).items():
        for dst, quota in recipients.items():
            fill(src, dst, quota)
    pending = sorted((np.linalg.norm(centres[src] - centres[dst]), src, dst)
                     for src in np.flatnonzero(excess > 0) for dst in np.flatnonzero(need > 0))
    for _, src, dst in pending:
        quota = min(excess[src], need[dst])
        if quota > 0:
            fill(src, dst, quota)
    routing = None
    if routed is not None:
        # Also recover short trips within a tract, without consuming its capacity for other workers.
        def reachable_workers(jobs):
            fits = routed(jobs[active_workers], [active[w] for w in active_workers])
            return {w for w, fit in zip(active_workers, fits, strict=True) if fit}

        print(f"Checking original routes for {len(active_workers):,} workers with active legs", flush=True)
        before = reachable_workers(workers[:, 3])
        improved = 0
        unresolved_by_tract = defaultdict(list)
        for w in active_workers:
            if w not in before and assigned[w] == workers[w, 3]:
                unresolved_by_tract[after[w]].append(w)
        for tract_index, choices in enumerate(sites):
            unresolved = np.asarray(unresolved_by_tract[tract_index], dtype=int)
            if not len(unresolved):
                continue
            first = [min(active[w], key=lambda leg: leg[1] * SPEED[leg[2]])[0] for w in unresolved]
            _, nearby = cKDTree(coords[choices]).query(coords[first], k=list(range(1, min(len(choices), 16) + 1)))
            nearby = choices[nearby]
            pending = np.ones(len(unresolved), dtype=bool)
            for column in nearby.T:
                if not pending.any():
                    break
                remaining, jobs = unresolved[pending], column[pending]
                delta = coords[jobs, None, :] - coords[anchors[remaining]]
                fits = check(remaining, jobs, (np.sum(delta * delta, axis=2) <= limits[remaining]).all(axis=1))
                assigned[remaining[fits]] = jobs[fits]
                improved += np.count_nonzero(fits)
                pending[pending] = ~fits
        print(f"Checking final active routes after {improved:,} workplace changes within tracts", flush=True)
        after_routed = reachable_workers(assigned)
        if not before <= after_routed:
            raise ValueError("A workplace move made a previously feasible active commute infeasible")
        routing = dict(workers=len(active_workers), before=len(before), after=len(after_routed), withinTract=int(improved))
    realized = np.bincount(after[covered], minlength=n)
    changed = np.flatnonzero(assigned != workers[:, 3])
    if np.any(fixed[changed]) or not np.array_equal(after, site_tract[assigned]):
        raise ValueError("Tract roster and assigned workplace addresses disagree")
    moves = np.column_stack((workers[changed, :2], workers[changed, 3], assigned[changed])).tolist()
    checks = check_move_distances(coords, ((rows[w][5], workers[w, 3], assigned[w]) for w in changed),
                                  active=networks is not None)
    result = dict(moves=moves, moved=len(moves), workers=len(rows), covered=int(covered.sum()),
                fixed=int(floor.sum()), seed=SEED, tracts=tract_ids, census=observed.tolist(),
                before=stock.tolist(), floor=floor.tolist(), target=target.tolist(), after=realized.tolist(),
                unfilled=int(np.maximum(target - realized, 0).sum()), distanceChecks=checks)
    if routing is not None:
        result.update(preserveDiaryModes=True, activeRoutes=routing, movedTract=int(np.count_nonzero(after != ids)))
    return result


def compile_workplaces(root, atlas, day, outbound, matched, solution, places, geography_path):
    geo = geography(geography_path, places)
    site_zones = {str(i): geo["zone"][i] for i, place in enumerate(places) if place[3] == "Workplace"}
    with tempfile.TemporaryDirectory() as tmp:
        result, zones = [Path(tmp) / name for name in ("solution.json", "geography.json")]
        write_json(result, {**solution, "siteZones": site_zones})
        write_json(zones, geo)

        def build(folder):
            subprocess.run([*TRACT_COMMAND, "evaluate", atlas, day, outbound, matched, result, folder / "worksites.json"], check=True)
            subprocess.run(["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.survey-zones",
                            atlas, day, outbound, folder, zones, folder / "zones.json"], check=True)

        return package(root, "tract-workplaces", build)


def publish(root, data, archive, pointer=None, *, preserve_modes=False):
    pointer = pointer or read(root / "cityday/current.json")
    atlas = root / "atlas" / pointer["atlas"]
    day = root / "cityday" / pointer["version"]
    outbound = root / "outbound" / read(root / "outbound" / (atlas.name + "_" + day.name + ".json"))["version"]
    matched = root / "worksites" / read(root / "worksites" / (outbound.name + ".json"))["version"]
    places = read(day / "places.json")
    with tempfile.TemporaryDirectory() as tmp:
        roster = Path(tmp) / "roster.json"
        method = ["diary"] if preserve_modes else []
        subprocess.run([*TRACT_COMMAND, "extract", atlas, day, outbound, matched, roster, *method], check=True)
        tracts, counts, mapping, weights, source = workplace_geography(data, archive, places, atlas)
        networks = None
        if preserve_modes:
            fit = read(outbound / "report.json")["neighbourhoodFit"]
            source.update(streets=fit["streets"], cycling=fit["cycling"])
            networks = {"walk": read(root / "streets" / source["streets"] / "network.json"),
                        "bike": read(root / "cycling" / source["cycling"] / "network.json")}
        solution = allocate(read(roster), places, tracts, counts, mapping, weights, networks=networks)
    version = compile_workplaces(root, atlas, day, outbound, matched, {**solution, **source}, places, data/"taz-gvrd.geojson")
    suffix = "_diary_modes.json" if preserve_modes else ".json"
    publish_pointer(root / "tract-workplaces" / (matched.name + suffix), dict(version=version))
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--data", type=Path, default=Path("data/mobility"))
    parser.add_argument("--fitted-atlas", help="Use the weekday locations for the given fitted atlas")
    parser.add_argument("--preserve-modes", action="store_true", help="Keep diary commute modes and check active routes")
    args = parser.parse_args()
    selected = None
    if args.fitted_atlas:
        versions = read(args.root / "diary-fit" / (args.fitted_atlas + ".json"))["locations"]
        if versions["atlas"] != args.fitted_atlas:
            raise ValueError("The workplace calibration requires the fitted atlas's own weekday")
        selected = dict(atlas=versions["atlas"], version=versions["day"])
    print(publish(args.root, args.data, args.archive, selected, preserve_modes=args.preserve_modes), flush=True)
