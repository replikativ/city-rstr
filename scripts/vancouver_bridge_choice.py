"""Compare faster and feasible alternative bridge routes for the same resident drives."""
import argparse
from pathlib import Path

import numpy as np
from scipy.sparse.csgraph import dijkstra

from scripts.vancouver_atlas import write_json
from scripts.vancouver_bridge_traffic import (
    IRONWORKERS, REGIONAL_BRIDGES, resident_legs, road_profile, screen_arcs,
)
from scripts.vancouver_flexible_transit import WORKPLACE_RUN
from scripts.vancouver_north_shore_demand import SURVEY_2025, SURVEY_2025_ARCHIVE, SURVEY_2025_DIGEST, verify_survey
from scripts.vancouver_region import NAMES, package, read
from scripts.vancouver_streets import access_graph
from scripts.vancouver_transit_commutes import pointer

BRIDGES = (*REGIONAL_BRIDGES, IRONWORKERS)
GROUPS = ("Downtown or West End", "Rest of Vancouver or UBC", "Burnaby or New Westminster")
# Table 35, 2025. Shares of all person trips, including people riding buses and SeaBus.
SURVEY_SHARES = ((62, 17, 21), (48, 47, 5), (4, 95, 1))
SEED = 2035
CHOICE_SCALE = 3.0


def road_trees(graph, arcs):
    """Distances with both bridges removed, plus the cost of each southbound cut."""
    cut = graph.tolil()
    for a, b in arcs:
        cut[a, b] = 0
    cut = cut.tocsr()
    reverse = cut.T.tocsr()
    for (a, b), (bridge, direction, fraction) in arcs.items():
        if direction != 0:
            continue
        prefix, to_a = dijkstra(reverse, indices=a, return_predecessors=True)
        suffix, from_b = dijkstra(cut, indices=b, return_predecessors=True)
        yield bridge, a, b, fraction, float(graph[a, b]), prefix, suffix, to_a, from_b


def choices(starts, ends, duration, access, egress, trees):
    times = np.full((len(starts), len(BRIDGES)), np.inf)
    at_cut = np.zeros_like(times)
    via = np.full(times.shape, -1)
    for i, (bridge, _, _, fraction, edge, prefix, suffix, *_) in enumerate(trees):
        before = access + prefix[starts]
        cost = before + edge + suffix[ends] + egress
        better = (cost < times[:, bridge]) & (cost <= duration)
        times[better, bridge] = cost[better]
        at_cut[better, bridge] = before[better] + edge * fraction
        via[better, bridge] = i
    return times, at_cut, via


def follow_nodes(start, end, predecessor):
    nodes = [end]
    while nodes[-1] != start:
        before = int(predecessor[nodes[-1]])
        if before < 0:
            raise ValueError("A feasible bridge route lost its predecessor")
        nodes.append(before)
    return nodes[::-1]


def route(points, locations, leg, a, b, tree, access, egress):
    bridge, before, after, fraction, edge, prefix, suffix, to_a, from_b = tree
    head = follow_nodes(before, a, to_a)[::-1]
    tail = follow_nodes(after, b, from_b)
    costs = [0, *(access + prefix[a] - prefix[head]), *(access + prefix[a] + edge + suffix[tail])]
    minutes = float(costs[-1] + egress)
    line = [locations[leg[1]], *(points[node] for node in head + tail), locations[leg[2]]]
    cut_minute = float(leg[3] + leg[4] * (access + prefix[a] + edge * fraction) / minutes)
    return dict(bridge=bridge, minute=cut_minute, minutes=minutes, path=line,
                offsets=[float(n) for n in (*costs, minutes)])


