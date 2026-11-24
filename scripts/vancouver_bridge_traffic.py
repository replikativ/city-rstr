"""Compare routed resident and commuter vehicles with City bridge count stations."""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import csv
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile

import duckdb
import numpy as np
from scipy.sparse.csgraph import connected_components, dijkstra

from scripts.vancouver_atlas import write_json
from scripts.vancouver_cityday import SPEED, xy
from scripts.vancouver_region import package, read
from scripts.vancouver_streets import access_graph

SOURCE = "https://vancouver.ca/streets-transportation/traffic-count-data.aspx#permanent-count-stations"
ARCHIVE = "counts_vancouver_arcgis_TCSPermanentCounts_sample.json"
SCENARIOS = ("Residents, diary", "Residents, census workplaces", "Residents, workplaces and cycling",
             "Incoming work drivers")
MAX_CONNECTOR = 500
# Local south coordinates of transects on the bridge decks. Directions are
# listed southward then northward, following the City's sensor convention.
BRIDGES = [
    ("BurrardBridge", "Burrard Bridge", -1650, ("Burrard Street Bridge",), ("Southbound", "Northbound")),
    ("GranvilleStBridge", "Granville Bridge", -1300, ("Granville Bridge",), ("Southbound", "Northbound")),
    ("CambieBridge", "Cambie Bridge", -1240, ("Cambie Street Bridge", "Cambie Bridge"),
     ("Southbound", "Northbound")),
    ("LionsGateBridge", "Lions Gate Bridge", -6400, ("Lions Gate Bridge",), ("Eastbound", "Westbound")),
]
REGIONAL_BRIDGES = [bridge for bridge in BRIDGES if bridge[0] == "LionsGateBridge"]
IRONWORKERS = ("Ironworkers", "Ironworkers Memorial Bridge", -4200,
               ("Ironworkers Memorial Second Narrows Crossing",), ("Eastbound", "Westbound"))
IRONWORKERS_FILE = "ironworkers-2025-03.csv"
IRONWORKERS_SOURCE = (
    "https://tradas.th.gov.bc.ca/reports/AllYears/2025/03/MV03/"
    "MV03P_Second%20Narrows%20P-15-2EW%20-%20NY3-2025.csv"
)
WORK_FLOWS = "vancouver_commuting_flows.jsonl"


def hour_fields():
    def clock(h):
        h %= 24
        return f"{h%12 or 12:02d}00" + ("am" if h < 12 else "pm")
    fields = [f"F_{clock(h)}_{clock(h+1)}" for h in range(24)]
    fields[10] = "F_10000am_1100am"  # published field name
    return fields


def observations(path, bridges=None):
    archive = read(path)
    rows = defaultdict(list)
    for feature in archive["features"]:
        a = feature["attributes"]
        rows[a["Screen"], a["Direction"]].append(a)
    sites = []
    for key, name, _, _, directions in BRIDGES if bridges is None else bridges:
        counters = []
        for direction in directions:
            row, = rows[key, direction]
            counts = [row[f] for f in hour_fields()]
            if not all(isinstance(n, (int, float)) and n >= 0 for n in counts):
                raise ValueError(f"Incomplete hourly counter record: {key}, {direction}")
            counters.append(dict(direction=direction, month=row["MonthMAWDTHourly"], year=row["YearMAWDTHourly"],
                                 record=row["OBJECTID"], counts=counts))
        sites.append(dict(key=key, name=name, counters=counters))
    return sites


