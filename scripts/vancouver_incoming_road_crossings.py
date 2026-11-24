"""Count the actual timed passages of incoming work drivers through city and road screens."""
import argparse
from collections import Counter
import hashlib
from pathlib import Path

from matplotlib.path import Path as Polygon
import numpy as np

from scripts.vancouver_bridge_traffic import ARCHIVE, BRIDGES as CITY_BRIDGES, IRONWORKERS, IRONWORKERS_FILE, SOURCE, ironworkers_observations, observations, screen_arcs
from scripts.vancouver_cityday import ORIGIN, SCALE
from scripts.vancouver_incoming_drives import driving_legs
from scripts.vancouver_region import read
from scripts.vancouver_transit_commutes import pointer
from scripts.vancouver_workplace_drives import score


CITY_LIMIT_SOURCE = "https://opendata.vancouver.ca/explore/dataset/city-boundary/table/"
BRIDGES = [*CITY_BRIDGES, IRONWORKERS, ("OakStBridge", "Oak Street Bridge", 6900, ("Oak Street Bridge",), ("Southbound", "Northbound"))]
EAST = [
    ("Adanac@Boundary", "Adanac Street near Boundary", "Adanac Street"),
    ("22nd@Boundary", "East 22nd Avenue near Boundary", "East 22nd Avenue"),
    ("29th@Boundary", "East 29th Avenue near Boundary", "East 29th Avenue"),
    ("Kingsway@Boundary", "Kingsway near Boundary", "Kingsway"),
    ("45th@Boundary", "East 45th Avenue near Boundary", "East 45th Avenue"),
    ("49th@Boundary", "East 49th Avenue near Boundary", "East 49th Avenue"),
]


def city_ring(file):
    features = read(file)["features"]
    pieces = [list(map(tuple, path)) for f in features for path in f["geometry"]["coordinates"]]
    line = pieces.pop()
    while pieces:
        for i, part in enumerate(pieces):
            if line[-1] == part[0]:
                line.extend(part[1:])
            elif line[-1] == part[-1]:
                line.extend(part[-2::-1])
            else:
                continue
            pieces.pop(i)
            break
        else:
            raise ValueError("The legal city line does not form one closed boundary")
    if line[0] != line[-1]:
        raise ValueError("The legal city line has open endpoints")
    return (np.asarray(line)-ORIGIN)*SCALE


def cross(a, b):
    return a[..., 0]*b[..., 1]-a[..., 1]*b[..., 0]


class Cordon:
    def __init__(self, ring, graph_points, addresses):
        self.vertices = ring[:-1]
        self.edges = np.diff(ring, axis=0)
        region = Polygon(ring)
        self.nodes_inside = region.contains_points(graph_points)
        self.places_inside = region.contains_points(addresses)

    def crossing(self, a, b, entering):
        segment = np.asarray(b)-a
        delta = self.vertices-a
        determinant = cross(segment, self.edges)
        usable = determinant != 0
        t = cross(delta[usable], self.edges[usable])/determinant[usable]
        u = cross(delta[usable], segment)/determinant[usable]
        intersections = t[(t >= -1e-9) & (t <= 1+1e-9) & (u >= -1e-9) & (u <= 1+1e-9)]
        if not len(intersections):
            return None
        return float(np.clip((max if entering else min)(intersections), 0, 1))


def east_arcs(network, sites, first):
    nodes, names = network["nodes"], network["names"]
    result = {}
    cut = 5520
    for i, (_, _, street) in enumerate(EAST, first):
        crossings = []
        for flags, name, path in network["ways"]:
            if names[name] != street:
                continue
            for a, b in zip(path, path[1:]):
                x,y = nodes[a]
                u,v = nodes[b]
                if (x < cut) == (u < cut):
                    continue
                t = (cut-x)/(u-x)
                crossings.append(y+t*(v-y))
                if flags & 2:
                    result[a,b] = i, int(u<x), t
                if flags & 4:
                    result[b,a] = i, int(x<u), 1-t
        if not crossings or {direction for site,direction,_ in result.values() if site == i} != {0,1}:
            raise ValueError(f"Missing east-boundary observation approach for {street}")
        sites[i]["point"] = [cut, sum(crossings)/len(crossings)]
    return result


