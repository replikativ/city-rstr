"""Fit additional North Shore shopping and recreation outings into existing weekdays."""
import argparse
from collections import Counter, defaultdict
import hashlib
import math
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from scripts.vancouver_atlas import write_json
from scripts.vancouver_bridge_traffic import road_profile
from scripts.vancouver_cityday import xy
from scripts.vancouver_north_shore_demand import NORTH_SHORE, SURVEY_MODES, SURVEY_ROWS, trip_inputs
from scripts.vancouver_region import package, read, rows
from scripts.vancouver_streets import access_graph, walk_graph

SHOPPING = "Shopping and personal errands"
RECREATION = "Recreation"
PURPOSES = (SHOPPING, RECREATION)
MODES = ("car-driver", "walk")
WALK_SPEED = 80  # metres per minute, as in the short-walk and market models
HOURS = {SHOPPING: (480, 1200), RECREATION: (420, 1260)}
SHOPPING_SHARES = {  # Table 7, household-maintenance/shopping and personal business
    "City of North Vancouver": (11.9, 5.6),
    "District of North Vancouver": (12.2, 6.7),
    "West Vancouver": (13.7, 7.1),
}
# Figure 14, driver and walking shares for shopping, personal business, and recreation.
SHARES = {SHOPPING: ([.74, .71], [.16, .12]), RECREATION: ([.54], [.32])}
SEED = 202323


def donor_tours(atlas, day):
    donors = defaultdict(list)
    for template, (diary, spatial) in enumerate(zip(atlas["templates"], day["templates"], strict=True)):
        parts, slots = spatial["parts"], spatial["slots"]
        trips, _ = trip_inputs(diary, spatial)
        purpose = {row[0]: trip[1] for row, trip in zip((p for p in parts if p[2] != "stop"), trips, strict=True)}
        for home, outbound, stop, inbound, end in zip(parts, parts[1:], parts[2:], parts[3:], parts[4:]):
            mode = outbound[2]
            if not (home[2] == end[2] == stop[2] == "stop" and slots[home[3]] == slots[end[3]] == "home"
                    and mode in MODES and inbound[2] == mode):
                continue
            purpose_of_trip = purpose[outbound[0]]
            if (purpose_of_trip, slots[stop[3]]) not in {
                    (SHOPPING, "store"), (RECREATION, "outdoors"), (RECREATION, "sports-venue")}:
                continue
            start, there = outbound[:2]
            arrival, back = inbound[:2]
            # Both diary legs must be single-mode. Keep the full observed dwell.
            if any(e[3] != mode for e in diary["episodes"]
                   if start <= e[0] < start + there or arrival <= e[0] < arrival + back):
                continue
            donors[purpose_of_trip, mode].append((template, start, there, stop[1], back))
    return donors


def local_venues(catalogue, places, areas):
    kinds = {"store": SHOPPING, "outdoors": RECREATION, "sports-venue": RECREATION}
    # A row can have more than one OSM role at a coordinate. Deduplicate by
    # purpose and keep the lowest existing place ID with a matching name.
    place_ids = {}
    for loc, (x, y, region, name) in enumerate(places):
        if region >= 0 and name and areas[region] in SURVEY_ROWS:
            place_ids.setdefault((x, y, name), loc)
    matched = defaultdict(set)
    for lon, lat, kind, label, *_ in rows(catalogue):
        if kind in kinds and label:
            loc = place_ids.get((*xy(lon, lat), label))
            if loc is not None:
                matched[kinds[kind]].add(loc)
    return {purpose: sorted(matched[purpose]) for purpose in PURPOSES}


