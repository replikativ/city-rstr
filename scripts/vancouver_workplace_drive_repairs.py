"""Find same-tract workplace alternatives for driving legs that lost a feasible route."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_cityday import SPEED
from scripts.vancouver_region import package, read
from scripts.vancouver_tract_scenario import TRACT_COMMAND, active_route_check, check_move_distances, compile_workplaces, workplace_geography
from scripts.vancouver_transit_commutes import pointer
from scripts.vancouver_workplace_drives import road_profiles, score


ACTIVE = {"walk", "bike"}
DRIVING = {"car-driver", "car-passenger", "motorcycle"}


def fixed_work_legs(template, diary, plan, paid):
    """Return timed legs that can all be evaluated for a move of one workplace."""
    parts = template["parts"]
    if any(a[2] == b[2] == "stop" and (a[3] in paid) != (b[3] in paid)
           for a, b in zip(parts, [*parts[1:], parts[0]])):
        return None
    legs = []
    for start, duration, mode, a, b in parts:
        if mode == "stop" or (a in paid) == (b in paid):
            continue
        modes = {episode[3] for episode in diary["episodes"] if start <= episode[0] < start + duration}
        anchor = plan[b if a in paid else a]
        if anchor < 0 or mode not in ACTIVE | DRIVING or modes != {mode}:
            return None
        legs.append((start, duration, anchor, mode, a in paid))
    return legs


def publish(root, data, archive, tract_id):
    tract = read(root/"tract-workplaces"/tract_id/"worksites.json")
    driving = root/"workplace-drives"
    audit = read(driving/(tract_id+".json"))["version"]
    report = read(driving/audit/"report.json")
    regressions = read(driving/audit/"regressions.json")
    atlas_id, day_id, streets = (tract[k] for k in ("atlas", "day", "streets"))
    versions = dict(atlas=atlas_id, day=day_id, streets=streets, tracts=tract_id)
    if versions != report["versions"] or not tract.get("preserveDiaryModes"):
        raise ValueError("The driving losses use different workplace inputs")
    day_dir, atlas_dir = root/"cityday"/day_id, root/"atlas"/atlas_id
    day, places = read(day_dir/"day.json"), read(day_dir/"places.json")
    diaries = read(atlas_dir/"atlas.json")["templates"]
    paid = list(map(set, read(root/"outbound"/tract["outbound"]/"report.json")["slots"]))
    tracts, _, membership, _, geography = workplace_geography(data, archive, places, atlas_dir)
    if tracts != tract["tracts"] or any(geography[key] != tract[key] for key in ("tableDigest", "geometryDigest")):
        raise ValueError("The original and alternative workplaces use different tract boundaries")
    sites = [np.flatnonzero(membership == i) for i in range(len(tracts))]
    coords = np.asarray([place[:2] for place in places])
    streets_net = read(root/"streets"/streets/"network.json")
    bicycle_net = read(root/"cycling"/tract["cycling"]/"network.json")
    walk_or_bike = active_route_check({"walk": streets_net, "bike": bicycle_net}, coords)
    road, measured, source = road_profiles(root/"drive-profile", streets, report["traffic"])
    if source["profileDigest"] != report["profileDigest"] or source["baselineDigest"] != report["baselineDigest"]:
        raise ValueError("The published driving profile differs from the profile being repaired")
    existing = {(d, i, s): dest for d, i, s, _, dest in tract["changes"]}
    requested = defaultdict(lambda: defaultdict(list))
    for case in regressions:
        requested[case["da"]][case["index"]].append(case)
    alternatives, journeys, skipped = [], [], Counter()
    search_limit = 24

    for d, da in enumerate(day["das"]):
        if da not in requested:
            continue
        people = read(atlas_dir/(da+".json"))["people"]
        plans = read(day_dir/(da+".json"))["plans"]
        for i, cases in sorted(requested[da].items()):
            template = people[i][-1]
            plan, slots = plans[i], paid[template]
            original = {plan[s] for s in slots}
            current = {existing.get((d, i, s), plan[s]) for s in slots}
            if len(original) != 1 or len(current) != 1:
                skipped["severalWorkplaces"] += 1
                continue
            old, job = next(iter(original)), next(iter(current))
            tract_index = membership[job] if job >= 0 else -1
            if old < 0 or tract_index < 0:
                skipped["unmappedWorkplace"] += 1
                continue
            timed = fixed_work_legs(day["templates"][template], diaries[template], plan, slots)
            if not timed:
                skipped["otherOrUnresolvedModes"] += 1
                continue
            direct = {(s, n, from_job, anchor) for s, n, anchor, mode, from_job in timed if mode == "car-driver"}
            for case in cases:
                out = case["fromWork"]
                origin, destination = case["revised"]
                work, anchor = (origin, destination) if out else (destination, origin)
                if work != job or (case["start"], case["duration"], out, anchor) not in direct:
                    raise ValueError("A failed drive differs from the workplace and diary used to repair it")
            area_sites = sites[tract_index]
            order = np.linalg.norm(coords[area_sites] - coords[job], axis=1).argsort(kind="stable")
            chosen = [int(s) for s in area_sites[order] if s != job][:search_limit]
            anchors = np.asarray([a for _, _, a, _, _ in timed])
            prior = np.linalg.norm(coords[anchors] - coords[old], axis=1)
            limits = np.maximum(prior, [n * SPEED[mode] for _, n, _, mode, _ in timed])
            chosen = [s for s in chosen if np.all(np.linalg.norm(coords[anchors] - coords[s], axis=1) <= limits + 1e-6)]
            active = [(a, n, mode, from_job) for _, n, a, mode, from_job in timed if mode in ACTIVE]
            viable = walk_or_bike(chosen, [active] * len(chosen))
            road_legs = [(s, n, a, out) for s, n, a, mode, out in timed if mode in DRIVING]
            for candidate, ok in zip(chosen, viable, strict=True):
                if not ok:
                    continue
                first = len(journeys)
                for start, duration, anchor, out in road_legs:
                    a, b, c, e = (job, anchor, candidate, anchor) if out else (anchor, job, anchor, candidate)
                    journeys.append([d, i, start, duration, a, b, c, e, int(out)])
                alternatives.append((d, i, job, candidate, first, len(journeys), len(cases)))

    print(f"Checking {len(alternatives):,} alternative workplace addresses and {len(journeys):,} driving legs", flush=True)
    _, times, _, _ = score(journeys, places, streets_net, road, measured["hourly"])
    accepted = {}
    for d, i, job, site, start, end, lost in alternatives:
        if (d, i) not in accepted and np.isfinite(times[start:end, 2]).all():
            accepted[d, i] = dict(da=day["das"][d], index=i, current=job, replacement=site,
                                   repaired=lost, roadMinutes=np.round(times[start:end, 2], 4).tolist())
    changes = list(accepted.values())
    workers = sum(len(rows) for rows in requested.values())
    result = dict(versions=versions, roadAudit=audit, sourceTrips=len(regressions), workers=workers,
                  eligible=workers-sum(skipped.values()), candidateLimit=search_limit, skipped=dict(skipped),
                  repairedWorkers=len(changes), repairedTrips=sum(change["repaired"] for change in changes),
                  changes=changes)
    family = "workplace-drive-repairs"
    release = package(root, family, lambda out: write_json(out/"report.json", result))
    pointer(root/family/(tract_id+".json"), {"version": release})
    print(release, {k: v for k, v in result.items() if k != "changes"}, flush=True)
    return release


def apply_repairs(root, data, archive, tract_id):
    """Compile a separate layout so dependent scenarios can be rebuilt on the new sites."""
    tract = read(root/"tract-workplaces"/tract_id/"worksites.json")
    folder = root/"workplace-drive-repairs"
    repair_id = read(folder/(tract_id+".json"))["version"]
    repairs = read(folder/repair_id/"report.json")
    if any(repairs["versions"][k] != tract[k] for k in ("atlas", "day", "streets")) or repairs["versions"]["tracts"] != tract_id:
        raise ValueError("The drive repairs use a different workplace release")
    atlas = root/"atlas"/tract["atlas"]
    day = root/"cityday"/tract["day"]
    outbound = root/"outbound"/tract["outbound"]
    matched = root/"worksites"/tract["worksites"]
    places = read(day/"places.json")
    das = read(day/"day.json")["das"]
    da_index = {da: i for i, da in enumerate(das)}
    tracts, _, membership, _, geography = workplace_geography(data, archive, places, atlas)
    if tracts != tract["tracts"] or any(geography[k] != tract[k] for k in ("tableDigest", "geometryDigest")):
        raise ValueError("The road repairs require the same employment geography")
    with tempfile.TemporaryDirectory() as tmp:
        roster = Path(tmp)/"workers.json"
        subprocess.run([*TRACT_COMMAND, "extract", atlas, day, outbound, matched, roster, "diary"], check=True)
        workers = {(d, i): (site, fixed, legs) for d, i, _, site, fixed, legs in read(roster)}
    moves = {}
    for d, i, _, old, destination in tract["changes"]:
        key = d, i
        if moves.setdefault(key, (old, destination)) != (old, destination):
            raise ValueError("A worker uses several published workplaces")

    eligible, relocated, current, active_legs = [], [], [], []
    for repair in repairs["changes"]:
        key = da_index[repair["da"]], repair["index"]
        source = workers.get(key)
        if not source or source[1]:
            continue
        old, _, legs = source
        origin, previous = moves.get(key, (old, old))
        job = repair["replacement"]
        if origin != old or previous != repair["current"] or membership[previous] < 0 or membership[job] != membership[previous]:
            raise ValueError("A proposed repair would change tract or replace the wrong workplace")
        if job == old:
            moves.pop(key, None)
        else:
            moves[key] = old, job
        eligible.append(repair)
        active = [leg for leg in legs if leg[2] in ACTIVE]
        if active:
            relocated.append(job)
            current.append(previous)
            active_legs.append(active)
    coords = np.asarray([place[:2] for place in places])
    recovered_active = 0
    if active_legs:
        walking = read(root/"streets"/tract["streets"]/"network.json")
        cycling = read(root/"cycling"/tract["cycling"]/"network.json")
        fits = active_route_check({"walk": walking, "bike": cycling}, coords)
        if not fits(relocated, active_legs).all():
            raise ValueError("A repair lost a feasible walking or cycling route")
        recovered_active = int(np.count_nonzero(~fits(current, active_legs)))

    checks = check_move_distances(coords, ((workers[key][2], old, job) for key, (old, job) in moves.items()), active=True)
    source_only = {"changes", "occupancyDelta", "delta", "examples"}
    solution = {name: value for name, value in tract.items() if name not in source_only}
    stats = dict(source=tract_id, plan=repair_id, people=len(eligible),
                 drivingLegs=sum(row["repaired"] for row in eligible), activeWorkersRecovered=recovered_active)
    solution.update(roadRepairs=stats, moved=len(moves), distanceChecks=checks,
                    activeRoutes={**tract["activeRoutes"], "after": tract["activeRoutes"]["after"]+recovered_active},
                    moves=[[d, i, *move] for (d, i), move in sorted(moves.items())])
    version = compile_workplaces(root, atlas, day, outbound, matched, solution, places, data/"taz-gvrd.geojson")
    pointer(root/"tract-workplaces"/(tract_id+"_road_repairs.json"), {"version": version})
    print(version, stats, flush=True)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("tract_release")
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--data", type=Path, default=Path("data/mobility"))
    parser.add_argument("--apply", action="store_true", help="compile the published repairs into a separate workplace layout")
    args = parser.parse_args()
    run = apply_repairs if args.apply else publish
    run(args.root, args.data, args.archive, args.tract_release)
