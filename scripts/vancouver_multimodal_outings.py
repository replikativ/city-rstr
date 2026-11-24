"""Add bicycle and scheduled transit outings to the paired North Shore replay."""
import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
from pathlib import Path
import tempfile

import numpy as np
from scipy.spatial import cKDTree

from scripts.vancouver_campus import access_routes
from scripts.vancouver_city_transit import DirectService
from scripts.vancouver_cycle_tours import assign_access
from scripts.vancouver_discretionary_outings import (
    HOURS, PURPOSES, RECREATION, SHOPPING, SHOPPING_SHARES, accessible_sites, available_windows,
    donor_tours, local_venues, place_outing, publish_outings, raster_clock, read_opportunities, reserved_walks,
)
from scripts.vancouver_north_shore_demand import SURVEY_MODES, SURVEY_ROWS, trip_inputs
from scripts.vancouver_region import read
from scripts.vancouver_streets import access_graph
from scripts.vancouver_transit_commutes import BOARDING_MARGIN_SECONDS
from scripts.vancouver_transit_load import ANNUAL_TABLE, TABLE, BusSpaces, bus_capacity_profile, observed_spare_capacity

MODES = ("bike", "transit")
BIKE_ACCESS = {"City of North Vancouver": 54, "District of North Vancouver": 58, "West Vancouver": 47}
# Survey Figure 14. Each bracket lists shopping, personal business, or the one recreation share.
SHARES = {SHOPPING: {"bike": (.01, .02), "transit": (.03, .08)},
          RECREATION: {"bike": (.02,), "transit": (.03,)}}
SEED = 65005
BIKE_SPEED = 220
TIMETABLE = "5688b19e3abeb58bd4a2"


def draw_access(adults):
    candidates = defaultdict(list)
    for i, (_, _, area, cycling) in enumerate(adults):
        candidates[area, cycling].append(i)
    access, counts = set(), {}
    for i, (area, percent) in enumerate(BIKE_ACCESS.items()):
        free, riders = candidates[area, False], candidates[area, True]
        draw = assign_access(free, riders, percent, np.random.default_rng([SEED, i]))
        access.update(tuple(adults[j][:2]) for j in draw)
        counts[area] = dict(adults=len(free)+len(riders), access=len(draw), observedCyclists=len(riders))
    return access, counts


def travel_budget_pairs(atlas, day):
    """Take both travel allowances from the same single-stop diary outing."""
    allowed = {"bike": {"bike"}, "transit": {"transit", "walk"}}
    pairs = defaultdict(list)
    for i, (diary, spatial) in enumerate(zip(atlas["templates"], day["templates"], strict=True)):
        parts, slots = spatial["parts"], spatial["slots"]
        bouts, _ = trip_inputs(diary, spatial)
        names = {row[0]: trip[0] for row, trip in zip((p for p in parts if p[2] != "stop"), bouts, strict=True)}
        for home, out, stop, back, end in zip(parts, parts[1:], parts[2:], parts[3:], parts[4:]):
            if not (home[2] == stop[2] == end[2] == "stop" and slots[home[3]] == slots[end[3]] == "home"):
                continue
            for mode in MODES:
                if names.get(out[0]) != SURVEY_MODES[mode] or names.get(back[0]) != SURVEY_MODES[mode]:
                    continue
                if any(ep[3] not in allowed[mode] for ep in diary["episodes"]
                       if out[0] <= ep[0] < out[0]+out[1] or back[0] <= ep[0] < back[0]+back[1]):
                    continue
                pairs[mode].append((i, min(60, out[1]), min(60, back[1])))
    return pairs


def activity_priors(atlas, day):
    stops, pairs = donor_tours(atlas, day), travel_budget_pairs(atlas, day)
    rng = np.random.default_rng(SEED)
    priors = {}
    for purpose in PURPOSES:
        dwell = sorted({(tpl, start, duration) for mode in ("car-driver", "walk")
                        for tpl, start, _, duration, _ in stops[purpose, mode]})
        for mode in MODES:
            rows = []
            for tpl, start, duration in dwell:
                budget_tpl, there, back = pairs[mode][rng.integers(len(pairs[mode]))]
                # Store both source templates under the common donor field.
                rows.append(((tpl, budget_tpl), start, there, duration, back))
            priors[purpose, mode] = rows
    return priors, pairs


def targets_for(evidence):
    targets = {}
    for name in SURVEY_ROWS:
        model, survey = evidence["model"][name], evidence["observations"][name]
        for purpose in PURPOSES:
            weights = SHOPPING_SHARES[name] if purpose == SHOPPING else (1,)
            for mode in MODES:
                share = np.dot(SHARES[purpose][mode], weights) / sum(weights)
                estimate = survey["purposes"][purpose] * share * model["residents"] / survey["residents"]
                targets[name, purpose, mode] = (model["purposeModes"][purpose][SURVEY_MODES[mode]], round(estimate))
    return targets