def accessible_sites(homes, sites, coords, graph, snap, limit, connector, units_per_minute, radii=()):
    """Check both directions from the same address to the same nearby venue."""
    takes = list(homes)
    if not takes:
        return defaultdict(list)
    points = np.asarray(coords)
    nodes, access = snap(points, lowest_id_on_ties=True)
    # Try the nearest venues as well as destinations in different directions
    # for longer driving diaries. Check every resulting route in both directions.
    requests = defaultdict(list)
    angles = np.arange(8) * (math.pi / 4)
    bearings = np.column_stack((np.cos(angles), np.sin(angles)))
    for purpose, venue_ids in sites.items():
        tree = cKDTree(points[venue_ids])
        if not len(tree.data):
            raise ValueError("No matched venues for " + purpose)
        origins = points[takes]
        _, indices = tree.query(origins, k=min(8, len(venue_ids)))
        nearby = [indices.reshape(len(takes), -1)]
        for radius in radii:
            _, across = tree.query(origins[:, None, :] + radius * bearings)
            nearby.append(across)
        indexes = np.column_stack(nearby)
        for row, home in enumerate(takes):
            if access[home] > connector:
                continue
            for index in dict.fromkeys(indexes[row]):
                dest = venue_ids[index]
                if access[dest] <= connector and not np.array_equal(points[dest], points[home]):
                    requests[dest].append((home, purpose))
    result = defaultdict(list)
    reverse = graph.T.tocsr()
    for dest, candidates in sorted(requests.items()):
        at = int(nodes[dest])
        outward = dijkstra(reverse, indices=at, limit=limit)
        inward = dijkstra(graph, indices=at, limit=limit)
        for home, purpose in candidates:
            start = int(nodes[home])
            access_cost = access[home] + access[dest]
            go, back = outward[start] + access_cost, inward[start] + access_cost
            if max(go, back) <= limit:
                result[home, purpose].append((dest, max(1, math.ceil(go / units_per_minute)),
                                             max(1, math.ceil(back / units_per_minute))))
    return result


def mode_routes(root, streets, places, opportunities, venues, donors):
    graph_dir = root / "streets" / streets
    network = read(graph_dir / "network.json")
    points = np.array([p[:2] for p in places])
    walk, snap = walk_graph(network)
    homes = sorted({r[2] for r in opportunities})
    output = {"walk": accessible_sites(homes, venues, points, walk, snap,
                                      min(30, max(max(d[2], d[4]) for p in PURPOSES for d in donors[p, "walk"])) * WALK_SPEED,
                                      500, WALK_SPEED)}
    print("Checked outward and return walks to nearby shops and recreation sites.", flush=True)
    profile, provenance = road_profile(root, streets, "time")
    drive, snap_drive = access_graph(network, 2, 4, speeds=profile["kmh"])
    metres_per_minute = profile["connectorKmh"] * 1000 / 60

    def attachment(coords, **kwargs):
        node, metres = snap_drive(coords, **kwargs)
        return node, metres / metres_per_minute

    homes = sorted({r[2] for r in opportunities if r[-1]})
    output["car-driver"] = accessible_sites(homes, venues, points, drive, attachment, 25,
                                             profile["connectorMetres"] / metres_per_minute, 1, radii=(2000, 4000, 6000))
    print("Checked both directions on the free-flow road graph.", flush=True)
    return output, provenance


def target_tours(evidence):
    targets = {}
    for name in SURVEY_ROWS:
        city, observed = evidence["model"][name], evidence["observations"][name]
        for purpose in PURPOSES:
            parts = SHOPPING_SHARES[name] if purpose == SHOPPING else (1,)
            for mode, shares in zip(MODES, SHARES[purpose], strict=True):
                share = np.dot(parts, shares) / sum(parts)
                count = round(city["residents"] * observed["purposes"][purpose] * share / observed["residents"])
                baseline = city["purposeModes"][purpose][SURVEY_MODES[mode]]
                targets[name, purpose, mode] = [baseline, count]
    return targets


def time_slots(windows, there, duration, back, opening, closing):
    for a, b in windows:
        lo = max(a, opening - there)
        hi = min(b - there - duration - back, closing - there - duration)
        if lo <= hi:
            yield lo, hi


def place_outing(windows, network, diaries, purpose, rng, *, match_times=False):
    if not network:
        return None
    opening, closing = HOURS[purpose]
    for i in rng.permutation(len(diaries)):
        template, preferred, outbound, dwell, inbound = diaries[i]
        candidates = list(rng.permutation(len(network)))
        if match_times:
            candidates.sort(key=lambda j: abs(outbound - network[j][1]) + abs(inbound - network[j][2]))
        for j in candidates:
            site, there, back = network[j]
            if there > outbound or back > inbound:
                continue
            intervals = list(time_slots(windows, there, dwell, back, opening, closing))
            if intervals:
                lo, hi = min(intervals, key=lambda span: max(span[0] - preferred, preferred - span[1], 0))
                departure = lo if lo == hi else round(rng.triangular(lo, min(hi, max(lo, preferred)), hi))
                return site, departure, there, dwell, back, template
    return None


