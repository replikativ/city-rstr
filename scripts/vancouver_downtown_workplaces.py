"""Match the North Shore survey's downtown workplace share through feasible job swaps."""
import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from scripts.vancouver_atlas import write_json
from scripts.vancouver_bridge_traffic import IRONWORKERS, REGIONAL_BRIDGES, road_profile, screen_arcs
from scripts.vancouver_campus import access_routes
from scripts.vancouver_city_transit import DirectService
from scripts.vancouver_cityday import SPEED, xy
from scripts.vancouver_north_shore_demand import SURVEY, SURVEY_ARCHIVE, SURVEY_DIGEST
from scripts.vancouver_region import package, read
from scripts.vancouver_regional_workplaces import ROAD, publish_companions, variant_day
from scripts.vancouver_streets import access_graph, walk_graph
from scripts.vancouver_transit_commutes import BOARDING_MARGIN_SECONDS
from scripts.vancouver_transit_transfers import OneTransfer, walk_transfers

# Table 20. Usual workplaces in CBD/West End and the rest of Vancouver/UEL.
WORK_LOCATIONS = {
    "City of North Vancouver": (7770, 3300),
    "District of North Vancouver": (8000, 5750),
    "West Vancouver": (3160, 2560),
}
CORE = {"Downtown", "West End"}
TIMETABLE = "5688b19e3abeb58bd4a2"  # Sep 15, 2026, with passenger and transfer rules
SUPPORTED = ROAD | {"walk", "bike", "transit"}


@lru_cache(maxsize=12)
def bounded_distances(graph_key, origin, limit):
    return dijkstra(graph_key.graph, indices=origin, limit=limit)