class TransitOutings:
    def __init__(self, root, archive, versions, timetable, places, homes, venues):
        schedule = root/"transit"/timetable
        street = root/"streets"/versions["streets"]
        service = DirectService(schedule)
        self.service = service
        self.places = np.array([p[:2] for p in places])
        self.venues = venues
        self.trees = {purpose: cKDTree(self.places[sites]) for purpose, sites in venues.items()}
        access = access_routes(places, set(homes) | set().union(*venues.values()), service.stations, street)
        self.positions = service.accessible_positions(access)
        probes = archive/"data/raw/probes"
        self.capacity = bus_capacity_profile(service.route_manifest, probes/TABLE, probes/ANNUAL_TABLE)
        self.capacity.update(observed_spare_capacity(service.route_manifest, probes/TABLE, self.capacity["limits"]))
        spare = self.capacity["spare"]
        self.spaces = BusSpaces({route: n for route, n in spare.items() if n}, (route for route, n in spare.items() if not n))
        self.usable = {i for i, (route, *_) in enumerate(service.patterns)
                       if service.mapped[i] and route not in self.spaces.closed}
        self.latest = service.latest_departure(access, BOARDING_MARGIN_SECONDS, self.spaces.available)
        self.earliest = service.matcher(access, boarding_margin=BOARDING_MARGIN_SECONDS, mapped_only=True,
                                        available=self.spaces.available, arrival_time=True)
        self.summary = dict(release=timetable, date=service.route_manifest["date"],
                            boardingMargin=BOARDING_MARGIN_SECONDS, capacity=self.capacity,
                            routes=[{"id": r["id"], "name": r["name"]} for r in service.route_manifest["routes"]])

    @lru_cache(maxsize=6000)
    def sites(self, home, purpose):
        home_board, home_alight = (self.positions(home, b) for b in (True, False))
        if not home_board or not home_alight:
            return ()
        tree, venues = self.trees[purpose], self.venues[purpose]
        here = self.places[home]
        rings = [here + np.array(d) * radius for radius in (1500, 3500) for d in ((1, 0), (-1, 0), (0, 1), (0, -1))]
        _, indexes = tree.query([here, *rings], k=min(6, len(venues)))
        result = []
        for j in dict.fromkeys(indexes.flatten()):
            site = venues[j]
            if site == home or np.linalg.norm(here-self.places[site]) < 250:
                continue
            if (self.usable & home_board.keys() & self.positions(site, False).keys() and
                    self.usable & home_alight.keys() & self.positions(site, True).keys()):
                result.append(site)
        return tuple(result)

    def tour(self, windows, home, purpose, donors, rng):
        sites = self.sites(home, purpose)
        if not sites:
            return None
        opening, closing = HOURS[purpose]
        for j in rng.permutation(len(donors))[:12]:
            pair, preferred, go_budget, dwell, return_budget = donors[j]
            for a, b in windows:
                low, high = max(opening, a+4), min(closing-dwell, b-dwell-4)
                if low > high:
                    continue
                preferred_arrival = min(high, max(low, preferred+go_budget//2))
                attempts = dict.fromkeys((preferred_arrival, high, (low+high)//2, low))
                for k in rng.permutation(len(sites)):
                    site = sites[k]
                    for deadline in attempts:
                        outward = self.latest(deadline*60, home, site)
                        if not outward:
                            continue
                        start, reach, there = outward
                        arrive = (reach+59)//60
                        travel = arrive-start
                        if start < a or not (0 < travel <= go_budget and opening <= arrive <= high):
                            continue
                        leave = arrive+dwell
                        onward = self.earliest(leave, min(return_budget, b-leave), site, home)
                        if not onward:
                            continue
                        at_home, back = onward
                        duration = (at_home+59)//60-leave
                        if not 0 < duration <= return_budget:
                            continue
                        self.spaces.reserve(there)
                        self.spaces.reserve(back)
                        scheduled = [[*leg, *self.service.ride_times(leg)] for leg in (there, back)]
                        return site, start, travel, dwell, duration, pair, scheduled
        return None


def assign_multimodal(opportunities, chosen, access, paths, transit, donors, targets, reserved):
    rng = np.random.default_rng(SEED)
    gains = Counter()
    desired = {k: max(0, b-a) for k, (a, b) in targets.items()}
    remaining = desired.copy()
    new = []
    for n in rng.permutation(len(opportunities["residents"])):
        d, i, home, template, area, _ = opportunities["residents"][n]
        if (d, i) in chosen:
            continue
        offers = [(area, purpose, mode) for purpose in PURPOSES for mode in MODES
                  if remaining[area, purpose, mode] > 0 and (mode != "bike" or (d, i) in access)]
        if not offers:
            continue
        offers.sort(key=lambda k: -remaining[k]/desired[k])
        windows = list(available_windows(opportunities["windows"][template], reserved.get((d, i), ())))
        for key in offers:
            _, purpose, mode = key
            if mode == "bike":
                solution = place_outing(windows, paths[home, purpose], donors[purpose, mode], purpose, rng, match_times=True)
            else:
                solution = transit.tour(windows, home, purpose, donors[purpose, mode], rng)
            if solution:
                site, departure, there, dwell, back, pair, *scheduled = solution
                new.append([d, i, home, site, purpose, mode, departure, there, dwell, back, list(pair), *scheduled])
                gains[key] += 1
                remaining[key] -= 1
                break
    return new, gains


def publish(root, archive, reference, catalogue, timetable, backend):
    original = root/"discretionary-outings"/reference
    model = read(original/"report.json")
    if model.get("multimodalParent"):
        raise ValueError("Choose a walking and driving scenario as the parent")
    with catalogue.open("rb") as stream:
        if model["venueDigest"] != hashlib.file_digest(stream, "sha256").hexdigest():
            raise ValueError("The venue catalogue differs from the parent outings")
    tours = read(original/"tours.json")
    chosen = {tuple(row[:2]) for row in tours}
    versions = model["versions"]
    day_dir, atlas = root/"cityday"/versions["day"], root/"atlas"/versions["atlas"]
    day, atlas_data = read(day_dir/"day.json"), read(atlas/"atlas.json")
    places = read(day_dir/"places.json")
    evidence = read(root/"north-shore-demand"/model["demand"]/"report.json")
    venues = local_venues(catalogue, places, day["areas"])
    reserved, digest = reserved_walks(root, versions, evidence)
    if digest != model.get("reservedWalksDigest"):
        raise ValueError("The reconstructed walks differ from the parent outings")
    donors, budget_pairs = activity_priors(atlas_data, day)
    targets = targets_for(evidence)
    with tempfile.TemporaryDirectory(dir=root) as scratch:
        scratch = Path(scratch)
        opportunities = read_opportunities(atlas, day_dir, scratch, detail="with-access")
        access, counts = draw_access(opportunities["adults"])
        candidates = [r for r in opportunities["residents"] if tuple(r[:2]) not in chosen]
        print(f"Checking routes for {len(candidates):,} residents with available time.", flush=True)
        cycling = read(root/"cycling"/(versions["streets"]+".json"))["version"]
        network = read(root/"cycling"/cycling/"network.json")
        graph, snap = access_graph(network, 8, 16)
        homes = sorted({r[2] for r in candidates if tuple(r[:2]) in access})
        bike = accessible_sites(homes, venues, [p[:2] for p in places], graph, snap, 40*BIKE_SPEED,
                                500, BIKE_SPEED, radii=(2000, 4000))
        print("Checked both cycling legs on the directed graph.", flush=True)
        transit = TransitOutings(root, archive, versions, timetable, places, {r[2] for r in candidates}, venues)
        print(f"Checking outward and return rides on the {transit.summary['date']} timetable.", flush=True)
        added, gains = assign_multimodal(opportunities, chosen, access, bike, transit, donors, targets, reserved)
        tours = sorted(tours+added)
        if len({tuple(row[:2]) for row in tours}) != len(tours):
            raise ValueError("An additional outing has an occupied resident")
        clock = raster_clock(tours, places, day["occupancy"], day["areas"], scratch, backend)
    model.update(clock, attendance=len(tours), multimodalParent=reference, bicycleAccess=counts,
                 cycleProfile=dict(version=cycling, metresPerMinute=BIKE_SPEED),
                 transit=transit.summary, extraSeed=SEED,
                 modeBudgetPairs={mode: len(rows) for mode, rows in budget_pairs.items()})
    model["metrics"].extend([name, purpose, mode, *target, gains[name, purpose, mode]]
                            for (name, purpose, mode), target in targets.items())
    publish_outings(root, model, tours)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--archive", type=Path, default=Path("../Simulations/city"))
    parser.add_argument("--reference", default="a639dda90b0f9f2ebb91")
    parser.add_argument("--catalogue", type=Path, default=Path("data/region/work/places.jsonl"))
    parser.add_argument("--timetable", default=TIMETABLE)
    parser.add_argument("--backend", default="jvm")
    args = parser.parse_args()
    publish(args.region, args.archive, args.reference, args.catalogue, args.timetable, args.backend)
