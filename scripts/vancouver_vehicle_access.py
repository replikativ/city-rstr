"""Test complete driver tours after assigning household vehicle access by income."""
import argparse
from collections import Counter, defaultdict
import hashlib
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from scipy.sparse.csgraph import dijkstra

from scripts.vancouver_atlas import write_json
from scripts.vancouver_city_transit import DirectService
from scripts.vancouver_commuter_coverage import passenger_walks
from scripts.vancouver_cycle_tours import SPEED as BIKE_METRES_PER_MINUTE
from scripts.vancouver_cycling import FORWARD, REVERSE
from scripts.vancouver_income_travel import BANDS, MODES, SOURCE, roster_bands
from scripts.vancouver_mobility import PRIORITY, REPORT
from scripts.vancouver_region import package, read
from scripts.vancouver_streets import access_graph
from scripts.vancouver_street_scenarios import VEHICLE_ACCESS, publish_index
from scripts.vancouver_transit_commutes import BOARDING_MARGIN_SECONDS, pointer
from scripts.vancouver_transit_load import ANNUAL_TABLE, TABLE, BusSpaces, bus_capacity_profile, bus_load_evidence, ride_legs
from scripts.vancouver_vehicle_traffic import project
from scripts.vancouver_work_transit import choose, fits, schedule_choices, transfer_inputs

CAR_ACCESS = (52, 67, 76, 82, 82, 91)  # Figure 25, adults in households with a vehicle.
WALK_METRES_PER_MINUTE = 80
SEED = 20261122


def household_access(rosters):
    people, incomes, groups = [], [], defaultdict(list)
    for d, roster in enumerate(rosters):
        bands = roster_bands(roster)
        incomes.append(bands)
        people.append([0] * len(bands))
        for start, size, _ in roster["homes"]:
            band = bands[start]
            adults = sum(2 if p[0] == 3 else 5 if 4 <= p[0] <= 13 else 0 for p in roster["people"][start:start+size])
            if band < len(BANDS) and adults:
                groups[band].append((d, start, size, adults))
    coverage = []
    for band, percent in enumerate(CAR_ACCESS):
        homes = groups[band]
        rng = np.random.default_rng([SEED, band])
        order = rng.permutation(len(homes))
        cum = np.r_[0, np.cumsum([homes[i][3] for i in order], dtype=np.int64)]
        count = int(np.argmin(abs(cum*100 - cum[-1]*percent)))
        for j, index in enumerate(order):
            d, start, size, _ = homes[index]
            people[d][start:start+size] = [2 if j < count else 1] * size
        coverage.append(dict(adults=cum[-1].item()/5, withVehicle=cum[count].item()/5,
                             households=len(homes), householdsWithVehicle=count, observed=percent))
    return people, incomes, coverage


def active_paths(tours, places, network, speed, forward, reverse):
    graph, snap = access_graph(network, forward, reverse)
    coords = np.asarray([row[:2] for row in places])
    pairs = defaultdict(dict)
    for _, _, _, legs in tours:
        for _, duration, a, b in legs:
            limit = duration*speed
            if np.linalg.norm(coords[a]-coords[b]) <= limit:
                pairs[a][b] = max(limit, pairs[a].get(b, 0))
    if not pairs:
        return {}
    ids = sorted(set(pairs) | {b for options in pairs.values() for b in options})
    nearest, offsets = snap(coords[ids], lowest_id_on_ties=True)
    endpoints = dict(zip(ids, zip(nearest, offsets)))
    roots = defaultdict(list)
    for a, options in pairs.items():
        source, access = endpoints[a]
        for b, limit in options.items():
            dest, egress = endpoints[b]
            if limit >= access + egress:
                roots[source].append((a, b, dest, access, egress, limit))
    paths = {}
    for source, requests in roots.items():
        distance, previous = dijkstra(graph, indices=source, limit=max(r[-1]-r[3]-r[4] for r in requests),
                                      return_predecessors=True)
        for a, b, dest, access, egress, limit in requests:
            metres = access + distance[dest] + egress
            if metres > limit:
                continue
            nodes = [dest]
            while nodes[-1] != source:
                nodes.append(previous[nodes[-1]])
            points = [places[a][:2], *(network["nodes"][i] for i in reversed(nodes)), places[b][:2]]
            paths[a, b] = metres, [p for i, p in enumerate(points) if i == 0 or p != points[i-1]]
    return paths


def active_leg(leg, paths, speed, mode):
    start, duration, a, b = leg
    metres, path = paths.get((a, b), (np.inf, None))
    return [start, duration, a, b, mode, path] if metres <= duration*speed and len(path) > 1 else None


