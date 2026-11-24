"""Pair a North Shore workplace calibration with a fixed-shift timing sensitivity."""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
from math import dist
from pathlib import Path
import re

from scripts.vancouver_city_transit import DirectService
from scripts.vancouver_downtown import station_counts
from scripts.vancouver_downtown_transit_audit import downtown_window, incoming_inputs
from scripts.vancouver_downtown_transit_booking import keep_reservations, trial
from scripts.vancouver_downtown_workplaces import CORE, WORK_LOCATIONS
from scripts.vancouver_incoming_duration_check import DISTANCE, DURATION, SOURCE, duration_margins, summarize
from scripts.vancouver_north_shore_demand import SURVEY, SURVEY_2025, SURVEY_2025_ARCHIVE, SURVEY_2025_DIGEST, SURVEY_ARCHIVE, SURVEY_DIGEST
from scripts.vancouver_region import read
from scripts.vancouver_transit_commutes import pointer
from scripts.vancouver_transit_trace import JourneyTrace
from scripts.vancouver_work_transit import transfer_inputs, window


def kilometres(places, home, workplace):
    return dist(places[home][:2], places[workplace][:2]) / 1_000


def distance_band(km):
    return bisect_right(DISTANCE, km) - 1


def exchange_workplaces(workers, places, stations_are_core, north, strata, protected):
    """Preserve assigned slot counts and each worker's original Census distance band."""
    def in_core(row):
        return stations_are_core[row[5]]

    totals = Counter(key[0] for key in workers if key[0] in north)
    before = Counter(key[0] for key, row in workers.items() if key[0] in north and in_core(row))
    quotas = {key: (totals[key] * core * 2 + core + other) // (2 * (core + other))
              for key, (core, other) in north.items()}
    donors = defaultdict(list)
    for key, row in workers.items():
        if key[0] not in north and in_core(row) and key not in protected:
            donors[strata[key]].append(key)
    original = {key: kilometres(places, row[4], row[5]) for key, row in workers.items()}
    swaps = {}
    assigned = before.copy()
    for key, row in workers.items():
        group = key[0]
        if group not in north or key in protected or in_core(row) or assigned[group] >= quotas[group]:
            continue
        options = []
        for donor in donors[strata[key]]:
            if donor in swaps:
                continue
            other = workers[donor]
            a = kilometres(places, row[4], other[5])
            b = kilometres(places, other[4], row[5])
            if distance_band(a) == distance_band(original[key]) and distance_band(b) == distance_band(original[donor]):
                options.append((abs(a - original[key]) + abs(b - original[donor]), donor))
        if options:
            _, donor = min(options)
            swaps[key] = workers[donor][5]
            swaps[donor] = row[5]
            assigned[group] += 1
    if Counter(row[5] for row in workers.values()) != Counter(swaps.get(key, row[5]) for key, row in workers.items()):
        raise ValueError("Workplace exchanges changed the number of assigned jobs at an address")
    return swaps, {key: dict(total=totals[key], before=before[key], target=quotas[key], after=assigned[key],
                             survey=north[key]) for key in north}


def reassign(row, swaps):
    job = swaps.get(tuple(row[:2]))
    if job is None:
        return row
    return (*row[:4], row[4], job, True) if row[-1] else (*row[:4], job, row[5], False)


def check_source(path, expected):
    with path.open("rb") as archive:
        if hashlib.file_digest(archive, "sha256").hexdigest() != expected:
            raise ValueError(f"The archived survey differs from the published reference: {path}")


