"""Count scheduled buses and the additional vehicles in a playable regional weekday."""
import argparse
from bisect import bisect_left
import math
from pathlib import Path
import tempfile

import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_bridge_traffic import IRONWORKERS, REGIONAL_BRIDGES, road_profile, score, screen_arcs
from scripts.vancouver_region import package, read
from scripts.vancouver_transit_commutes import pointer

BRIDGES = (*REGIONAL_BRIDGES, IRONWORKERS)
SCREEN_WIDTH = 50  # metres either side of a named deck's centre at the cut
LAYERS = ("discretionary-outings", "eastern-outings", "school-escorts", "weekday-attendance")


def crossings(line, axis, screens, east_screens=()):
    for a, b, start, end in zip(line[:-1], line[1:], axis[:-1], axis[1:], strict=True):
        x, y = a
        u, v = b
        for j, (centre, cut) in enumerate(screens):
            if (y < cut) == (v < cut):
                continue
            f = (cut-y) / (v-y)
            if abs(x + f*(u-x) - centre) <= SCREEN_WIDTH:
                yield j, int(v < y), start + f*(end-start)
        for j, (cut, centre) in enumerate(east_screens, len(screens)):
            if (x < cut) == (u < cut):
                continue
            f = (cut-x) / (u-x)
            if abs(y + f*(v-y) - centre) <= SCREEN_WIDTH:
                yield j, int(u < x), start + f*(end-start)


def bins(count=len(BRIDGES)):
    return [{"counts": [[0]*24 for _ in range(2)], "examples": [[None]*24 for _ in range(2)],
             "minutes": [[0]*1440 for _ in range(2)]} for _ in range(count)]


