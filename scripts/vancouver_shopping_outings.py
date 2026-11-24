"""Fit additional walking trips to Vancouver shops within existing resident diaries."""
import argparse
from collections import Counter, defaultdict
import hashlib
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from scripts.vancouver_atlas import largest_remainder
from scripts.vancouver_cityday import compile_day, overture_venues, xy
from scripts.vancouver_discretionary_outings import (
    HOURS, SHOPPING, WALK_SPEED, accessible_sites, available_windows, donor_tours,
    publish_outings, raster_clock, read_opportunities, time_slots,
)
from scripts.vancouver_flexible_transit import protected_intervals
from scripts.vancouver_pedestrians import routed_passages
from scripts.vancouver_region import read
from scripts.vancouver_streets import walk_graph
from scripts.vancouver_trip_demand import MODES, linked_trips, destination
from scripts.vancouver_walks import can_reach_site


SHOP = "Shopping"
WALK = "Walking"
CITY = "City of Vancouver"
SEED = 202346
LEG_LIMIT = 1_600  # Section 6.4.3 walkability distance for a one-way trip.
WALK_DECAY_MINUTES = 10
TIME_USE = "https://www150.statcan.gc.ca/n1/pub/45-25-0001/index-eng.htm"


def survey_target(evidence):
    survey = evidence["purposeModeSurvey"]
    shop = survey["purposes"][SHOP]
    model = Counter()
    for _, mode, purpose, fifths, *_ in evidence["cells"]:
        if purpose == SHOP and mode in MODES:
            model[mode] += fifths
    adults = sum(evidence["adults"].values()) / 5
    all_trips = adults * shop["trips"] / survey["adults"]
    walking = adults * shop["modeTrips"][WALK] / survey["adults"]
    missing_volume = max(0, all_trips - model.total() / 5)
    walk_share = shop["modeTrips"][WALK] / shop["trips"]
    target = round(missing_volume * walk_share)
    return target, {"adultEquivalents": adults, "allShopping": model.total() / 5,
                    "walking": model[WALK] / 5, "surveyAllShopping": all_trips,
                    "surveyWalking": walking, "walkShare": walk_share, "volumeTarget": target}


def named_stores(archive, places):
    located = {}
    for i, (x, y, area, label) in enumerate(places):
        if area >= 0 and label:
            located.setdefault((x, y, label), i)
    return sorted({located[key] for lon, lat, kind, label in overture_venues(archive / "data/raw")
                   if kind == "store" and (key := (*xy(lon, lat), label)) in located})


def donor_diaries(archive, scratch):
    source = scratch / "time-use.json"
    with source.open("w") as output:
        subprocess.run(["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.atlas-diaries",
                        archive, "--shopping-comparison"], check=True, stdout=output)
    diaries = read(source)
    return diaries, {"templates": [compile_day(d["episodes"]) for d in diaries]}


def weighted_donors(diaries, day):
    tours = donor_tours({"templates": diaries}, day)[SHOPPING, "walk"]
    result = defaultdict(list)
    opening, closing = HOURS[SHOPPING]
    for index, start, there, dwell, back in tours:
        purpose = next(destination(before, after) for minute, *_, before, after
                       in linked_trips(diaries[index], day["templates"][index]) if minute == start)
        if purpose != SHOP:
            continue
        hour = start // 60
        span = [(hour * 60, 1440)]
        if any(lo < (hour + 1) * 60
               for lo, _ in time_slots(span, 1, dwell, 1, opening, closing)):
            result[hour].append((index, start, there, dwell, back, diaries[index]["weight"]))
    return dict(sorted(result.items()))


def protected_activities(root, versions, day):
    by_da = protected_intervals(root, versions, day, None)
    ordinal = {da: i for i, da in enumerate(day["das"])}
    reserved = defaultdict(list, {(ordinal[da], i): intervals for (da, i), intervals in by_da.items()})
    companions = {}
    for family in ("recreation-loops", "voting"):
        companions[family] = []
        for file in sorted((root / family).glob("*/report.json")):
            folder = file.parent
            report = read(folder / "report.json")
            parents = report["versions"]
            if parents.get("clock") or any(parents.get(k) != v for k, v in versions.items()):
                continue
            companions[family].append(folder.name)
            if family == "recreation-loops":
                for da in report["areas"]:
                    for d, i, _, start, duration, added, *_ in read(folder / f"{da}.json"):
                        if added:
                            reserved[d, i].append((start, start + duration))
            else:
                for layout in report["results"]:
                    for d, i, _, _, _, start, _, leave, back, *_ in read(folder / f"{layout}.json"):
                        reserved[d, i].append((start, leave + back))
    for intervals in reserved.values():
        intervals.sort()
    short_walk = root / "short-walks" / f"{versions['day']}_{versions['streets']}.json"
    if short_walk.is_file():
        companions["shortWalkDigest"] = hashlib.sha256(short_walk.read_bytes()).hexdigest()
    return reserved, companions


