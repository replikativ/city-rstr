"""Supply complete dated service and OSM street walks for regional commuters."""
from collections import defaultdict
from datetime import date
import hashlib
import json
import math

import duckdb
import numpy as np
from scipy.sparse.csgraph import dijkstra

from scripts.vancouver_atlas import write_json
from scripts.vancouver_campus import ACCESS_METRES, WALK_METRES_PER_SECOND
from scripts.vancouver_cityday import ORIGIN, SCALE
from scripts.vancouver_region import package, read
from scripts.vancouver_streets import encode_way, permissions, walk_graph
from scripts.vancouver_transit import build as build_timetable
from scripts.vancouver_transit_load import ride_legs


def full_timetable(root, feed, baseline):
    old = read(baseline / "transit.json")
    with feed.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != old["feedDigest"]:
            raise ValueError("The expanded timetable must use the same GTFS archive as the resident run")
    return package(root, "transit", lambda out: build_timetable(feed, None, date.fromisoformat(old["date"]), out,
                                                                passenger_rules=True, transfer_rules=True))


def vehicle_signatures(data):
    def signature(pattern):
        stops = [data["stopIds"][i] for i in pattern["stops"]]
        coords = [data["stations"][i] for i in pattern["stops"]]
        encoded = json.dumps([stops, coords, pattern["access"], pattern["line"], pattern["dist"], pattern["mapped"]],
                             separators=(",", ":"), ensure_ascii=False).encode()
        return hashlib.sha256(encoded).digest()

    patterns = [signature(pattern) for pattern in data["patterns"]]
    groups = defaultdict(list)
    for run, (pattern, start, times, destination) in enumerate(data["rides"]):
        groups[patterns[pattern], start, tuple(times), destination].append(run)
    return groups


def carry_bookings(original, expanded, bookings):
    """Translate resident run indexes without changing the vehicles or stops they reserved."""
    old, new = (read(folder / "transit.json") for folder in (original, expanded))
    if any(old[k] != new[k] for k in ("date", "feed", "feedDigest")):
        raise ValueError("Booking translation requires the same dated timetable and GTFS source")
    routes = {row["id"]: row for row in new["routes"]}
    index = {}
    for route in old["routes"]:
        rid = route["id"]
        if any(routes[rid][k] != v for k, v in route.items() if k != "trips"):
            raise ValueError(f"Expanded transit changed route {rid}")
        a, b = (vehicle_signatures(read(folder / f"{rid}.json")) for folder in (original, expanded))
        index[rid] = {}
        for key, runs in a.items():
            # Identical runs share all stops and therefore have the same geographic selection.
            for i, j in zip(runs, b.get(key, ()), strict=True):
                index[rid][i] = j
    return [(rid, index[rid][run], board, alight) for rid, run, board, alight in bookings]


def walking_bounds(positions):
    coords = np.asarray(positions, dtype=float)
    lo = (coords.min(axis=0) - ACCESS_METRES - 2) / SCALE + ORIGIN
    hi = (coords.max(axis=0) + ACCESS_METRES + 2) / SCALE + ORIGIN
    return [float(lo[0]), float(hi[1]), float(hi[0]), float(lo[1])]


def road_sections(pbf, bounds):
    west, south, east, north = bounds
    with duckdb.connect() as db:
        db.execute("load spatial")
        db.execute("set threads=3")
        db.execute("""create temp table points as select id,lon,lat from st_readosm(?)
                      where kind='node' and lon between ? and ? and lat between ? and ?""",
                   [str(pbf), west, east, south, north])
        db.execute("""create temp table roads as select id,tags,refs from st_readosm(?)
                      where kind='way' and tags['highway'] is not null""", [str(pbf)])
        cursor = db.execute("""with inside as (
                 select r.id, n.ref, n.i, p.lon, p.lat
                 from roads r cross join unnest(r.refs) with ordinality n(ref,i) join points p on p.id=n.ref
               ), sections as (
                 select id, ref, i, lon, lat, i - row_number() over (partition by id order by i) as gap
                 from inside
               ), paths as (
                 select id, gap, list(ref order by i) as refs, list(lon order by i) as xs, list(lat order by i) as ys
                 from sections group by id,gap having count(*)>1
               ) select roads.tags,paths.refs,paths.xs,paths.ys from paths join roads using(id) order by paths.id,paths.gap""")
        while records := cursor.fetchmany(2000):
            yield from records


def publish_walks(root, pbf, positions):
    bounds = walking_bounds(positions)

    def build(out):
        nodes, ways, ids, names = [], [], {}, {}
        for tags, refs, lons, lats in road_sections(pbf, bounds):
            if not permissions(tags) & 1:
                continue
            way = dict(tags=tags, nodes=refs, geometry=[dict(lon=x, lat=y) for x, y in zip(lons, lats, strict=True)])
            ways.append(encode_way(way, 1, nodes, ids, names))
        if not ways:
            raise ValueError("The OSM archive does not cover the commuter walks")
        write_json(out / "network.json", dict(nodes=nodes, ways=ways, names=list(names)))
        with pbf.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        write_json(out / "report.json", dict(bounds=bounds, nodes=len(nodes), ways=len(ways), sourceDigest=digest))
        print(f"Built {len(ways):,} walkable OSM sections", flush=True)

    return package(root, "commuter-walk", build)


def passenger_walks(network, service, places, rows):
    """Reconstruct the bounded street walks using the published snapped nodes and duration."""
    graph, snap = walk_graph(network)
    options = defaultdict(set)
    by_ride = {}

    def platform(route, run, pos):
        return service.ride_platforms[route][run][pos]

    for row in rows:
        group, person, start, _, a, b, route, run, board, alight, access, egress = row[:12]
        last_route, last_run, _, last_alight = list(ride_legs(row[6:]))[-1]
        first, last = (platform(route, run, board), a, access), (platform(last_route, last_run, last_alight), b, egress)
        for stop, place, duration in (first, last):
            options[stop].add((place, duration))
        by_ride[group, person, start] = first, last

    endpoints = sorted({place for pairs in options.values() for place, _ in pairs})
    if not endpoints:
        return {}
    nodes, offsets = snap([places[p][:2] for p in endpoints], lowest_id_on_ties=True)
    anchors = dict(zip(endpoints, zip(nodes, offsets)))
    stations, station_offsets = snap(service.stations, lowest_id_on_ties=True)
    paths = {}
    for stop, pairs in options.items():
        source, offset = stations[stop], station_offsets[stop]
        length, previous = dijkstra(graph, indices=source, limit=ACCESS_METRES-offset, return_predecessors=True)
        for place, duration in pairs:
            dest, distance = anchors[place]
            total = (offset + length[dest]) + distance
            if total > ACCESS_METRES or math.ceil(total / WALK_METRES_PER_SECOND) != duration:
                raise ValueError("Playback walk and access assignment differ")
            path = [dest]
            while path[-1] != source:
                path.append(previous[path[-1]])
            points = [list(service.stations[stop]), *(network["nodes"][i] for i in reversed(path)), places[place][:2]]
            paths[stop, place, duration] = [p for i, p in enumerate(points) if i == 0 or p != points[i-1]]

    result = defaultdict(list)
    for (group, person, start), (first, last) in by_ride.items():
        result[group].append([person, start, paths[first][::-1], paths[last]])
    return result