def available_windows(windows, blocks):
    for a, b in windows:
        cursor = a
        for start, end in blocks:
            if end <= cursor or start >= b:
                continue
            if cursor < start:
                yield cursor, start
            cursor = max(cursor, end)
        if cursor < b:
            yield cursor, b


def assign(opportunities, routes, donors, targets, reserved):
    rng = np.random.default_rng(SEED)
    totals = Counter()
    desired = {k: max(0, control - baseline) for k, (baseline, control) in targets.items()}
    remaining = desired.copy()
    candidates = opportunities["residents"]
    windows = opportunities["windows"]
    result = []
    for j in rng.permutation(len(candidates)):
        d, i, home, template, municipality, can_drive = candidates[j]
        offers = [(municipality, purpose, mode) for purpose in PURPOSES for mode in MODES
                  if (mode != "car-driver" or can_drive) and remaining[municipality, purpose, mode] > 0]
        offers.sort(key=lambda k: -remaining[k] / desired[k])
        free = list(available_windows(windows[template], reserved.get((d, i), ())))
        for key in offers:
            _, purpose, mode = key
            option = place_outing(free, routes[mode][home, purpose], donors[purpose, mode], purpose, rng,
                                  match_times=mode=="car-driver")
            if option:
                site, departure, there, dwell, back, donor = option
                result.append([d, i, home, site, purpose, mode, departure, there, dwell, back, donor])
                totals[key] += 1
                remaining[key] -= 1
                break
    return sorted(result), totals


def raster_clock(tours, places, occupancy, areas, scratch, backend):
    cols = len(areas) + 2
    changes = np.zeros((1441, cols), dtype=np.int32)
    schedules = []
    for _, _, home, site, _, _, start, there, dwell, back, *_ in tours:
        area, venue = places[home][2], places[site][2]
        a, b, c, end = start - 240, start - 240 + there, start - 240 + there + dwell, start - 240 + there + dwell + back
        seq = ((a, b, cols - 2), (b, c, venue), (c, end, cols - 2))
        if not (0 <= a < b < c < end <= 1440 and min(area, venue) >= 0):
            raise ValueError("Invalid outing time or address")
        schedules.append(tuple((x*cols+area, y*cols+area, z-area) for x, y, z in seq))
        changes[a:end, area] -= 1
        for x, y, z in seq:
            changes[x:y, z] += 1
    return verify_intervals(schedules, changes, occupancy, scratch, backend)


def verify_intervals(schedules, changes, occupancy, scratch, backend):
    cols = changes.shape[1]
    weights = Counter(schedules)
    groups = list(weights)
    index = {schedule: i for i, schedule in enumerate(groups)}
    parts = [part for group in groups for part in group]
    starts, ends, shifts = zip(*parts, strict=True)
    offsets = np.cumsum([0, *(len(group) for group in groups)])
    tables = {"starts": starts, "ends": ends, "shifts": shifts, "ranks": np.ones(len(groups)),
              "offsets": offsets, "group-sizes": list(weights.values()),
              "population": [index[schedule] for schedule in schedules]}
    for name, values in tables.items():
        np.asarray(values, dtype="<i4").tofile(scratch / (name + ".i32"))
    write_json(scratch / "shape.json", dict(zones=cols, steps=max(map(len, groups)), levels=[0, 1]))
    subprocess.run(["clojure", "-J--add-modules=jdk.incubator.vector", "-J--enable-native-access=ALL-UNNAMED",
                    "-M", "-m", "city.vancouver.occupancy-run", scratch, backend, "groups", "agents"], check=True)
    for fidelity in ("groups", "agents"):
        before, after = (np.fromfile(scratch / f"{fidelity}-{level}.i32", dtype="<i4").reshape(1441, cols)
                         for level in (0, 1))
        if not np.array_equal((after - before).cumsum(axis=0), changes):
            raise ValueError("Raster outing occupancy differs from enumerating individual schedules")
    fitted = np.asarray(occupancy) + changes[:-1]
    if np.any(fitted < 0) or np.any(changes.sum(axis=1)) or np.any(changes[-1]):
        raise ValueError("Outing occupancy does not conserve residents")
    return dict(backend=backend, agents=len(schedules), groups=len(groups), occupancyDelta=changes[:-1].tolist())


def read_opportunities(atlas, day_dir, scratch, *, detail=None, municipalities=SURVEY_ROWS, clock=None):
    inputs, output = scratch/"groups.json", scratch/"opportunities.json"
    write_json(inputs, list(municipalities))
    command = ["clojure", "-J-Xmx1g", "-M", "-m", "city.vancouver.outing-opportunities",
               atlas, day_dir, inputs, output]
    if detail or clock:
        command.append(detail or "")
    if clock:
        command.append(clock)
    subprocess.run(command, check=True)
    return read(output)


