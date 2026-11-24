"""Test whether flexible home time can accommodate otherwise unmatched work transit."""
import argparse
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
import subprocess
import tempfile

from scripts.artifacts import package, pointer, read, write_json
from scripts.vancouver_campus import access_routes
from scripts.vancouver_city_transit import DirectService
from scripts.vancouver_raster import publish as raster_occupancy
from scripts.vancouver_transit_commutes import BOARDING_MARGIN_SECONDS
from scripts.vancouver_transit_load import ANNUAL_TABLE, TABLE, BusSpaces, bus_capacity_profile, bus_load_evidence
from scripts.vancouver_transit_transfers import OneTransfer, walk_transfers
from scripts.vancouver_work_transit import choose, outing_rides, priority, publish_rides

WORKPLACE_RUN = "06c504c638de40f775a7"
MAX_EXTENSION = 30
REMAINING_HOME_TIME = 10


def protected_intervals(region, versions, day, outing_version):
    reserved = defaultdict(list)
    if outing_version:
        tours = read(region / "discretionary-outings" / outing_version / "tours.json")
        for d, person, _, _, _, _, start, travel, dwell, back, *_ in tours:
            reserved[day["das"][d], person].append((start, start + travel + dwell + back))
    short_walks = region / "short-walks" / (versions["day"] + "_" + versions["streets"] + ".json")
    if short_walks.is_file():
        data = read(short_walks)
        if any(data[k] != versions[k] for k in ("atlas", "day", "streets")):
            raise ValueError("Reconstructed walks use a different weekday")
        for d, person, start, duration, *_ in data["walks"]:
            reserved[day["das"][d], person].append((start, start + duration))
    return reserved


def time_budget(span, intervals, toward_work):
    lo, hi = span
    blocks = sorted((max(lo, a), min(hi, b)) for a, b in intervals if a < hi and b > lo)
    available, cursor = hi - lo, lo
    for a, b in blocks:
        available -= max(0, b - max(a, cursor))
        cursor = max(cursor, b)
    free_edge = (hi - cursor if toward_work else blocks[0][0] - lo) if blocks else hi - lo
    return max(0, min(MAX_EXTENSION, available - REMAINING_HOME_TIME, free_edge))


def min_change(direct, transfer, toward_work, start, end, a, b, budget):
    if toward_work:
        # Both can leave by the original work arrival. The latest actual
        # departure uses the least additional home time.
        options = [ride for ride in (direct(end * 60, a, b), transfer(end * 60, a, b))
                   if ride is not None and start - budget <= ride[0] < start]
        if options:
            best = max(options, key=lambda ride: (ride[0], len(ride[2]) == 6, -ride[1]))
            return best[0], end, best[2]
    else:
        options = choose(direct, transfer, start, end + budget, a, b)
        if options is None:
            return None
        lo, hi = end + 1, end + budget
        while lo < hi:
            mid = (lo + hi) // 2
            trial = choose(direct, transfer, start, mid, a, b)
            if trial is None:
                lo = mid + 1
            else:
                hi, options = mid, trial
        if options[1] > end * 60:
            return start, hi, options[2]


def fit(rows, baseline, places, access, service, planner, spaces, protected):
    matched = {tuple(row[:3]) for row in baseline}
    direct = service.latest_departure(access, BOARDING_MARGIN_SECONDS, spaces.available)
    transfer = lambda deadline, a, b: planner.latest(deadline, a, b, spaces.available)
    open_direct = lru_cache(maxsize=32768)(service.latest_departure(access, BOARDING_MARGIN_SECONDS))
    revised, added, counts = defaultdict(list), [], Counter()
    for row in sorted(rows, key=priority):
        da, person, start, duration, a, b, toward_work, tpl, span = row
        identity, end = (da, person), start + duration
        if (*identity, start) in matched:
            counts["alreadyMatched"] += 1
            continue
        counts["unmatchedFlexible"] += 1
        budget = time_budget(span, protected.get(identity, []), toward_work)
        if not budget or a not in access or b not in access or places[a][:2] == places[b][:2]:
            continue
        counts["considered"] += 1
        result = min_change(direct, transfer, toward_work, start, end, a, b, budget)
        if result is None:
            continue
        departure, arrival, ride = result
        borrowed = (departure, start) if toward_work else (end, arrival)
        spaces.reserve(ride)
        protected[identity].append(borrowed)
        reason = "capacity" if choose(open_direct, planner.latest, start, end, a, b) else "schedule"
        counts["recovered" + reason.title()] += 1
        edit = [start, end, departure, arrival]
        revised[da, person, tpl].append(edit)
        added.append(([da, person, departure, arrival - departure, a, b, *ride], edit, toward_work))
    revisions = [[da, person, tpl, sorted(edits)] for (da, person, tpl), edits in sorted(revised.items())]
    return added, revisions, dict(counts)