def place_walk(windows, venues, donors, hour, rng):
    opening, closing = HOURS[SHOPPING]
    first, last = hour * 60, (hour + 1) * 60 - 1
    for index, minute, max_there, dwell, max_back, _ in sorted(
            donors, key=lambda donor: rng.exponential() / donor[-1]):
        choices = []
        for site, there, back in venues:
            if there > max_there or back > max_back:
                continue
            ranges = [(max(a, first), min(b, last))
                      for a, b in time_slots(windows, there, dwell, back, opening, closing)
                      if a <= last and b >= first]
            if ranges:
                departure = min((min(hi, max(lo, minute)) for lo, hi in ranges),
                                key=lambda start: abs(start - minute))
                choices.append((site, departure, there, dwell, back, index))
        if choices:
            weights = np.exp([-(there + back) / (2 * WALK_DECAY_MINUTES)
                              for _, _, there, _, back, _ in choices])
            return choices[rng.choice(len(choices), p=weights / weights.sum())]
    return None


def fit(opportunities, routes, donors, reserved, target, rng):
    areas, hours = sorted(opportunities["adultsByArea"]), list(donors)
    area_targets = dict(zip(areas, map(int, largest_remainder(
        [opportunities["adultsByArea"][name] for name in areas], target)), strict=True))
    hour_targets = dict(zip(hours, map(int, largest_remainder(
        [sum(donor[-1] for donor in donors[hour]) for hour in hours], target)), strict=True))
    added_area, added_hour = Counter(), Counter()
    tours = []
    residents = opportunities["residents"]
    for index in rng.permutation(len(residents)):
        d, i, home, template, area, *_ = residents[index]
        if added_area[area] >= area_targets[area] or not routes.get((home, SHOP)):
            continue
        windows = list(available_windows(opportunities["windows"][template], reserved.get((d, i), ())))
        eligible_hours = [hour for hour in hours if added_hour[hour] < hour_targets[hour]
                          and any(lo < (hour + 1) * 60 and hi > hour * 60 for lo, hi in windows)]
        rng.shuffle(eligible_hours)
        eligible_hours.sort(key=lambda h: added_hour[h] / hour_targets[h])
        for hour in eligible_hours:
            assigned = place_walk(windows, routes[home, SHOP], donors[hour], hour, rng)
            if assigned:
                site, start, there, dwell, back, donor = assigned
                tours.append([d, i, home, site, SHOP, "walk", start, there, dwell, back, donor])
                added_area[area] += 1
                added_hour[hour] += 1
                break
        if len(tours) == target:
            break
    return sorted(tours), [[name, area_targets[name], added_area[name]] for name in areas], [
        [hour, hour_targets[hour], added_hour[hour]] for hour in hours]


def pedestrian_check(root, versions, network, places, tours):
    folder = root / "pedestrians"
    key = f"{versions['day']}_{versions['streets']}.json"
    release = read(folder / key)["version"]
    reference = read(folder / release / "counts.json")
    if any(reference[k] != v for k, v in versions.items()):
        raise ValueError("The pedestrian counts use a different weekday")
    sites = reference["sites"]
    legs = []
    for _, _, home, store, _, _, start, there, dwell, back, _ in tours:
        for a, b, minute, duration in ((home, store, start, there),
                                       (store, home, start + there + dwell, back)):
            limit = duration * WALK_SPEED
            if any(can_reach_site(places[a][:2], places[b][:2], site["point"], limit)
                   and any(hour < minute + duration and hour + 60 > minute for hour in site["hours"])
                   for site in sites):
                legs.append(("outings", a, b, minute, duration, limit))
    passages = Counter(routed_passages(network, places, sites, legs))
    return {"release": release, "radius": reference["radius"], "sites": [
        dict(name=site["name"], date=site["date"], source=site["source"], hours=site["hours"],
             observed=site["observed"], base=[a + b for a, b in zip(site["city"], site["inferred"], strict=True)],
             added=[passages[j, "outings", hour] for hour in site["hours"]])
        for j, site in enumerate(sites)]}