def reserved_walks(root, versions, evidence):
    day = versions["day"]
    reserved = defaultdict(list)
    gaps = root / "short-walks" / (day + "_" + versions["streets"] + ".json")
    if evidence.get("gapStreetRelease") != versions["streets"]:
        return reserved, None
    release = read(gaps)
    if any(release[k] != versions[k] for k in ("atlas", "day", "streets")):
        raise ValueError("The reserved reconstructed walks use a different weekday")
    for d, i, start, minutes, *_ in release["walks"]:
        reserved[d, i].append((start, start + minutes))
    return reserved, hashlib.sha256(gaps.read_bytes()).hexdigest()


def publish_outings(root, report, tours):
    versions = report["versions"]
    key = versions["atlas"] + "_" + versions["day"] + ".json"

    def build(out):
        write_json(out / "report.json", report)
        write_json(out / "tours.json", tours)

    version = package(root, "discretionary-outings", build)
    path = root / "discretionary-outings"
    with tempfile.TemporaryDirectory(dir=path) as tmp:
        pointer = Path(tmp) / "pointer"
        write_json(pointer, {"version": version})
        pointer.replace(path / key)
    print(version, len(tours), report["metrics"], flush=True)
    return version


def publish(root, day, catalogue, backend):
    versions = dict(read(root / "current.json"), day=day)
    da = root / "cityday" / day
    atlas = root / "atlas" / versions["atlas"]
    model, population = read(da / "day.json"), read(atlas / "atlas.json")
    places = read(da / "places.json")
    demand_key = versions["atlas"] + "_" + day + ".json"
    survey_root = root / "north-shore-demand"
    demand = read(survey_root / demand_key)["version"]
    evidence = read(survey_root / demand / "report.json")
    if (evidence["atlas"], evidence["day"]) != (versions["atlas"], day):
        raise ValueError("Demand evidence uses a different paired weekday")
    donors = donor_tours(population, model)
    targets = target_tours(evidence)
    venues = local_venues(catalogue, places, model["areas"])
    reserved, walk_digest = reserved_walks(root, versions, evidence)
    with tempfile.TemporaryDirectory(dir=root) as folder:
        scratch = Path(folder)
        opportunities = read_opportunities(atlas, da, scratch)
        print(f"Considering {len(opportunities['residents']):,} residents with discretionary time.", flush=True)
        routes, profile = mode_routes(root, versions["streets"], places, opportunities["residents"], venues, donors)
        tours, sums = assign(opportunities, routes, donors, targets, reserved)
        if not tours or len({tuple(t[:2]) for t in tours}) != len(tours):
            raise ValueError("The scenario must assign separate residents to feasible outings")
        clock = raster_clock(tours, places, model["occupancy"], model["areas"], scratch, backend)
    metrics = [[name, purpose, mode, *targets[name, purpose, mode], sums[name, purpose, mode]]
               for name in SURVEY_ROWS for purpose in PURPOSES for mode in MODES]
    support = [[p, mode, len(donors[p, mode])] for p in PURPOSES for mode in MODES]
    reference = evidence["model"][NORTH_SHORE]
    observed = evidence["observations"][NORTH_SHORE]
    with catalogue.open("rb") as stream:
        catalogue_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    report = dict(versions=versions, demand=demand, source=evidence["source"], sourceDigest=evidence["sourceDigest"],
                  seed=SEED, metrics=metrics, trips=reference["trips"], residents=reference["residents"],
                  surveyRate=observed["trips"] / observed["residents"],
                  attendance=len(tours), venues={k: len(v) for k, v in venues.items()}, donorTours=support,
                  venueDigest=catalogue_digest, roadProfile=profile, walkMetresPerMinute=WALK_SPEED,
                  hours=HOURS, **clock)
    if walk_digest:
        report["reservedWalksDigest"] = walk_digest
    return publish_outings(root, report, tours)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--day", default="14dfd26a0355cc5695ea")
    parser.add_argument("--catalogue", type=Path, default=Path("data/region/work/places.jsonl"))
    parser.add_argument("--backend", default="jvm")
    args = parser.parse_args()
    publish(args.region, args.day, args.catalogue, args.backend)