def evaluate(legs, groups, places, network, profile, das):
    screens = [{} for _ in BRIDGES]
    arcs = screen_arcs(network, screens, BRIDGES)
    points = network["nodes"]
    locations = [p[:2] for p in places]
    free_flow, snap = access_graph(network, 2, 4, speeds=profile["kmh"])
    nodes, offsets = snap(locations, lowest_id_on_ties=True)
    reachable = (offsets[legs[:, 1]] <= profile["connectorMetres"]) & (offsets[legs[:, 2]] <= profile["connectorMetres"])
    starts, ends = nodes[legs[:, 1]], nodes[legs[:, 2]]
    offsets /= profile["connectorKmh"] * 1000 / 60
    access, egress = offsets[legs[:, 1]], offsets[legs[:, 2]]
    trips = legs[:, 3]
    rng = np.random.default_rng(SEED)
    draw = rng.random(len(legs))
    by_hour = np.zeros((len(GROUPS), len(BRIDGES), 24, 3), dtype=int)
    example = None
    # Prefer morning examples that move a vehicle toward the undercounted crossing.
    example_rank = None
    fit = np.zeros(len(legs), dtype=bool)
    dual = fit.copy()
    hour = (trips // 60) % 24
    timing = profile["hourly"]
    for column, h in enumerate([*timing["hours"], None]):
        included = hour == h if h is not None else ~np.isin(hour, timing["hours"])
        idx = np.flatnonzero(included & reachable)
        if not len(idx):
            continue
        if h is not None:
            slowdowns = {tuple(arc): corridor["factors"][column]
                         for corridor in timing["corridors"] for arc in corridor["arcs"]}
            graph, _ = access_graph(network, 2, 4, speeds=profile["kmh"], slowdowns=slowdowns)
        else:
            graph = free_flow
        trees = list(road_trees(graph, arcs))
        times, at_cut, via = choices(starts[idx], ends[idx], legs[idx, 4], access[idx], egress[idx], trees)
        possible = via >= 0
        fastest = times.argmin(axis=1)
        rows = np.arange(len(idx))
        alternate = 1-fastest
        has_route = possible.any(axis=1)
        both = possible.all(axis=1)
        fit[idx], dual[idx] = has_route, both
        delta = times[rows[both], alternate[both]] - times[rows[both], fastest[both]]
        switched = np.zeros(len(idx), dtype=bool)
        switched[both] = draw[idx[both]] < 1 / (1 + np.exp(delta / CHOICE_SCALE))
        selected = np.where(switched, alternate, fastest)
        for b in range(len(BRIDGES)):
            eligible = possible[:, b]
            source = rows[eligible]
            minute = trips[idx[eligible]] + legs[idx[eligible], 4] * at_cut[source, b] / times[source, b]
            crossing_hour = (minute // 60).astype(int) % 24
            groups_at_cut = groups[idx[eligible]]
            for k, mask in enumerate((fastest[eligible] == b, selected[eligible] == b, np.ones(len(source), dtype=bool))):
                np.add.at(by_hour[:, b, :, k], (groups_at_cut[mask], crossing_hour[mask]), 1)
            moved_here = switched[eligible] & (selected[eligible] == b)
            for j, m in zip(source[moved_here], minute[moved_here], strict=True):
                n = idx[j]
                rank = (b != 1, abs(m - 480), legs[n, 5], legs[n, 6])
                if example_rank is not None and rank >= example_rank:
                    continue
                example_rank = rank
                example = dict(da=das[legs[n, 5]], person=int(legs[n, 6]), start=int(trips[n]),
                               duration=int(legs[n, 4]), group=GROUPS[groups[n]], routes=[
                    route(points, locations, legs[n], starts[n], ends[n], trees[via[j, chosen]], access[n], egress[n])
                    for chosen in (fastest[j], b)])
        print("Departures", h if h is not None else "other hours", len(idx),
              "fitting", int(has_route.sum()), "either bridge", int(both.sum()), flush=True)
    if not (by_hour[..., 0].sum() == by_hour[..., 1].sum() == fit.sum()
            and by_hour[..., 2].sum() == fit.sum() + dual.sum()):
        raise ValueError("Bridge alternatives lost or duplicated a driving leg")
    return dict(eligible=len(legs), reachable=int(reachable.sum()), fit=int(fit.sum()), dual=int(dual.sum()),
                counts=by_hour.tolist(), example=example)


def publish(root, workplace, survey):
    verify_survey(survey, SURVEY_2025_DIGEST)
    parent = read(root / "regional-workplaces" / workplace / "report.json")
    versions = {**parent["versions"], "day": parent["day"]}
    atlas = read(root / "atlas" / versions["atlas"] / "atlas.json")
    week = root / "cityday" / versions["day"]
    day, places = read(week / "day.json"), read(week / "places.json")
    if not {"Burnaby", "New Westminster"}.issubset(day["areas"]):
        raise ValueError("The bridge comparison needs the expanded eastern workplace inventory")
    north = set(NAMES.values())
    south = {i: (0 if name in ("Downtown", "West End") else 2 if name in ("Burnaby", "New Westminster") else 1)
             for i, name in enumerate(day["areas"]) if name not in north}
    homes = {da for name in north for da in atlas["areas"][name]["das"]}
    residential = np.asarray([da in homes for da in day["das"]])
    groups = np.asarray([south.get(p[2], -1) for p in places])
    north_place = np.asarray([p[2] >= 0 and day["areas"][p[2]] in north for p in places])
    all_legs = resident_legs(root, versions)
    _, origin, dest, _, _, da, _ = all_legs.T
    include = (origin >= 0) & (dest >= 0) & residential[da] & north_place[origin] & (groups[dest] >= 0)
    legs = all_legs[include]
    profile, routing = road_profile(root, versions["streets"], "highway1")
    network = read(root / "streets" / versions["streets"] / "network.json")
    result = evaluate(legs, groups[legs[:, 2]], places, network, profile, day["das"])
    report = dict(versions=versions, workplaceRun=workplace, routing=routing, groups=GROUPS,
                  bridges=[b[1] for b in BRIDGES], survey=SURVEY_2025, surveyDigest=SURVEY_2025_DIGEST,
                  surveyShares=SURVEY_SHARES, scale=CHOICE_SCALE, seed=SEED, **result)
    release = package(root, "bridge-choice", lambda out: write_json(out / "report.json", report))
    key = "_".join(versions[k] for k in ("atlas", "day", "streets"))
    pointer(root / "bridge-choice" / (key + ".json"), {"version": release})
    print(release, {key: report[key] for key in ("eligible", "reachable", "fit", "dual")}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--workplace-run", default=WORKPLACE_RUN)
    parser.add_argument("--survey", type=Path, default=SURVEY_2025_ARCHIVE)
    args = parser.parse_args()
    publish(args.region, args.workplace_run, args.survey)