def verified_occupancy(region, versions, clock_id, atlas_dir, day_dir, work):
    """Run both Raster fidelities on the existing plans with revised templates."""
    clock = read(region / "household-clock" / clock_id / "clock.json")
    atlas, day = read(atlas_dir / "atlas.json"), read(day_dir / "day.json")
    atlas["templates"].extend(t["diary"] for t in clock["templates"])
    day["templates"].extend(t["day"] for t in clock["templates"])
    day["occupancy"] = clock["occupancy"]
    changes = {da: dict((i, (old, new)) for i, old, new in rows) for da, rows in clock["changes"].items()}
    for row in day["sample"]:
        d, i, tpl, *_ = row
        edit = changes.get(day["das"][d], {}).get(i)
        if edit:
            if tpl != edit[0]:
                raise ValueError("Revised template uses a different display sample")
            row[2] = edit[1]
    temp_atlas, temp_day = work / "atlas" / versions["atlas"], work / "day" / versions["day"]
    temp_atlas.mkdir(parents=True)
    temp_day.mkdir(parents=True)
    for da in day["das"]:
        name = da + ".json"
        (temp_day / name).symlink_to((day_dir / name).resolve())
        if da in changes:
            roster = read(atlas_dir / name)
            for i, (old, new) in changes[da].items():
                if roster["people"][i][7] != old:
                    raise ValueError("Revised template uses a different resident")
                roster["people"][i][7] = new
            write_json(temp_atlas / name, roster)
        else:
            (temp_atlas / name).symlink_to((atlas_dir / name).resolve())
    (temp_day / "places.json").symlink_to((day_dir / "places.json").resolve())
    write_json(temp_atlas / "atlas.json", atlas)
    write_json(temp_day / "day.json", day)
    result = raster_occupancy(work, versions["atlas"], versions["day"], verify=True,
                              atlas_root=temp_atlas.parent, day_root=temp_day.parent)
    pointer(region / "raster" / (versions["atlas"] + "_" + versions["day"] + "_" + clock_id + ".json"), result)
    print("Verified Raster occupancy", result["population"], "residents", result["groups"], "weighted itineraries", flush=True)