def transit_tours(tours, choices, planner, service, access, spaces):
    direct = service.latest_departure(access, BOARDING_MARGIN_SECONDS, spaces.available)
    bounded = lambda deadline, a, b: planner.latest(deadline, a, b, spaces.available)
    outcomes = []
    # Earlier completed tours claim space first. Hashing this order avoids ties by neighbourhood.
    for d, i, weight, legs, walks in sorted(tours, key=lambda x: (x[3][-1][0] + x[3][-1][1],
            hashlib.blake2b(f"{x[0]}/{x[1]}/{x[3][0][0]}".encode(), digest_size=8).digest(), x[0], x[1])):
        plans = []
        for leg, walk in zip(legs, walks, strict=True):
            if walk:
                plans.append(walk)
                continue
            start, duration, a, b = leg
            option = choices.get((start, start+duration, a, b))
            if option is None:
                break
            if not spaces.fits(option[2]):
                option = choose(direct, bounded, start, start+duration, a, b)
                if not fits(option, start):
                    break
            plans.append([*leg, "transit", option[2]])
        if len(plans) == len(legs):
            for plan in plans:
                if plan[4] == "transit":
                    spaces.reserve(plan[5])
            outcomes.append((d, i, weight, plans))
    return outcomes


def driver_demand(extracted, incomes, replacements):
    """Count unweighted driver trips in households drawn without a vehicle."""
    closed = Counter()
    switched = Counter()
    for d, i, _, legs in extracted["tours"]:
        closed[incomes[d][i]] += len(legs)
    for d, i in replacements:
        switched[incomes[d][i]] += 1
    by_band = extracted["driverByIncome"]
    if sum(by_band) != extracted["driverTrips"] or any(
        not 0 <= switched[band] <= closed[band] <= total for band, total in enumerate(by_band)
    ):
        raise ValueError("Driver demand in households without a vehicle did not reconcile")
    return [dict(outsideClosedTours=total-closed[band], unmatchedInClosedTours=closed[band]-switched[band],
                 switched=switched[band]) for band, total in enumerate(by_band)]