def ironworkers_observations(path):
    with path.open(newline="") as stream:
        rows = list(csv.reader(stream))
    counters = []
    weekdays = {day for day in range(1, 32) if date(2025, 3, day).weekday() < 5}
    hours = [f"{hour:02d}:00" for hour in range(24)]
    for letter, direction in zip(("E", "W"), IRONWORKERS[-1], strict=True):
        header, = [i for i, row in enumerate(rows) if letter in row and "March 2025" in row]
        columns, = [i for i in range(header, header + 8) if rows[i][0] == hours[0]]
        if [cell for cell in rows[columns] if cell] != hours + ["Total"]:
            raise ValueError(f"Unexpected Ironworkers report columns: {direction}")
        by_day = {}
        for row in rows[columns + 1:]:
            if not row or not row[0].isdigit():
                break
            day = int(row[0])
            if day not in weekdays:
                continue
            *counts, total = [int(cell.replace(",", "")) for cell in row[1:] if cell]
            if len(counts) != 24 or day in by_day or any(n < 0 for n in counts) or sum(counts) != total:
                raise ValueError(f"Invalid Ironworkers counts for March {day}, {direction}")
            by_day[day] = counts
        if set(by_day) != weekdays:
            raise ValueError(f"Missing March 2025 weekday at Ironworkers: {direction}")
        average = [round(sum(values) / len(by_day)) for values in zip(*by_day.values(), strict=True)]
        counters.append(dict(direction=direction, month="March", year=2025,
                             days=len(by_day), counts=average))
    return dict(key=IRONWORKERS[0], name=IRONWORKERS[1], source=IRONWORKERS_SOURCE, counters=counters)


def screen_arcs(network, sites, bridges=None):
    """Match a geographic cut to road edges on each named bridge."""
    arcs = {}
    points = network["nodes"]
    for j, (_, _, cut, names, _) in enumerate(BRIDGES if bridges is None else bridges):
        centres = []
        for flags, name, chain in network["ways"]:
            if not flags & 6 or not network["names"][name].startswith(names):
                continue
            for a, b in zip(chain, chain[1:]):
                x, y = points[a]
                u, v = points[b]
                if (y < cut) == (v < cut):
                    continue
                fraction = (cut - y) / (v - y)
                centres.append(x + fraction * (u - x))
                if flags & 2:
                    arcs[a, b] = j, int(v < y), fraction
                if flags & 4:
                    arcs[b, a] = j, int(y < v), 1 - fraction
        if not centres or {d for k, d, _ in arcs.values() if k == j} != {0, 1}:
            raise ValueError(f"Missing directed bridge deck: {sites[j]['name']}")
        sites[j]["point"] = [sum(centres) / len(centres), cut]
    return arcs


def inbound_legs(root, raw, versions, places):
    directory = root / "commuters" / versions["commuters"]
    report = read(directory / "commuters.json")
    if any(report["versions"][k] != versions[k] for k in ("atlas", "day")):
        raise ValueError("Incoming workers and bridge traffic use different city releases")
    driver = report["modes"].index("Car driver")
    cohorts = [(csd, read(directory / (csd + ".json"))) for csd in report["groups"]]
    ids = sorted({d for _, cohort in cohorts for d in cohort["homes"]})
    with duckdb.connect() as db:
        db.execute("LOAD spatial")
        db.execute("create table homes (da varchar)")
        db.executemany("insert into homes values (?)", [(d,) for d in ids])
        anchors = db.execute("""with points as (
            select da, st_transform(st_pointonsurface(geom),'EPSG:3347','EPSG:4326',always_xy:=true) p
            from homes join st_read(?) s on s.DAUID=da)
            select da, st_x(p), st_y(p) from points order by da""", [str(raw / "lda_000b21a_e.shp")]).fetchall()
    if [d for d, _, _ in anchors] != ids:
        raise ValueError("Missing inbound DA geometry")
    locations = {d: i for i, d in enumerate(ids, len(places))}
    places.extend(xy(lon, lat) for _, lon, lat in anchors)
    rows = []
    for _, cohort in cohorts:
        home = [locations[d] for d in cohort["homes"]]
        for a, b, _, _, mode, start, duration, span, attend, _ in cohort["people"]:
            if mode != driver or not attend:
                continue
            rows.append((8, home[a], b, start, duration, -1, -1))
            rows.append((8, b, home[a], start + duration + span, duration, -1, -1))
    return np.asarray(rows, dtype=np.int32).reshape(-1, 7)


