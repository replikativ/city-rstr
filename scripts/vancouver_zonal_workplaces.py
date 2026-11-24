"""Fit North Shore work destinations to the 2025 diary matrix on a paired weekday."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import os
import subprocess
import tempfile

import numpy as np
from scipy.spatial import cKDTree

from scripts.vancouver_atlas import largest_remainder, write_json
from scripts.vancouver_downtown_workplaces import SUPPORTED, Routes
from scripts.vancouver_eastern_workplaces import candidates_for, publish_replay
from scripts.vancouver_north_shore_demand import SURVEY_2025, SURVEY_2025_ARCHIVE, SURVEY_2025_DIGEST, verify_survey
from scripts.vancouver_north_shore_zones import OBSERVED, WORK_ZONES, ZONE_NAMES, crosswalk, workplace_groups
from scripts.vancouver_region import NAMES, package, read
from scripts.vancouver_regional_workplaces import variant_day

DESTINATIONS = WORK_ZONES[:-1]  # Table 54 suppresses every New Westminster estimate.


def fit_zone(zone, workers, groups, site_options, routes, rng):
    observed = dict(zip(DESTINATIONS, (row[zone - 1] for row in OBSERVED[:-1]), strict=True))
    before = Counter(groups[w[4]] for w in workers)
    # Apply the survey proportions to the located synthetic commute total.
    # Keep suppressed cells at their existing synthetic count.
    known = [name for name in DESTINATIONS if isinstance(observed[name], int)]
    expected = np.asarray([observed[name] for name in known])
    target = before.copy()
    desired = largest_remainder(expected / expected.sum(), sum(before[name] for name in known))
    for name, count in zip(known, desired, strict=True):
        target[name] = int(count)
    after = before.copy()
    candidates = [w for w in workers if after[groups[w[4]]] > target[groups[w[4]]] and w[6]
                  and all(a >= 0 and t > 0 and m in SUPPORTED for a, t, m, *_ in w[6])]
    order = rng.permutation(len(candidates))
    moved, used = [], set()
    # Allocate higher deficits first. The other cells and commute clocks are
    # fixed, so a shortfall reflects the inventory, search and diary limits.
    for destination in sorted(known, key=lambda name: before[name] - target[name]):
        if after[destination] >= target[destination] or destination not in site_options:
            continue
        for i in order:
            worker = candidates[i]
            d, person, _, _, old, slots, legs, _ = worker
            origin = groups[old]
            if after[origin] <= target[origin] or (d, person) in used:
                continue
            anchor = min(legs, key=lambda leg: leg[1])[0]
            for site in candidates_for(routes.points[anchor], site_options[destination], rng):
                if routes.feasible(worker, int(site)):
                    after[origin] -= 1
                    after[destination] += 1
                    used.add((d, person))
                    moved.append((d, [person, slots, old, int(site)]))
                    break
            if after[destination] == target[destination]:
                break
    if before.total() != after.total():
        raise ValueError("Commute reallocation changed the number of workers in a home zone")
    return moved, dict(zone=zone, before=before, after=after, target=target)


def publish(root, parent_id, survey):
    verify_survey(survey, SURVEY_2025_DIGEST)
    parent = read(root / "regional-workplaces" / parent_id / "report.json")
    versions = dict(parent["versions"], day=parent["day"])
    base = root / "cityday" / versions["day"]
    roster = root / "atlas" / versions["atlas"]
    atlas, day, places = read(roster / "atlas.json"), read(base / "day.json"), read(base / "places.json")
    if not all(city in day["areas"] for city in ("Burnaby", "New Westminster")):
        raise ValueError("The zonal fit requires the eastern workplace weekday")
    zones = crosswalk(survey, atlas, roster, places, day["areas"], NAMES.values())
    groups = workplace_groups(places, day["areas"], zones["placeZones"], NAMES.values())
    with tempfile.TemporaryDirectory(dir=root) as temp:
        extracted = Path(temp) / "workers.json"
        subprocess.run(["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.regional-workplaces",
                        roster, base, extracted, "swaps"], check=True)
        workers = read(extracted)["workers"]
    by_home = defaultdict(list)
    homes = {}
    sites = defaultdict(Counter)
    for w in workers:
        d, person, municipality, _, job, *_ = w
        if groups[job] in DESTINATIONS:
            sites[groups[job]][job] += 1
        if municipality <= 0:
            continue
        da = day["das"][d]
        if d not in homes:
            homes[d] = read(base / f"{da}.json")["home"]
        site = homes[d][person]
        place_zone = zones["placeZones"][site] if site >= 0 else 0
        zone = place_zone or zones["daZones"][da]
        if zone:
            by_home[zone].append(w)
    # The expanded inventory includes unused mapped Burnaby job sites.
    for i, (_, _, area, *_) in enumerate(places):
        if area >= 0 and day["areas"][area] == "Burnaby":
            sites["Burnaby"].setdefault(i, 1)
    north = [worker for records in by_home.values() for worker in records]
    site_ids = {i for counts in sites.values() for i in counts}
    print(f"Checking {len(north):,} workers and {len(site_ids):,} mapped job sites.", flush=True)
    routes = Routes(root, versions, places, [w for w in north if w[6]], parent["timetable"],
                    destination_sites=site_ids)
    options = {}
    for name, counts in sites.items():
        ids = np.array(list(counts))
        weights = np.array(list(counts.values()))
        options[name] = ids, weights / weights.sum(), cKDTree(routes.points[ids])
    moves, evidence = defaultdict(list), []
    rng = np.random.default_rng(202554)
    for zone, records in sorted(by_home.items()):
        changed, audit = fit_zone(zone, records, groups, options, routes, rng)
        for da, move in changed:
            moves[da].append(move)
        evidence.append(audit)
        print(ZONE_NAMES[zone - 1], "moved", len(changed), "Burnaby", audit["after"]["Burnaby"], flush=True)
    moved = sum(map(len, moves.values()))
    if not moved:
        raise ValueError("No surveyed workplace adjustment fit the original travel windows")

    def build(out):
        day["workplaceFit"] = SURVEY_2025_DIGEST
        variant_day(base, day, places, moves, roster, out)
        os.link(base / "basemap.json", out / "basemap.json")

    release_day = package(root, "cityday", build, versions["day"])
    report = dict(versions=versions, day=release_day, extendedMap=True, incomingDay=parent["incomingDay"],
                  originWorkplaceRun=parent_id, basisLabels={"original": "Eastern workplaces", "census": "2025 workplace fit"},
                  zoneAllocation=evidence, moved=moved, source=SURVEY_2025, sourceDigest=SURVEY_2025_DIGEST,
                  timetable=parent["timetable"], serviceDate=routes.transit_date, speedDigest=routes.routing["profileDigest"])
    release = package(root, "regional-workplaces", lambda out: write_json(out / "report.json", report))
    print(release, release_day, moved, flush=True)
    return report, release


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--archive", type=Path, default=Path("../Simulations/city"))
    parser.add_argument("--inputs", type=Path, default=Path("data/region"))
    parser.add_argument("--parent", default="c1b31a9daf40041dcb73")
    parser.add_argument("--survey", type=Path, default=SURVEY_2025_ARCHIVE)
    parser.add_argument("--resume", help="Publish replay companions for an existing fit.")
    args = parser.parse_args()
    if args.resume:
        release = args.resume
        result = read(args.region / "regional-workplaces" / release / "report.json")
    else:
        result, release = publish(args.region, args.parent, args.survey)
    publish_replay(args.region, args.archive, args.inputs, result, release, survey_2025=args.survey)