def record(sites, bridge, direction, minute, example):
    if 240 <= minute < 1680:
        site, hour = sites[bridge], int(minute//60) % 24
        site["counts"][direction][hour] += 1
        site["minutes"][direction][int(minute)-240] += 1
        if site["examples"][direction][hour] is None:
            site["examples"][direction][hour] = [*example, round(minute, 6)]


def stop_leg(stops, distance):
    """Find the moving leg containing a distance on a scheduled shape."""
    next_stop = bisect_left(stops, distance)
    if 0 < next_stop < len(stops):
        previous = next_stop-1
        span = stops[next_stop]-stops[previous]
        if span > 0:
            return previous, (distance-stops[previous])/span
    return None


def buses(folder, screens, east_screens=()):
    manifest = read(folder/"transit.json")
    if not all("type" in route for route in manifest["routes"]):
        raise ValueError("The crossing report requires a timetable with GTFS route types")
    sites, used, skipped = bins(len(screens)+len(east_screens)), set(), 0
    for route in manifest["routes"]:
        if route["type"] != 3:
            continue
        data = read(folder/(route["id"]+".json"))
        patterns = []
        for pattern in data["patterns"]:
            line = pattern["line"]
            if not pattern["mapped"]:
                skipped += 1
                patterns.append([])
                continue
            axis = [0]
            for a, b in zip(line, line[1:]):
                axis.append(axis[-1] + math.dist(a, b))
            hits = []
            for j, direction, distance in crossings(line, axis, screens, east_screens):
                leg = stop_leg(pattern["dist"], distance)
                if leg is not None:
                    hits.append((j, direction, *leg))
            patterns.append(hits)
        for pattern, first, times, *_ in data["rides"]:
            for j, direction, stop, f in patterns[pattern]:
                departure, arrival = times[stop*2+1:stop*2+3]
                minute = (first + departure + f*(arrival-departure))/60
                record(sites, j, direction, minute, (route["id"], route["name"]))
                if 240 <= minute < 1680:
                    used.add(route["name"])
    return dict(date=manifest["date"], feedDigest=manifest["feedDigest"], routes=sorted(used),
                unmappedPatterns=skipped, sites=sites)


def timed_cars(folder, report, layer, screens, das):
    sites, legs = bins(), 0
    for da in report["areas"]:
        for row in read(folder/(da+".json")):
            d, person = row[:2]
            if das[d] != da:
                raise ValueError("A bridge layer uses a different resident roster")
            if layer == "school-escorts":
                _, _, _, _, _, mode, _, start, there, handoff, _, go, back, _ = row
                leave = start + there + handoff
            else:
                _, _, _, _, mode, start, _, leave, _, go, back, *_ = row
            if mode != "car-driver":
                continue
            for at, (line, axis) in ((start, go), (leave, back)):
                legs += 1
                for j, direction, offset in crossings(line, axis, screens):
                    record(sites, j, direction, at+offset, (da, person))
    return dict(legs=legs, sites=sites)


def outing_cars(directory, graph, venues, profile, das):
    rows = []
    for d, person, home, place, _, mode, start, there, dwell, back, *_ in read(directory/"tours.json"):
        if mode == "car-driver":
            rows.extend(((1, home, place, start, there, d, person),
                         (1, place, home, start+there+dwell, back, d, person)))
    if not rows:
        return dict(legs=0, sites=bins())
    sites = [{"name": name} for _, name, *_ in BRIDGES]
    score(np.asarray(rows), venues, graph, sites, das, bridges=BRIDGES, scenarios=1, profile=profile, minute_counts=True)
    return dict(legs=len(rows), sites=[s["scenarios"][0] for s in sites])


def publish(root, workplace_run):
    workplace = read(root/"regional-workplaces"/workplace_run/"report.json")
    versions = {**workplace["versions"], "day": workplace["day"], "transit": workplace["timetable"]}
    parents = {k: versions[k] for k in ("atlas", "day", "streets")}
    population_key = "_".join((versions["atlas"], versions["day"]))
    key = population_key + "_" + versions["streets"]
    streets = read(root/"streets"/versions["streets"]/"network.json")
    day_dir = root/"cityday"/versions["day"]
    das = read(day_dir/"day.json")["das"]
    venues = [p[:2] for p in read(day_dir/"places.json")]
    sites = [{"name": name} for _, name, *_ in BRIDGES]
    screen_arcs(streets, sites, BRIDGES)
    screens = [site["point"] for site in sites]
    profile, roads = road_profile(root, versions["streets"], "time")
    schedule = buses(root/"transit"/versions["transit"], screens)
    layers = {}
    for layer in LAYERS:
        folder = root/layer
        index = folder/((population_key if layer == "discretionary-outings" else key)+".json")
        if not index.exists():
            continue
        release = read(index)["version"]
        directory = folder/release
        report = read(directory/"report.json")
        if any(report["versions"][k] != v for k, v in parents.items()):
            raise ValueError(f"Mismatched simulation inputs for {layer}")
        evidence = report.get("roadProfile", report.get("roads"))
        if evidence["profileDigest"] != roads["profileDigest"]:
            raise ValueError(f"Mismatched road speeds for {layer}")
        if layer in ("discretionary-outings", "eastern-outings"):
            if layer == "eastern-outings" and report["basePlaces"] != len(venues):
                raise ValueError("Eastern errands use a different inventory of places")
            additions = [p[:2] for p in report.get("sites", ())] if layer == "eastern-outings" else []
            counts = outing_cars(directory, streets, [*venues, *additions], profile, das)
        else:
            counts = timed_cars(directory, report, layer, screens, das)
        counts.update(release=release)
        layers[layer] = counts
    report = dict(schema=1, versions=versions, workplaceRun=workplace_run, roads=roads,
                  bridges=[b[0] for b in BRIDGES], buses=schedule, layers=layers)
    family = "bridge-layers"
    version = package(root, family, lambda out: write_json(out/"counts.json", report))
    pointer(root/family/(key+".json"), {"version": version})
    for name, part in [("scheduled buses", schedule), *layers.items()]:
        print(name, [sum(map(sum, site["counts"])) for site in part["sites"]], flush=True)
    print(version, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--workplace-run", default="06c504c638de40f775a7")
    args = parser.parse_args()
    publish(args.region, args.workplace_run)