def trace(predecessor, origin, destination, arcs, distances, points=None):
    """Walk a chosen shortest path and report its cumulative cost at each screen."""
    path = []
    b = destination
    while b != origin:
        a = predecessor[b]
        if a < 0:
            raise ValueError("Attempted to trace an unconnected drive")
        path.append((a, b))
        b = a
    hits = []
    walked = 0
    for a, b in reversed(path):
        length = math.dist(points[a], points[b]) if points is not None else distances[b] - distances[a]
        if (a, b) in arcs:
            j, direction, fraction = arcs[a, b]
            hits.append((j, direction, walked + length * fraction))
        walked += length
    return hits


def prune_bridge_candidates(indices, via, starts, ends, graph, reverse, points):
    # A route through any hub supplies an upper bound on the unrestricted
    # shortest path. It rules out a bridge path only if strictly shorter.
    hubs = {}
    frequency = Counter(np.concatenate((starts[indices], ends[indices])))
    for node, _ in frequency.most_common():
        x, y = points[node]
        hubs.setdefault((x // 4000, y // 4000), node)
        if len(hubs) == 24:
            break
    for hub in hubs.values():
        if not len(indices):
            break
        to_hub = dijkstra(reverse, indices=hub)
        from_hub = dijkstra(graph, indices=hub)
        upper = to_hub[starts[indices]] + from_hub[ends[indices]]
        indices = indices[upper + 1e-6 >= via[indices]]
    return indices


def score_window(legs, places, network, sites, das, *, bridges=None, scenarios=len(SCENARIOS), evidence=None,
                 required_crossing=None, profile=None, slowdowns=None, required_samples=None, minute_counts=False,
                 arcs=None, elapsed=False):
    if arcs is None:
        arcs = screen_arcs(network, sites, bridges)
    graph, snap = access_graph(network, 2, 4, speeds=profile["kmh"] if profile else None, slowdowns=slowdowns)
    places = np.asarray(places)
    nodes, offsets = snap(places, lowest_id_on_ties=True)
    masks, origins, destinations, _, durations, _, _ = legs.T
    located = (origins >= 0) & (destinations >= 0)
    max_connector = profile["connectorMetres"] if profile else MAX_CONNECTOR
    snapped = located & (offsets[origins] <= max_connector) & (offsets[destinations] <= max_connector)
    if elapsed:
        snapped &= np.any(places[origins] != places[destinations], axis=1)
    cost_per_minute = 1 if profile else SPEED["car-driver"]
    connector_speed = profile["connectorKmh"] * 1000/60 if profile else SPEED["car-driver"]
    costs = offsets * (cost_per_minute / connector_speed)
    starts, ends = nodes[origins], nodes[destinations]
    connector = costs[origins] + costs[destinations]
    reverse = graph.T.tocsr()
    via = np.full(len(legs), np.inf)
    if profile:
        best = np.full(len(legs), -1, dtype=int)
        crossing_cost = np.zeros(len(legs))
    for arc, ((a, b), (_, _, fraction)) in enumerate(arcs.items()):
        prefix = dijkstra(reverse, indices=a)
        suffix = dijkstra(graph, indices=b)
        edge_cost = graph[a, b]
        through = prefix[starts] + edge_cost + suffix[ends]
        if profile:
            better = through < via-1e-8
            tied = np.isfinite(through) & (through <= via+1e-8) & ~better
            best[tied] = -1
            best[better] = arc
            crossing_cost[better] = prefix[starts[better]] + fraction * edge_cost
        via = np.minimum(via, through)
    possible = snapped & (via + connector <= durations*cost_per_minute)
    if required_crossing is not None or profile:
        cut = graph.copy()
        for a, b in arcs:
            cut[a, b] = 0
        cut.eliminate_zeros()
        _, component = connected_components(cut, directed=False)
        required = snapped & np.isfinite(via) & (component[starts] != component[ends])
        if required_crossing is not None:
            required_crossing.update(legs=int(required.sum()), fits=int((required & possible).sum()))
            if required.any():
                times = (via[required] + connector[required]) / cost_per_minute
                required_crossing["medianRoadMinutes"] = float(np.median(times))
                required_crossing["medianDiaryMinutes"] = float(np.median(durations[required]))
                if required_samples is not None:
                    required_samples.append(np.column_stack((times, durations[required])))
        del cut, component
    # Every path for these trips uses some screen edge. The cheapest candidate
    # is therefore globally shortest. Every screen on any tied shortest path
    # would also attain that same minimum, so only settle unique screen edges.
    resolved = required & possible & (best >= 0) if profile else np.zeros(len(legs), dtype=bool)
    ii = np.flatnonzero(possible & ~resolved)
    # Search by the more frequent endpoint. An admitted bridge path provides
    # an upper bound on the distance needed to find the unconstrained route.
    from_counts = Counter(starts[ii])
    to_counts = Counter(ends[ii])
    if min(len(from_counts), len(to_counts)) > 48:
        ii = prune_bridge_candidates(ii, via, starts, ends, graph, reverse, network["nodes"])
    groups = defaultdict(list)
    for i in ii:
        a, b = starts[i], ends[i]
        rev = from_counts[a] < to_counts[b]
        groups[rev, b if rev else a].append(i)
    print(f"Checking {len(ii):,} possible passages with {len(groups):,} shortest-path searches.", flush=True)
    counts = np.zeros((scenarios, len(sites), 2, 24), dtype=int)
    minutes = np.zeros((scenarios, len(sites), 2, 1440), dtype=int) if minute_counts else None
    if evidence:
        homes, purposes, across, direct = evidence
        attributed = np.zeros((len(sites), 2, 24, 3, 3), dtype=int)
        passed = np.zeros(len(legs), dtype=bool)
    examples = {}

    def register(i, j, direction, along, total):
        mask, a, _, start, duration, da, person = legs[i]
        minute = start + (costs[a] + along)/cost_per_minute if elapsed else start + duration*(costs[a] + along)/total
        hour = int(minute // 60) % 24
        if evidence:
            passed[i] = True
            attributed[j, direction, hour, homes[da], purposes[i]] += 1
        for s in range(scenarios):
            if mask & (1 << s):
                counts[s, j, direction, hour] += 1
                if minute_counts:
                    minutes[s, j, direction, (int(minute)-240) % 1440] += 1
                if da >= 0:
                    example = [das[da], int(person), minute]
                    if elapsed:
                        example.extend([int(start), int(duration), int(a), int(legs[i, 2])])
                    examples.setdefault((s, j, direction, hour), example)

    if profile:
        screens = list(arcs.values())
        for i in np.flatnonzero(resolved):
            j, direction, _ = screens[best[i]]
            register(i, j, direction, crossing_cost[i], via[i] + connector[i])
    reversed_arcs = {(b, a): (j, direction, 1 - f) for (a, b), (j, direction, f) in arcs.items()}
    for (rev, origin), indices in sorted(groups.items()):
        dist, pred = dijkstra(reverse if rev else graph, indices=origin, limit=via[indices].max()+1e-6,
                              return_predecessors=True)
        cache = {}
        for i in indices:
            end = starts[i] if rev else ends[i]
            if end == origin or dist[end]+1e-6 < via[i]:
                continue
            if end not in cache:
                cache[end] = trace(pred, origin, end, reversed_arcs if rev else arcs, dist,
                                   None if profile else network["nodes"])
            total = dist[end] + connector[i]
            for j, direction, along in cache[end]:
                if rev:
                    along = dist[end] - along
                register(i, j, direction, along, total)
    coverage = []
    for s in range(scenarios):
        cohort = (masks & (1 << s)) != 0
        coverage.append({k: int(np.count_nonzero(cohort & test)) for k, test in
                         (("legs", True), ("located", located), ("snapped", snapped), ("possibleBridge", possible))})
    for j, site in enumerate(sites):
        site["scenarios"] = [dict(counts=counts[s, j].tolist(),
                                  examples=[[examples.get((s, j, direction, h)) for h in range(24)]
                                            for direction in range(2)]) for s in range(scenarios)]
        if minute_counts:
            for s, scenario in enumerate(site["scenarios"]):
                scenario["minutes"] = minutes[s, j].tolist()
        if evidence:
            if not np.array_equal(attributed[j].sum(axis=(2, 3)), counts[0, j]):
                raise ValueError("Bridge crossing categories do not reconcile to routed traffic")
            site["byHomePurpose"] = attributed[j].tolist()
    if evidence:
        departure_hour = (legs[:, 3] // 60) % 24
        for direction, selected in enumerate(across):
            direct[direction] = {key: np.bincount(departure_hour[selected & flags], minlength=24).tolist()
                                 for key, flags in (("assigned", True), ("fits", possible), ("routed", passed))}
    return coverage, len(groups)


def score(legs, places, network, sites, das, *, bridges=None, scenarios=len(SCENARIOS), evidence=None,
          required_crossing=None, profile=None, minute_counts=False):
    args = dict(bridges=bridges, scenarios=scenarios, profile=profile, minute_counts=minute_counts)
    if not profile or "hourly" not in profile:
        return score_window(legs, places, network, sites, das, evidence=evidence,
                            required_crossing=required_crossing, **args)
    service = profile["hourly"]
    bins = (legs[:, 3] // 60) % 24
    hours = service["hours"]
    total, searches, required_times = [Counter() for _ in range(scenarios)], 0, []
    combined = None
    for column, hour in enumerate([*hours, None]):
        active = bins == hour if hour is not None else ~np.isin(bins, hours)
        if not np.any(active):
            continue
        slowdowns = {tuple(arc): corridor["factors"][column]
                     for corridor in service["corridors"] for arc in corridor["arcs"]} if hour is not None else None
        subset = deepcopy(sites)
        required = {} if required_crossing is not None else None
        detail = None
        if evidence:
            homes, purposes, directions, direct = evidence
            stages = [{}, {}]
            detail = homes, purposes[active], [d[active] for d in directions], stages
        coverage, n = score_window(legs[active], places, network, subset, das, evidence=detail,
                                   required_crossing=required, required_samples=required_times,
                                   slowdowns=slowdowns, **args)
        searches += n
        for counter, row in zip(total, coverage, strict=True):
            counter.update(row)
        if required_crossing is not None:
            for key in ("legs", "fits"):
                required_crossing[key] = required_crossing.get(key, 0) + required[key]
        if detail:
            for complete, stage in zip(direct, stages, strict=True):
                for key, counts in stage.items():
                    complete[key] = (np.asarray(complete.get(key, 0)) + counts).tolist()
        if combined is None:
            combined = subset
            continue
        for a, b in zip(combined, subset, strict=True):
            for first, second in zip(a["scenarios"], b["scenarios"], strict=True):
                first["counts"] = (np.asarray(first["counts"]) + second["counts"]).tolist()
                if minute_counts:
                    first["minutes"] = (np.asarray(first["minutes"]) + second["minutes"]).tolist()
                first["examples"] = [[x or y for x, y in zip(d1, d2, strict=True)]
                                     for d1, d2 in zip(first["examples"], second["examples"], strict=True)]
            if detail:
                a["byHomePurpose"] = (np.asarray(a["byHomePurpose"]) + b["byHomePurpose"]).tolist()
    if combined is None:
        return score_window(legs, places, network, sites, das, evidence=evidence,
                            required_crossing=required_crossing, **args)
    sites[:] = combined
    if required_times:
        medians = np.median(np.concatenate(required_times), axis=0)
        required_crossing.update(medianRoadMinutes=float(medians[0]), medianDiaryMinutes=float(medians[1]))
    return [dict(row) for row in total], searches


def add_incoming(report, root, places, incoming):
    versions = report["versions"]
    regional = root/"region"
    versions["incomingStreets"] = read(regional/"current.json")["streets"]
    network = read(regional/"streets"/versions["incomingStreets"]/"network.json")
    print(f"Routing {len(incoming):,} incoming work legs on the Metro Vancouver graph.", flush=True)
    sites = [dict(name=s["name"]) for s in report["sites"]]
    coverage, searches = score(incoming, places, network, sites, [])
    for city, metro in zip(report["sites"], sites, strict=True):
        city["scenarios"][3] = metro["scenarios"][3]
    report["incomingCityCoverage"] = report["coverage"][3]
    report["coverage"][3] = coverage[3]
    report["incomingSearches"] = searches


def publish_report(root, report):
    versions = report["versions"]
    key = "_".join(versions[k] for k in ("atlas", "day", "streets"))
    if routing := report.get("routing"):
        key += "_" + routing["metric"]
    release = package(root, "bridge-traffic", lambda folder: write_json(folder/"counts.json", report))
    parent = root/"bridge-traffic"
    with tempfile.TemporaryDirectory(dir=parent) as tmp:
        pointer = Path(tmp)/"pointer.json"
        write_json(pointer, {"version": release})
        pointer.replace(parent/(key+".json"))
    print(release, report["coverage"], flush=True)


def resident_legs(root, versions, *, detailed=False, fitted=False):
    with tempfile.TemporaryFile(mode="w+") as out:
        cmd = ["node", "scripts/vancouver_bridge_legs.mjs", root]
        if fitted:
            cmd.append("--fitted")
        elif detailed:
            cmd.append("--templates")
        subprocess.run(cmd,
                       input=json.dumps(versions), stdout=out, text=True, check=True)
        out.seek(0)
        return np.loadtxt(out, delimiter=",", dtype=np.int32, ndmin=2)


def report_fields(source, versions):
    return dict(versions=versions, source=SOURCE, sourceFile=ARCHIVE, sourceDigest=hashlib.sha256(source.read_bytes()).hexdigest(),
                connectorMetres=MAX_CONNECTOR, speed=SPEED["car-driver"])


def road_profile(root, streets, metric="time"):
    path = root/"drive-profile"/(streets + ("_highway1" if metric == "highway1" else "") + ".json")
    profile = read(path)
    if profile["streets"] != streets:
        raise ValueError("Road speeds and bridge benchmark use different streets")
    metadata = dict(metric=metric, profileDigest=hashlib.sha256(path.read_bytes()).hexdigest(),
                    profileSource=profile["sourceDigest"])
    if metric == "highway1":
        study = profile["hourly"]
        baseline = root/"drive-profile"/(streets+".json")
        if hashlib.sha256(baseline.read_bytes()).hexdigest() != study["baselineDigest"]:
            raise ValueError("Highway 1 speeds use a different free-flow graph")
        metadata.update({key: study[key] for key in ("baselineDigest", "year", "hours", "source", "studyDigest")})
        metadata["corridors"] = [{k: c[k] for k in ("name", "start", "end", "freeMinutes", "observedMinutes", "factors")}
                                 for c in study["corridors"]]
    return profile, metadata


def publish_region(archive, root, ironworkers, weekday_versions=None, *, road_speeds=False, observed_highway1=False):
    regional = root/"region"
    current = weekday_versions or read(regional/"current.json")
    versions = {key: current[key] for key in ("atlas", "day", "streets")}
    source = archive/"data/raw/probes"/ARCHIVE
    bridges = [*REGIONAL_BRIDGES, IRONWORKERS]
    sites = [*observations(source, REGIONAL_BRIDGES), ironworkers_observations(ironworkers)]
    day = regional/"cityday"/versions["day"]
    venues = read(day/"places.json")
    places = [p[:2] for p in venues]
    network = read(regional/"streets"/versions["streets"]/"network.json")
    metric = "highway1" if observed_highway1 else "time" if road_speeds else None
    profile, routing = road_profile(regional, versions["streets"], metric) if metric else (None, None)
    atlas = regional/"atlas"/versions["atlas"]
    flows = archive/"data/derived"/WORK_FLOWS
    with tempfile.TemporaryDirectory() as tmp:
        context = Path(tmp)/"regional.json"
        subprocess.run(["clojure", "-M", "-m", "city.vancouver.bridge-evidence", atlas, day, flows, context], check=True)
        evidence = read(context)
    residents = resident_legs(regional, versions, detailed=True)
    trips = np.zeros((len(evidence["templates"]), 1440), dtype=np.uint8)
    for i, entries in enumerate(evidence.pop("templates")):
        for minute, purpose in entries:
            trips[i, minute] = purpose
    purposes = trips[residents[:, 7], residents[:, 3]-240]
    places_area = np.array([p[2] for p in venues])
    weekday = read(day/"day.json")
    north = np.array(["North Vancouver" in area or area == "West Vancouver" for area in weekday["areas"]])
    a, b = residents[:, 1], residents[:, 2]
    area_a, area_b = places_area[a], places_area[b]
    direct = (purposes == 1) & (a >= 0) & (b >= 0) & (area_a >= 0) & (area_b >= 0)
    toward_city = direct & north[area_a] & ~north[area_b]
    toward_north = direct & ~north[area_a] & north[area_b]
    stages = [{}, {}]
    print(f"Checking both Burrard Inlet bridges for {len(residents):,} regional resident driving legs.", flush=True)
    coverage, searches = score(residents[:, :7], places, network, sites, weekday["das"], bridges=bridges, scenarios=1,
                              evidence=(evidence.pop("homeCodes"), purposes, [toward_city, toward_north], stages),
                              profile=profile)
    evidence["directWorkDriving"] = stages
    evidence["workSource"] = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810045901"
    evidence["workDigest"] = hashlib.sha256(flows.read_bytes()).hexdigest()
    report = dict(**report_fields(source, versions), searches=searches,
                  ironworkersDigest=hashlib.sha256(ironworkers.read_bytes()).hexdigest(),
                  labels=["Regional residents, diary"], coverage=coverage, sites=sites, evidence=evidence)
    if routing:
        report.update(routing=routing, connectorMetres=profile["connectorMetres"])
    publish_report(regional, report)


def publish(archive, root):
    city = read(root/"cityday/current.json")
    version = dict(atlas=city["atlas"], day=city["version"], streets=read(root/"streets/current.json")["version"])
    pair = city["atlas"] + "_" + city["version"]
    def resolve(family, key):
        return read(root/family/(key+".json"))["version"]
    version["outbound"] = resolve("outbound", pair)
    version["worksites"] = resolve("worksites", version["outbound"])
    version["tracts"] = resolve("tract-workplaces", version["worksites"])
    version["commuters"] = resolve("commuters", pair)
    cycling = resolve("cycling", version["streets"])
    version["tours"] = resolve("cycle-tours", "_".join((pair, version["streets"], cycling)))
    raw = archive/"data/raw"
    source = raw/"probes"/ARCHIVE
    sites = observations(source)
    day_dir = root/"cityday"/version["day"]
    places = [p[:2] for p in read(day_dir/"places.json")]
    network = read(root/"streets"/version["streets"]/"network.json")
    residents = resident_legs(root, version)
    incoming = inbound_legs(root, raw/"statcan", version, places)
    print(f"Routing {len(residents):,} resident records and testing city graph coverage for {len(incoming):,} incoming work legs.",
          flush=True)
    coverage, searches = score(np.vstack((residents, incoming)), places, network, sites, read(day_dir/"day.json")["das"])
    del residents, network
    report = dict(**report_fields(source, version), searches=searches,
                  labels=SCENARIOS, coverage=coverage, sites=sites)
    add_incoming(report, root, places, incoming)
    publish_report(root, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--region", action="store_true", help="compare Lions Gate with the regional resident weekday")
    routing = parser.add_mutually_exclusive_group()
    routing.add_argument("--road-speeds", action="store_true", help="use the versioned regional driving speed profile")
    routing.add_argument("--observed-highway1", action="store_true", help="use the 2022 Highway 1 travel-time study")
    parser.add_argument("--day", help="select an existing regional weekday paired with the current atlas")
    parser.add_argument("--ironworkers", type=Path, default=Path("data/mobility")/IRONWORKERS_FILE)
    args = parser.parse_args()
    if not args.region and (args.road_speeds or args.observed_highway1 or args.day):
        parser.error("Road-speed scenarios and --day require --region")
    if args.region:
        versions = None
        if args.day:
            versions = {**read(args.data/"region/current.json"), "day": args.day}
        publish_region(args.archive, args.data, args.ironworkers, weekday_versions=versions,
                       road_speeds=args.road_speeds, observed_highway1=args.observed_highway1)
    else:
        publish(args.archive, args.data)