class StreetTimes:
    def __init__(self, graph, nodes, access, connector, pivots=()):
        self.graph, self.nodes, self.access, self.connector = graph, nodes, access, connector
        reverse = graph.T.tocsr()
        self.via = [(dijkstra(reverse, indices=a)[nodes],
                     graph[a, b] + dijkstra(graph, indices=b)[nodes]) for a, b in pivots]

    def fits(self, a, b, minutes, speed=1):
        connectors = self.access[a] + self.access[b]
        budget = minutes * speed - connectors
        if budget < 0 or max(self.access[a], self.access[b]) > self.connector:
            return False
        if any(enter[a] + leave[b] <= budget for enter, leave in self.via):
            return True
        limit = 5 * (int(budget // 5) + 1)
        return bounded_distances(self, self.nodes[a], limit)[self.nodes[b]] <= budget


class Routes:
    def __init__(self, root, parents, places, candidates, timetable, *, destination_sites=None):
        self.points = np.asarray([p[:2] for p in places])
        street_dir = root/"streets"/parents["streets"]
        network = read(street_dir/"network.json")
        self.profile, self.routing = road_profile(root, parents["streets"], "highway1")
        graph, snap = access_graph(network, 2, 4, speeds=self.profile["kmh"])
        connectors = self.profile["connectorKmh"] * 1000 / 60
        nodes, approach = snap(self.points, lowest_id_on_ties=True)
        self.road_nodes, self.road_access = nodes, approach / connectors
        self.max_access = self.profile["connectorMetres"] / connectors
        bridges = [*REGIONAL_BRIDGES, IRONWORKERS]
        screens = screen_arcs(network, [{} for _ in bridges], bridges)
        # A legal path via any listed node gives a quick upper bound. The
        # bounded shortest-path query handles the remaining local pairs.
        urban, _ = snap([xy(lon, lat) for lon, lat in [
            (-123.118, 49.282), (-123.133, 49.282), (-123.099, 49.263),
            (-123.055, 49.282), (-123.162, 49.266), (-123.116, 49.2335),
        ]])
        self.pivots = list(screens) + [(int(n), int(n)) for n in urban]
        self.road = {None: StreetTimes(graph, nodes, self.road_access, self.max_access, self.pivots)}
        g, snap = walk_graph(network)
        indexes, offsets = snap(self.points, lowest_id_on_ties=True)
        self.walk = StreetTimes(g, indexes, offsets, 500)
        cycling = read(root/"cycling"/(parents["streets"]+".json"))["version"]
        bicycle = read(root/"cycling"/cycling/"network.json")
        g, snap = access_graph(bicycle, 8, 16)
        indexes, offsets = snap(self.points, lowest_id_on_ties=True)
        self.bike = StreetTimes(g, indexes, offsets, 500)
        service = DirectService(root/"transit"/timetable)
        self.transit_date = service.route_manifest["date"]
        kinds = {leg[0] for w in candidates for leg in w[6] if leg[2] == "transit"}
        sites = {w[4] for w in candidates} if destination_sites is None else set(destination_sites)
        access = access_routes(places, kinds | sites, service.stations, street_dir)
        self.transit_access = access
        margin = BOARDING_MARGIN_SECONDS
        self.direct_transit = service.latest_departure(access, margin)
        rules = read(root/"transit"/timetable/"transfers.json")["pairs"]
        self.transfer_transit = OneTransfer(service, access, walk_transfers(service, rules, street_dir/"network.json", margin), margin)

    def road_for(self, minute):
        hour = minute // 60 % 24
        service = self.profile["hourly"]
        if hour not in service["hours"]:
            return self.road[None]
        if hour not in self.road:
            column = service["hours"].index(hour)
            graph = self.road[None].graph.copy()
            for corridor in service["corridors"]:
                factor = corridor["factors"][column]
                if factor > 1:
                    for a, b in corridor["arcs"]:
                        graph[a, b] *= factor
            self.road[hour] = StreetTimes(graph, self.road_nodes, self.road_access, self.max_access, self.pivots)
        return self.road[hour]

    @lru_cache(maxsize=32768)
    def fits(self, a, b, duration, mode, start):
        if a == b:
            return True
        upper_speed = 2500 if mode in ROAD or mode == "transit" else SPEED[mode]
        if np.linalg.norm(self.points[a] - self.points[b]) > duration * upper_speed:
            return False
        if mode == "transit":
            if a not in self.transit_access or b not in self.transit_access:
                return False
            end = (start + duration) * 60
            ride = self.direct_transit(end, a, b)
            if ride and ride[0] >= start:
                return True
            ride = self.transfer_transit.latest(end, a, b)
            return bool(ride and ride[0] >= start)
        if mode in ROAD:
            return self.road_for(start).fits(a, b, duration)
        return (self.bike if mode == "bike" else self.walk).fits(a, b, duration, SPEED[mode])

    def feasible(self, worker, site):
        for anchor, duration, mode, start, from_work in worker[6]:
            a, b = (site, anchor) if from_work else (anchor, site)
            if not self.fits(a, b, duration, mode, start):
                return False
        return True


def eligible(row):
    return (row[3] == 0 and 1 <= (row[7] or 0) <= 10 and row[6] and
            all(anchor >= 0 and minutes > 0 and mode in SUPPORTED
                for anchor, minutes, mode, *_ in row[6]))


def allocate(workers, municipalities, areas, places, points, routes, seed=2023):
    is_core = [areas[place[2]] in CORE for place in places]
    north = [w for w in workers if w[2] > 0 and w[3] <= 0]
    before = Counter((w[2], is_core[w[4]]) for w in north)
    rng = np.random.default_rng(seed)
    part = defaultdict(list)
    for w in workers:
        if w[2] == 0 and eligible(w):
            part[w[7], is_core[w[4]]].append(w)
    options = {}
    for key, partner in part.items():
        anchors = [min(w[6], key=lambda leg: leg[1]*SPEED[leg[2]])[0] for w in partner]
        options[key] = partner, cKDTree(points[anchors])
    remaining, targets = Counter(), {}
    for home, name in enumerate(municipalities[1:], 1):
        downtown, outside = WORK_LOCATIONS[name]
        total = before[home, False] + before[home, True]
        target = (total * downtown + (downtown+outside)//2) // (downtown+outside)
        targets[home] = target
        remaining[home] = target - before[home, True]
    moves, used, pairs, by_mode = defaultdict(list), set(), [], Counter()
    offered = [w for w in north if eligible(w)]
    for index in rng.permutation(len(offered)):
        w = offered[index]
        d, person, group, _, old, slots, _, occ = w
        wants_core = remaining[group] > 0
        if not remaining[group] or wants_core == is_core[old] or (occ, wants_core) not in options:
            continue
        partners, tree = options[occ, wants_core]
        n = len(partners)
        nearby = np.atleast_1d(tree.query(points[old], k=min(n, 20))[1])
        farther = rng.choice(n, size=min(n, 12), replace=False)
        tried, unreachable = set(), set()
        for j in np.concatenate((nearby, farther)):
            if j in tried:
                continue
            tried.add(j)
            u = partners[j]
            ud, ui, _, _, new, uslots, _, _ = u
            if (ud, ui) in used or new in unreachable:
                continue
            if not routes.feasible(w, new):
                unreachable.add(new)
                continue
            if not routes.feasible(u, old):
                continue
            used.add((ud, ui))
            remaining[group] += -1 if wants_core else 1
            moves[d].append([person, slots, old, new])
            moves[ud].append([ui, uslots, new, old])
            pairs.append((w, u))
            by_mode[next((leg[2] for leg in w[6] if not leg[4]), w[6][0][2])] += 1
            break
    results = [dict(home=name, survey=WORK_LOCATIONS[name], before=before[k, True], target=targets[k],
                    after=targets[k]-remaining[k], total=before[k, True]+before[k, False])
               for k, name in enumerate(municipalities[1:], 1)]
    return results, moves, pairs, dict(by_mode)


def publish(root, workplace_run, survey, timetable):
    with survey.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != SURVEY_DIGEST:
            raise ValueError("The survey archive differs from the Table 20 reference")
    base = read(root/"regional-workplaces"/workplace_run/"report.json")
    parents = dict(base["versions"], day=base["day"])
    day_dir, roster = root/"cityday"/parents["day"], root/"atlas"/parents["atlas"]
    day, places = read(day_dir/"day.json"), read(day_dir/"places.json")
    with tempfile.TemporaryDirectory() as directory:
        manifest = Path(directory)/"workers.json"
        subprocess.run(["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.regional-workplaces",
                        roster, day_dir, manifest, "swaps"], check=True)
        extracted = read(manifest)
    workers, municipalities = extracted["workers"], extracted["municipalities"]
    print(f"Finding feasible workplace exchanges for {len(workers):,} scheduled workers.", flush=True)
    candidates = [w for w in workers if eligible(w)]
    routes = Routes(root, parents, places, candidates, timetable)
    rows, moves, pairs, modes = allocate(workers, municipalities, day["areas"], places, routes.points, routes)
    exchanges = {(x[0], x[1]): y[4] for pair in pairs for x, y in (pair, pair[::-1])}
    if (len(exchanges) != 2*len(pairs) or
            Counter((w[4], w[7]) for w in workers) != Counter(
                (exchanges.get((w[0], w[1]), w[4]), w[7]) for w in workers)):
        raise ValueError("Workplace exchanges changed the number of scheduled jobs per site or occupation")
    for w, u in pairs:
        if not routes.feasible(w, u[4]) or not routes.feasible(u, w[4]):
            raise ValueError("An exchanged job cannot be reached in its recorded time budget")
    print(rows, modes, flush=True)
    if not pairs:
        raise ValueError("The surveyed targets admit no feasible workplace exchanges")
    version = package(root, "cityday", lambda out: variant_day(day_dir, day, places, moves, roster, out), parents["day"])
    example = min(pairs, key=lambda pair: (abs(pair[0][6][0][3]-480), pair[0][:2]))[0]
    summary = dict(versions=parents, day=version, incomingDay=base["versions"]["day"],
                   basisLabels={"original": "Municipal fit", "census": "Downtown workplace fit"},
                   rows=rows, swaps=len(pairs), modes=modes, source=SURVEY, sourceDigest=SURVEY_DIGEST,
                   originWorkplaceRun=workplace_run, timetable=timetable, serviceDate=routes.transit_date,
                   speedDigest=routes.routing["profileDigest"],
                   example=[day["das"][example[0]], example[1], example[6][0][3]+example[6][0][1]])
    release = package(root, "regional-workplaces", lambda out: write_json(out/"report.json", summary))
    print(f"Downtown workplace report {release}, weekday {version}, {len(pairs):,} exchanges.", flush=True)
    return summary, release


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("../Simulations/city"))
    parser.add_argument("--inputs", type=Path, default=Path("data/region"))
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--workplace-run", default="5bea5bc3322eb2bbae9f")
    parser.add_argument("--survey", type=Path, default=SURVEY_ARCHIVE)
    parser.add_argument("--timetable", default=TIMETABLE)
    parser.add_argument("--resume", help="Build the replay data for an existing downtown workplace report")
    args = parser.parse_args()
    if args.resume:
        release = args.resume
        summary = read(args.region/"regional-workplaces"/release/"report.json")
    else:
        summary, release = publish(args.region, args.workplace_run, args.survey, args.timetable)
    from scripts.vancouver_commute_schedule import TABLE as COMMUTE_TABLE, publish as commute_schedule
    commute_schedule(args.region, COMMUTE_TABLE, [summary["day"]])
    publish_companions(args.region, args.archive, args.inputs, summary, release, timed_roads=True)