def publish(root, archive, backend, versions=None):
    if versions is None:
        city = read(root / "cityday/current.json")
        versions = dict(atlas=city["atlas"], day=city["version"], streets=read(root / "streets/current.json")["version"])
    street = versions["streets"]
    demand_root = root / "trip-demand"
    demand = read(demand_root / f"{versions['atlas']}_{versions['day']}.json")["version"]
    evidence = read(demand_root / demand / "demand.json")
    if any(evidence[k] != versions[k] for k in ("atlas", "day")):
        raise ValueError("The trip comparison uses a different weekday")
    target, benchmark = survey_target(evidence)
    atlas = root / "atlas" / versions["atlas"]
    day_dir = root / "cityday" / versions["day"]
    day, places = read(day_dir / "day.json"), read(day_dir / "places.json")
    population = read(atlas / "atlas.json")
    stores = named_stores(archive, places)
    if not stores:
        raise ValueError("No named shops match the resident weekday")
    network = read(root / "streets" / street / "network.json")
    graph, snap = walk_graph(network)
    reserved, companions = protected_activities(root, versions, day)
    templates_already_shopping = {
        i for i, (diary, template) in enumerate(zip(population["templates"], day["templates"], strict=True))
        if any(destination(before, after) == SHOP for *_, before, after in linked_trips(diary, template))}
    with tempfile.TemporaryDirectory(dir=root) as folder:
        scratch = Path(folder)
        donors = weighted_donors(*donor_diaries(archive, scratch))
        opportunities = read_opportunities(atlas, day_dir, scratch, detail="adults-only", municipalities=day["areas"])
        opportunities["residents"] = [
            row for row in opportunities["residents"] if row[2] >= 0 and places[row[2]][2] >= 0
            and row[3] not in templates_already_shopping]
        homes = sorted({r[2] for r in opportunities["residents"]})
        routes = accessible_sites(homes, {SHOP: stores}, [p[:2] for p in places], graph, snap,
                                  LEG_LIMIT, 500, WALK_SPEED)
        print(f"{len(opportunities['residents']):,} eligible diaries, {len(routes):,} homes with routes "
              f"to {len(stores):,} mapped shops. Fitting {target:,} added outings.", flush=True)
        tours, area_counts, hour_counts = fit(opportunities, routes, donors, reserved, target,
                                              np.random.default_rng(SEED))
        if not tours or len({tuple(row[:2]) for row in tours}) != len(tours):
            raise ValueError("The fitted outings must have distinct eligible residents")
        clock = raster_clock(tours, places, day["occupancy"], day["areas"], scratch, backend)

    metrics = [[CITY, SHOP, "walk", benchmark["walking"], round(benchmark["surveyWalking"]), len(tours)]]
    audit = read(day_dir / "mobility.json")
    fitted = {(row[0], row[1]) for row in tours}
    age45 = sum(row[-1] == 9 and (row[0], row[1]) in fitted for row in opportunities["residents"])
    crossings = pedestrian_check(root, versions, network, places, tours)
    report = dict(versions=versions, demand=demand, source=evidence["source"] + "#page=63", timeUse=TIME_USE,
                  cityScope=CITY, seed=SEED, metrics=metrics, attendance=len(tours),
                  residents=benchmark["adultEquivalents"], trips=audit["main"]["trips"],
                  surveyRate=audit["survey"]["rate"], age45Attendance=age45,
                  benchmark=benchmark, areaCounts=area_counts, hourCounts=hour_counts, companions=companions,
                  donorTours=sum(map(len, donors.values())),
                  donorDiaries=len({row[0] for rows in donors.values() for row in rows}),
                  venues=len(stores), visitedVenues=len({row[3] for row in tours}), hours=HOURS[SHOPPING],
                  pedestrianCheck=crossings,
                  walkMetresPerMinute=WALK_SPEED, legLimitMetres=LEG_LIMIT,
                  walkDecayMinutes=WALK_DECAY_MINUTES, **clock)
    return publish_outings(root, report, tours)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--backend", default="jvm")
    args = parser.parse_args()
    print(publish(args.root, args.archive, args.backend))