def publish(root, archive, joint_id):
    joint = read(root / "joint-weekday" / joint_id / "report.json")
    versions = dict(joint["versions"], transit=joint["transit"])
    atlas_id, day_id, street_id = (versions[k] for k in ("atlas", "day", "streets"))
    atlas, day_dir = root / "atlas" / atlas_id, root / "cityday" / day_id
    day, places = (read(day_dir / name) for name in ("day.json", "places.json"))
    das = day["das"]
    streets = root / "streets" / street_id
    bike_id = read(root / "cycling" / (street_id + ".json"))["version"]
    bike_dir = root / "cycling" / bike_id
    access_id = read(root / "cycle-tours" / ("_".join((atlas_id, day_id, street_id, bike_id)) + ".json"))["version"]
    access_dir = root / "cycle-tours" / access_id
    flags = (access_dir / "access.bin").read_bytes()
    offsets = read(access_dir / "report.json")["offsets"]
    vehicle, incomes, coverage = household_access(read(atlas / (da+".json")) for da in das)
    if list(np.cumsum([0, *map(len, vehicle[:-1])])) != offsets or len(flags) != sum(map(len, vehicle)):
        raise ValueError("The bicycle and vehicle assignments have different rosters")
    print("Assigned household vehicle access", coverage, flush=True)
    with tempfile.TemporaryDirectory(dir=root / "joint-weekday") as directory:
        folder = Path(directory)
        access_path, bands_path, inputs, output = (folder / name for name in
                                                   ("vehicle.json", "bands.json", "input.json", "trips.json"))
        write_json(access_path, vehicle)
        write_json(bands_path, incomes)
        works = joint["workplaces"]
        write_json(inputs, dict(joint["versions"], outbound=works["outbound"], worksites=works["worksites"],
                                tracts=works["tract-workplaces"], outings=joint["outings"], priority=PRIORITY,
                                surveyModes=REPORT, vehicleAccess=str(access_path), incomeBands=str(bands_path),
                                incomeModes=MODES, knownBands=BANDS))
        subprocess.run(["node", "scripts/vancouver_joint_trips.mjs", root, inputs, output], check=True)
        extracted = read(output)["vehicle"]
    tours = extracted["tours"]
    print(f"Found {len(tours):,} closed driver tours with no household vehicle", flush=True)
    walk_net = read(streets / "network.json")
    walks = active_paths(tours, places, walk_net, WALK_METRES_PER_MINUTE, 1, 1)
    remaining, accepted = [], []
    for d, i, weight, legs in tours:
        walking = [active_leg(leg, walks, WALK_METRES_PER_MINUTE, "walk") for leg in legs]
        if all(walking):
            accepted.append((d, i, weight, walking))
        else:
            remaining.append((d, i, weight, legs, walking))
    bikes = active_paths((row[:4] for row in remaining if flags[offsets[row[0]]+row[1]] == 2),
                         places, read(bike_dir / "network.json"), BIKE_METRES_PER_MINUTE, FORWARD, REVERSE)
    pending = []
    for d, i, weight, legs, walking in remaining:
        cycling = [active_leg(leg, bikes, BIKE_METRES_PER_MINUTE, "bike") for leg in legs] if flags[offsets[d]+i] == 2 else []
        if cycling and all(cycling):
            accepted.append((d, i, weight, cycling))
        else:
            pending.append((d, i, weight, legs, walking))

    schedule = root / "transit" / joint["transit"]
    service = DirectService(schedule)
    observed = archive / "data/raw/probes" / TABLE
    profile = bus_capacity_profile(service.route_manifest, observed, observed.with_name(ANNUAL_TABLE))
    rider_dir = root / "transit-riders" / joint["riders"]
    base = [leg for da in read(rider_dir / "riders.json")["das"] for row in read(rider_dir / (da+".json"))
            for leg in ride_legs(row[6:])]
    spaces = BusSpaces(profile["limits"])
    spaces.preload(base)
    windows = {(s, s+n, a,b) for _,_,_,legs,walking in pending for (s,n,a,b),walk in zip(legs,walking,strict=True) if not walk}
    access, planner = transfer_inputs(windows, places, service, streets, schedule)
    choices = schedule_choices(windows, access, planner, service)
    accepted.extend(transit_tours(pending, choices, planner, service, access, spaces))
    print(f"Replaced {len(accepted):,} tours", flush=True)

    rides, by_da, counts, examples = [], defaultdict(list), Counter(), {}
    added = np.zeros((len(BANDS)+1, len(MODES)), dtype=np.int64)
    for d, i, weight, legs in sorted(accepted):
        for s, n, a, b, mode, payload in legs:
            row = [d, i, s, n, a, b, mode, payload]
            if mode == "transit":
                rides.append([das[d], i, s, n, a, b, *payload])
            by_da[das[d]].append(row)
            counts[mode] += 1
            added[incomes[d][i], MODES.index(REPORT[mode])] += weight
            added[incomes[d][i], MODES.index("Auto driver")] -= weight
            if mode not in examples or abs(s-480) < abs(examples[mode][2]-480):
                examples[mode] = row[:6]
    paths = passenger_walks(walk_net, service, places, rides)
    for da, rows in by_da.items():
        walks_by_trip = {(i,s): [a,b] for i,s,a,b in paths.get(da, ())}
        for row in rows:
            if row[6] == "transit":
                row.append(walks_by_trip[row[1],row[2]])
    before = bus_load_evidence(schedule, service.route_manifest, (), observed, profile["limits"], reserved=base)
    after = bus_load_evidence(schedule, service.route_manifest, rides, observed, profile["limits"], reserved=base)
    if before["above"] != after["above"] or not np.all(added.sum(axis=1) == 0):
        raise ValueError("Vehicle-access routing changed trip totals or introduced a bus overload")
    sample = {(d,i) for d,i,*_ in day["sample"]}
    stats = dict(candidateTours=len(tours), switchedTours=len(accepted), switchedTrips=sum(counts.values()),
                 assignedNoVehicleDriverTrips=extracted["driverTrips"], modes=dict(counts))
    demand = driver_demand(extracted, incomes, (row[:2] for rows in by_da.values() for row in rows))
    report = dict(joint=joint_id, versions=versions, bicycleAccess=access_id, seed=SEED, source=SOURCE, figure=25,
                  households=coverage, stats=stats, areas=sorted(by_da), modeDelta=(added/5).tolist(), examples=examples, driverDemand=demand,
                  bus=dict(before=before, after=after), walkMetresPerMinute=WALK_METRES_PER_MINUTE, cycleMetresPerMinute=BIKE_METRES_PER_MINUTE)

    def stage(folder):
        write_json(folder / "report.json", report)
        (folder / "access.bin").write_bytes(bytes(flag for area in vehicle for flag in area))
        write_json(folder / "sample.json", [row for rows in by_da.values() for row in rows if tuple(row[:2]) in sample])
        write_json(folder / "departures.json", [row[:3] for rows in by_da.values() for row in rows])
        for da, rows in by_da.items():
            write_json(folder / (da+".json"), rows)

    family = VEHICLE_ACCESS
    version = package(root, family, stage)
    publish_index(root, family, version)
    project(root, archive, version)
    pointer(root / family / (joint_id + ".json"), {"version": version})
    print(version, stats, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("joint")
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    args = parser.parse_args()
    publish(args.root, args.archive, args.joint)