def publish(data, release, archive, table):
    check_source(SURVEY_ARCHIVE, SURVEY_DIGEST)
    check_source(SURVEY_2025_ARCHIVE, SURVEY_2025_DIGEST)
    run = read(data / "runs" / f"{release}.json")
    if (run["release"], run["city"], run["coverage"]) != (release, "vancouver", "city"):
        raise ValueError("Choose a published municipal Vancouver weekday")
    root = data / "vancouver"
    joint = read(root / "joint-weekday" / run["jointRun"] / "report.json")
    day = root / "cityday" / run["day"]
    area_names = read(day / "day.json")["areas"]
    core = area_names.index("Downtown")
    core_areas = {i for i, name in enumerate(area_names) if name in CORE}
    incoming, _, _, groups, names, places, identities, _, booked = incoming_inputs(
        root, run["jointRun"], joint, run["incomingTransit"], read(day / "places.json"))
    north = {key: WORK_LOCATIONS[name] for key, name in names.items() if name in WORK_LOCATIONS}
    if len(north) != len(WORK_LOCATIONS):
        raise ValueError("The published weekday lacks a North Shore municipality")
    workers = {key[:2]: row for key, row in identities.items() if row[-1]}
    cohort = root / "commuters" / joint["commuters"]
    strata = {}
    for group in names:
        for i, person in enumerate(read(cohort / f"{group}.json")["people"]):
            if (group, i) in workers:
                strata[group, i] = tuple(person[2:4])
    protected = {key[:2] for key in booked}
    core_jobs = [place[2] in core_areas for place in places]
    swaps, workplace = exchange_workplaces(workers, places, core_jobs, north, strata, protected)
    if not swaps:
        raise ValueError("No exchange is possible under the published controls")
    print("Workplace quotas", workplace, flush=True)

    # Test both assignments on the same workers, including donor partners outside the North Shore.
    scope = {key for key in workers if key[0] in north} | swaps.keys()
    selected = {key: row for key, row in identities.items() if key[:2] in scope}
    pendings = [{key: reassign(row, changes) for key, row in selected.items() if key not in booked}
                for changes in ({}, swaps)]
    probes = archive / "data/raw/probes"
    schedule = root / "transit" / incoming["timetable"]
    service = DirectService(schedule)
    spaces = keep_reservations(root, run, joint, incoming, booked, service, probes)
    walk = root / "commuter-walk" / incoming["walking"]
    windows = {window(row) for pending in pendings for row in pending.values() if places[row[4]][:2] != places[row[5]][:2]}
    access, planner = transfer_inputs(windows, places, service, walk, schedule)
    trace = JourneyTrace(service, access, planner.connections, incoming["boardingMargin"])
    book_comparisons = [trial(trace, deepcopy(spaces), [row for row in pending.values()
                       if row[4] in access and row[5] in access and places[row[4]][:2] != places[row[5]][:2]], (0, 15))
                        for pending in pendings]

    margins = duration_margins(table, {key[0] for key in scope})
    durations = {key: ((row[0], distance_band(kilometres(places, row[4], row[5]))), row[3])
                 for key, row in selected.items() if row[-1]}
    benchmark = read(root / "downtown-audit" / f"{release}.json")
    rail = next(site for site in benchmark["sites"] if site["key"] == "downtownSkyTrain")
    rail_table = probes / "transit_translink_tspr2025_skytrainavgalightsbrdgs_yearstationdaytypehourly.csv"

    def score(changes, extra, recovered):
        rail_counts = station_counts(rail_table, schedule, service.route_manifest, {"new": recovered.values()})
        observed = incoming["rail"]["observed"]
        if rail_counts["observed"] != observed or rail_counts["stations"] != rail["stations"]:
            raise ValueError("The workplace experiment uses different station observations")
        peak_windows = [range(7, 9), range(16, 18)]
        peaks = [sum(rail["directions"][i]["hourly"]["modeled"][h] + rail_counts["matched"][h][i]
                     for h in hours) for i, hours in enumerate(peak_windows)]
        cohort_peak = Counter()
        by_origin = defaultdict(Counter)
        for key, row in selected.items():
            group = by_origin[names[key[0]]]
            group["trips"] += 1
            fitted = key in booked or key in recovered
            group["booked"] += fitted
            group["added"] += key in recovered
            new = reassign(row, changes)
            slot = downtown_window(new, places, core)
            if slot and fitted and slot[0] in peak_windows[slot[1] == "leaving"]:
                cohort_peak[slot[1]] += 1
        durations_by_origin = defaultdict(list)
        for key, (band, old) in durations.items():
            durations_by_origin[names[key[0]]].append((band, old, recovered[key][3] if key in recovered else old))
        comparison = summarize([row for rows in durations_by_origin.values() for row in rows], margins)
        for name, rows in durations_by_origin.items():
            if any(margins.get(row[0]) for row in rows):
                by_origin[name]["duration"] = summarize(rows, margins)
        return dict(workplaces=bool(changes), extraMinutes=extra, added=len(recovered),
                    stationPeakCounts=peaks, downtownPeakBookings=[cohort_peak["arriving"], cohort_peak["leaving"]],
                    duration=comparison, byOrigin=dict(sorted(by_origin.items())))

    # Table 54 reports rounded home-zone counts for attending workers, summed across eight zones.
    holdout_workplaces = [15900, 10800]
    evidence = dict(schema=1, release=release, parents=benchmark["parents"], workplaceSource=SURVEY,
                    workplaceDigest=SURVEY_DIGEST, workplaceTable=20, holdoutSource=SURVEY_2025,
                    holdoutDigest=SURVEY_2025_DIGEST, holdoutTable=54, holdoutWorkplaces=holdout_workplaces,
                    durationSource=SOURCE, durationBands=DURATION, stationSource=rail["source"], workers=len(scope),
                    swaps=len(swaps) // 2,
                    northShore={names[key]: counts for key, counts in workplace.items()},
                    observedStationPeakCounts=[rail["directions"][i]["windows"][i]["observed"] for i in range(2)],
                    scenarios=[score(changes, extra, recovered) for changes, trials in zip(({}, swaps), book_comparisons, strict=True)
                               for extra, _, _, recovered in trials])
    out = root / "downtown-audit" / f"{release}-workplace-timing.json"
    pointer(out, evidence)
    print(out, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data", type=Path, default=Path("public/data"))
    parser.add_argument("--table", type=Path, default=Path("data/mobility/98100461-eng.zip"))
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{64}", args.release):
        parser.error("Choose a 64-character weekday ID")
    publish(args.data, args.release, args.archive, args.table)