class PassageCounter:
    def __init__(self, points, places, origins, cordon, screens, site_count, *, work_inside=True, record_start=False):
        self.points, self.places, self.origins = points, places, origins
        self.cordon, self.screens = cordon, screens
        self.counts = np.zeros((site_count, 2, 2, 24), dtype=int)
        self.examples = {}
        self.outcomes = [Counter(), Counter()]
        self.municipal_arcs = {}
        self.work_inside = work_inside
        self.record_start = record_start

    def events(self, a, b):
        gate = self.screens.get((a,b))
        if (a,b) not in self.municipal_arcs:
            before, after = self.cordon.nodes_inside[a], self.cordon.nodes_inside[b]
            if before != after:
                t = self.cordon.crossing(self.points[a], self.points[b], after)
                self.municipal_arcs[a,b] = None if t is None else (0, int(not after), t)
        return (self.municipal_arcs.get((a,b)), gate)

    def register(self, site, column, direction, minute, position, worker, start):
        hour = int(minute//60) % 24
        key = site,column,direction,hour
        self.counts[key] += 1
        city, index = worker
        example = [self.origins[city], int(index), float(minute), list(position)]
        if self.record_start:
            example.append(int(start))
        self.examples.setdefault(key,example)

    @staticmethod
    def position(a, b, fraction):
        return [x+fraction*(y-x) for x,y in zip(a,b,strict=True)]

    def __call__(self, routes, group, root, reverse, distance, parents, nodes, access):
        trace = {int(root): ()}

        def traced(end):
            target = end
            nodes_to_trace = []
            while end not in trace:
                nodes_to_trace.append(end)
                end = int(parents[end])
            for node in reversed(nodes_to_trace):
                parent = int(parents[node])
                a,b = (node,parent) if reverse else (parent,node)
                length = distance[node]-distance[parent]
                events = []
                for event in self.events(a,b):
                    if not event:
                        continue
                    site,direction,f = event
                    offset = distance[parent]+length*(1-f if reverse else f)
                    events.append((site,direction,offset,self.position(self.points[a],self.points[b],f)))
                trace[node] = tuple(sorted(events,key=lambda e:-e[2])) + trace[parent] if events else trace[parent]
            return trace[target]

        for index,column,end,budget,_ in group:
            if distance[end] > budget:
                continue
            d, i, start, _, a, b, c, e, _ = routes[index]
            if column:
                a,b = c,e
            paths = traced(int(end))
            self.outcomes[column]["feasible"] += 1
            for site,direction,offset,point in paths:
                if site:
                    minute = start+access[a]+(distance[end]-offset if reverse else offset)
                    self.register(site,column,direction,minute,point,(d,i),start)
            places_inside = self.cordon.places_inside
            leaving = reverse == self.work_inside
            if (bool(places_inside[a]), bool(places_inside[b])) != (leaving, not leaving):
                self.outcomes[column]["anchorsNotAcross"] += 1
                continue

            def connector(place, from_place, minute):
                node = nodes[place]
                if self.cordon.nodes_inside[node] == places_inside[place]:
                    return None
                place_xy, road_xy = self.places[place][:2], self.points[node]
                p,q = (place_xy,road_xy) if from_place else (road_xy,place_xy)
                f = self.cordon.crossing(p,q,not leaving)
                return None if f is None else (minute+f*access[place], self.position(p,q,f))

            road_end = start+access[a]+distance[end]
            near = connector(a, True, start) if reverse else connector(b, False, road_end)
            far = connector(b, False, road_end) if reverse else connector(a, True, start)
            road = next(((start+access[a]+(distance[end]-offset if reverse else offset),point)
                         for site,direction,offset,point in paths if site == 0 and direction == int(leaving)), None)
            crossing = near or road or far
            if crossing is None:
                raise ValueError(f"A feasible commute across the city limit has no passage: {d}/{i}/{start}")
            self.outcomes[column]["connectorCrossing" if near or not road else "roadCrossing"] += 1
            minute,point = crossing
            self.register(0,column,int(leaving),minute,point,(d,i),start)


def road_screens(network, counters, ironworkers):
    bridges = [observations(counters, [bridge])[0] if bridge != IRONWORKERS else ironworkers_observations(ironworkers)
               for bridge in BRIDGES]
    east = observations(counters, [(key,name,None,None,("Eastbound","Westbound")) for key,name,_ in EAST])
    for site in east:
        site["nearStation"] = True
    sites = [*bridges, *east]
    for site in sites:
        site["directions"] = [c["direction"] for c in site["counters"]]
        site.setdefault("source",SOURCE)
    bridges = screen_arcs(network, sites, BRIDGES)
    return sites, {**bridges, **east_arcs(network, sites, len(BRIDGES))}


def publish(root, archive, joint_id, fit_id, ironworkers):
    fit_dir = root / "incoming-home-fit" / fit_id
    fit = read(fit_dir / "report.json")
    driving = read(root / "incoming-drives" / f"{fit_id}.json")
    joint = read(root / "joint-weekday" / joint_id / "report.json")
    if (fit["joint"], driving["joint"], driving["homeFit"], driving["workerRelease"]) != (joint_id, joint_id, fit_id, joint["commuters"]):
        raise ValueError("The cordon and incoming driving comparison use different releases")
    cohort = root / "commuters" / joint["commuters"]
    workers = read(cohort / "commuters.json")
    groups = {group: read(cohort / f"{group}.json") for group in sorted(workers["groups"])}
    places = read(root / "cityday" / joint["versions"]["day"] / "places.json")
    legs, count = driving_legs(groups, len(places), fit_dir, workers["modes"].index("Car driver"))
    homes = read(root / "incoming-transit" / fit["baseline"] / "homes.json")
    if [row[3] for row in homes] != [f"Home census area {da}" for group in groups.values() for da in group["homes"]]:
        raise ValueError("The driving homes do not align with the workforce")
    places += homes
    if len(places) != count:
        raise ValueError("The cordon does not cover the full home catalogue")
    roads = root / "commuter-drive" / driving["network"]
    network, profile = (read(roads / f"{name}.json") for name in ("network", "profile"))
    raw = archive / "data/raw"
    boundary_file, counters = raw / "statcan/vancouver_city_boundary.geojson", raw / "probes" / ARCHIVE
    ring = city_ring(boundary_file)
    cordon = Cordon(ring, network["nodes"], [p[:2] for p in places])
    sites, arcs = road_screens(network, counters, ironworkers)
    sites.insert(0, dict(key="city", name="Vancouver city limit", directions=["Into Vancouver","Out of Vancouver"],
                         source=CITY_LIMIT_SOURCE))
    screens = {key: (j+1,d,f) for key,(j,d,f) in arcs.items()}
    passages = PassageCounter(network["nodes"], places, list(groups), cordon, screens, len(sites))
    score(legs, places, network, profile, {"corridors": []}, on_paths=passages)
    if [row["feasible"] for row in passages.outcomes] != driving["day"]["feasible"][:2]:
        raise ValueError("The cordon differs from the free-flow timetable’s road feasibility")
    if any(sum(passages.counts[0,i].ravel())!=outcome['roadCrossing']+outcome['connectorCrossing']
           for i,outcome in enumerate(passages.outcomes)):
        raise ValueError("The city-limit counts do not reconcile to the routed commutes")
    for j, site in enumerate(sites):
        site["counts"] = passages.counts[j].tolist()
        site["examples"] = [[[passages.examples.get((j,c,d,h)) for h in range(24)] for d in range(2)] for c in range(2)]
    sources = {path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in (boundary_file,counters,ironworkers)}
    result = dict(joint=joint_id, homeFit=fit_id, workerRelease=joint["commuters"], network=driving["network"], clock="free-flow",
                  sites=sites, coverage=passages.outcomes, sources=sources)
    pointer(root / "incoming-road-crossings" / f"{fit_id}.json", result)
    print(joint_id,[(s['key'],np.asarray(s['counts'])[:,:,7:9].sum(axis=2).tolist()) for s in sites],flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path)
    parser.add_argument("joint")
    parser.add_argument("fit")
    parser.add_argument("--root",type=Path,default=Path("public/data/vancouver"))
    parser.add_argument("--ironworkers",type=Path,default=Path("data/mobility")/IRONWORKERS_FILE)
    args = parser.parse_args()
    publish(args.root,args.archive,args.joint,args.fit,args.ironworkers)