def build(region, archive, workplace_run):
    pair = read(region / "regional-workplaces" / workplace_run / "report.json")
    versions = dict(pair["versions"], day=pair["day"], transit=pair["timetable"])
    key = "_".join(versions[k] for k in ("atlas", "day", "streets"))
    fixed_id = read(region / "work-transit" / (key + ".json"))["version"]
    fixed_dir = region / "work-transit" / fixed_id
    report = read(fixed_dir / "report.json")
    if report["versions"] != versions:
        raise ValueError("The fixed timetable uses different simulation inputs")
    fixed = [row for da in report["coverage"]["areas"] for row in read(fixed_dir / f"{da}.json")]
    schedule = region / "transit" / versions["transit"]
    streets = region / "streets" / versions["streets"]
    atlas_dir = region / "atlas" / versions["atlas"]
    day_dir = region / "cityday" / versions["day"]
    day, places = read(day_dir / "day.json"), read(day_dir / "places.json")
    outing_version = report.get("sharedOutings", {}).get("version")
    _, reserved = outing_rides(region, versions, outing_version) if outing_version else (None, [])
    protected = protected_intervals(region, versions, day, outing_version)
    observed = archive / "data/raw/probes" / TABLE
    annual = observed.with_name(ANNUAL_TABLE)
    service = DirectService(schedule)
    profile = bus_capacity_profile(service.route_manifest, observed, annual if annual.is_file() else None)
    spaces = BusSpaces(profile["limits"])
    for ride in reserved:
        spaces.reserve(ride)
    for row in fixed:
        spaces.reserve(row[6:])
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        windows = work / "windows.json"
        cmd = ["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.transit-commutes"]
        subprocess.run([*cmd, "flex-windows", atlas_dir, day_dir, windows], check=True)
        rows = read(windows)["rows"]
        if not rows:
            raise ValueError("No work trips touch a flexible at-home diary episode")
        locations = {p for row in rows for p in row[4:6]}
        access = access_routes(places, locations, service.stations, streets)
        connections = walk_transfers(service, read(schedule / "transfers.json")["pairs"],
                                     streets / "network.json", BOARDING_MARGIN_SECONDS)
        planner = OneTransfer(service, access, connections, BOARDING_MARGIN_SECONDS)
        added, revisions, counts = fit(rows, fixed, places, access, service, planner, spaces, protected)
        if not added:
            raise ValueError("Flexible home timing did not recover any trips on this weekday")
        print(f"Matched {len(added):,} additional trips.", counts, flush=True)
        trips = [*fixed, *(row for row, _, _ in added)]
        report["bus"] = bus_load_evidence(schedule, service.route_manifest, trips, observed, profile["limits"], reserved=reserved)
        if report["bus"]["above"]:
            raise ValueError("Combined transit reservations exceed their vehicle budget")
        outcomes = report["outcomes"]
        for key_name in ("schedule", "capacity"):
            outcomes[key_name] = outcomes.get(key_name, 0) - counts.get("recovered" + key_name.title(), 0)
        for row, _, toward_work in added:
            for key_name in ("transfer" if len(row) > 12 else "direct", "towardWork" if toward_work else "fromWork"):
                outcomes[key_name] = outcomes.get(key_name, 0) + 1
        if any(v < 0 for v in outcomes.values()) or len(trips) + sum(outcomes.get(k, 0) for k in ("schedule", "capacity", "access", "sameCoordinates")) != report["eligible"]:
            raise ValueError("Retimed trips and unrecovered counts do not reconcile")
        def added_minutes(edit):
            start, end, departure, arrival = edit
            return (arrival - departure) - (end - start)

        row, example, _ = min(added, key=lambda item: (-added_minutes(item[1]), abs(item[0][2] - 1020), item[0][:3]))
        report["examples"]["flex"] = row
        edits = sum(added_minutes(edit) for _, edit, _ in added)
        report["flex"] = dict(counts, added=len(added), people=len(revisions), flexibleWindows=len(rows),
                              minutesBorrowed=edits, maxExtension=MAX_EXTENSION, retainedHome=REMAINING_HOME_TIME,
                              originalMatchCount=len(fixed), baselineRelease=fixed_id, example=example)
        ride_release = publish_rides(region, day, trips, report)
        data = dict(revisions=revisions, report=dict(streets=versions["streets"], transit=versions["transit"],
                                                     workplaceRun=workplace_run, workTransitRelease=ride_release,
                                                     flex=report["flex"]))
        source = work / "retimed.json"
        write_json(source, data)
        clock_id = package(region, "household-clock", lambda out: subprocess.run(
            [*cmd, "flex-clock", atlas_dir, day_dir, source, out], check=True))
        verified_occupancy(region, versions, clock_id, atlas_dir, day_dir, work)
    history = region / "releases" / (versions["atlas"] + "_" + versions["day"] + ".json")
    if not history.is_file():
        pointer(history, {"atlas": versions["atlas"], "day": versions["day"], "streets": versions["streets"],
                          "transit": pair["versions"]["transit"]})
    pointer(region / "work-transit-flex" / (key + ".json"), {"version": clock_id})
    print("Published", clock_id, ride_release, report["flex"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--workplace-run", default=WORKPLACE_RUN)
    args = parser.parse_args()
    build(args.region, args.archive, args.workplace_run)
