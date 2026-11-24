"""Audit regional resident presence at UBC and match campus transit bouts to the timetable."""
import argparse
import math
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from scripts.artifacts import read, write_json
from scripts.vancouver_cityday import ORIGIN, SCALE
from scripts.vancouver_streets import walk_graph

CAMPUS = "UBC Vancouver campus"
REPORT = "https://planning.ubc.ca/sites/default/files/2026-06/UBC2025-TransportationStatusReport-FINAL.pdf"
# Fall 2025, Tables 2.1 and 2.3. Combine SOV/HOV since diaries give no vehicle occupancy.
MODES = ["auto", "transit", "bike", "walk", "truckMotorcycle", "other"]
OBSERVED = dict(daily=[65400, 81400, 2500, 1200, 1400, 0],
                amIn=[2902, 5094, 166, 56, 65, 0], amOut=[1615, 1500, 25, 31, 45, 0],
                pmIn=[1911, 2875, 106, 66, 14, 0], pmOut=[3185, 5655, 241, 58, 36, 0])
# Printed report totals include independent rounding of components.
TOTALS = dict(daily=151900, amIn=8283, amOut=3217, pmIn=4971, pmOut=9175)
ACCESS_METRES = 800
WALK_METRES_PER_SECOND = 80 / 60


def campus_mask(places, geometry):
    from matplotlib.path import Path as Ring
    pts = np.asarray([place[:2] for place in places])
    ring = (np.asarray(geometry['coordinates'][0]) - ORIGIN) * SCALE
    return Ring(ring).contains_points(pts)


def mode_index(mode):
    if mode in ("car-driver", "car-passenger", "taxi", "ridehail"):
        return 0
    return {"transit": 1, "bike": 2, "walk": 3, "motorcycle": 4}.get(mode, 5)


def resident_day(atlas_dir, day_dir, places, mask):
    atlas, day = read(atlas_dir / 'atlas.json'), read(day_dir / 'day.json')
    campus_das = set(atlas['areas'][CAMPUS]['das'])
    # Each stationary person has one home geography and one activity class.
    change = np.zeros((1441, 2, 4), dtype=int)
    flow = np.zeros((24, 2, len(MODES)), dtype=int)
    people_visiting = 0
    rides = []
    unresolved = 0
    mixed_transit = 0
    pure_transit = [{start for start, duration, mode, _, _ in tpl["parts"] if mode == "transit" and
                     all(e[3] in ("walk", "transit") for e in source["episodes"] if start <= e[0] < start+duration)}
                    for tpl, source in zip(day["templates"], atlas["templates"], strict=True)]
    for da in day['das']:
        roster = read(atlas_dir / (da + '.json'))['people']
        plans = read(day_dir / (da + '.json'))['plans']
        if not roster:
            continue
        home_group = int(da not in campus_das)
        groups = defaultdict(list)
        for p, person in enumerate(roster):
            groups[person[7]].append(p)
        for k, ix in groups.items():
            tpl = day['templates'][k]
            anchors = np.asarray([plans[p] for p in ix], dtype=int)
            inside = (anchors >= 0) & mask[anchors]
            if home_group:
                people_visiting += int(np.count_nonzero(inside.any(axis=1)))
            for start, duration, mode, i, j in tpl['parts']:
                if mode == 'stop':
                    n = np.count_nonzero(inside[:, i])
                    kind = {"home": 0, "job": 1, "school": 2}.get(tpl['slots'][i], 3)
                    change[start-240, home_group, kind] += n
                    change[start+duration-240, home_group, kind] -= n
                    continue
                if i < 0 or j < 0:
                    if max(i, j) >= 0:
                        unresolved += int(inside[:, max(i,j)].sum())
                    continue
                unresolved += int(((inside[:, i] & (anchors[:, j] < 0)) |
                                   (inside[:, j] & (anchors[:, i] < 0))).sum())
                for direction, cross in enumerate([~inside[:, i] & inside[:, j], inside[:, i] & ~inside[:, j]]):
                    crossing = cross & (anchors[:, i] >= 0) & (anchors[:, j] >= 0)
                    indices = np.flatnonzero(crossing)
                    if len(indices) == 0:
                        continue
                    # Arrival at the inside endpoint or departure from it approximates the crossing time.
                    minute = start if direction else start + duration
                    flow[(minute//60)%24, direction, mode_index(mode)] += len(indices)
                    if mode == 'transit':
                        if start not in pure_transit[k]:
                            mixed_transit += len(indices)
                            continue
                        for m in indices:
                            rides.append((da, ix[m], start, duration, int(anchors[m,i]), int(anchors[m,j])))
    presence = change.cumsum(axis=0)[:-1]
    assert (presence >= 0).all() and not change.sum(axis=0).any()
    return dict(presence=presence.reshape(1440,8).tolist(), flow=flow.tolist(),
                visitingResidents=people_visiting, unresolved=unresolved, mixedTransit=mixed_transit), rides


def access_routes(places, endpoints, stations, street_dir):
    """Shortest pedestrian distance including both off-network connectors, bounded to 800 m."""
    if not endpoints:
        return {}
    ids = sorted(endpoints)
    pos = np.asarray([places[i][:2] for i in ids])
    station_xy = np.asarray(stations)
    tree = cKDTree(pos)
    near = tree.query_ball_point(station_xy, ACCESS_METRES)
    graph, snap = walk_graph(read(street_dir / 'network.json'))
    end_node, end_off = snap(pos, lowest_id_on_ties=True)
    stop_node, stop_off = snap(station_xy, lowest_id_on_ties=True)
    access = defaultdict(dict)
    for s, candidates in enumerate(near):
        if not candidates or stop_off[s] > ACCESS_METRES:
            continue
        # The CSR integral distances are computed once per relevant physical stop.
        distances = dijkstra(graph, indices=stop_node[s], limit=ACCESS_METRES-stop_off[s])
        for p in candidates:
            length = stop_off[s]+distances[end_node[p]]+end_off[p]
            if length <= ACCESS_METRES:
                access[ids[p]][s] = math.ceil(length/WALK_METRES_PER_SECOND)
    return access


def schedule(transit_dir):
    manifest = read(transit_dir / 'transit.json')
    station_lookup = {}; patterns = []; boards = defaultdict(list)
    for route in manifest['routes']:
        data = read(transit_dir / (route['id']+'.json'))
        station_ids = [station_lookup.setdefault(tuple(s[:2]), len(station_lookup)) for s in data['stations']]
        for pi, pat in enumerate(data['patterns']):
            rides = [(idx, ride) for idx,ride in enumerate(data['rides']) if ride[0]==pi]
            times = np.asarray([np.asarray(r[2])+r[1] for _,r in rides])
            pid = len(patterns)
            stops = [station_ids[i] for i in pat['stops']]
            patterns.append((route['id'], stops, times, [idx for idx,_ in rides]))
            for pos, stop in enumerate(stops[:-1]):
                boards[stop].append((pid,pos))
    return list(station_lookup), patterns, boards


def match(start, duration, origins, destinations, patterns, boards):
    """Earliest door arrival, then least walking; allow one vehicle in the recorded window."""
    first, end = start*60, (start+duration)*60
    best = None
    for stop, access in origins.items():
        for pid, board in boards[stop]:
            route, stops, times, ids = patterns[pid]
            dep = times[:,2*board+1]
            for alight in range(board+1,len(stops)):
                egress = destinations.get(stops[alight])
                if egress is None or stops[alight] == stop:
                    continue
                arrivals = times[:,2*alight]
                possible = np.flatnonzero((dep >= first+access) & (arrivals+egress <= end) & (arrivals > dep))
                if len(possible):
                    trip = possible[np.argmin(arrivals[possible])]
                    candidate = (int(arrivals[trip])+egress, access+egress, route, ids[trip],
                                 board, alight, access, egress)
                    if best is None or candidate < best:
                        best = candidate
    return list(best[2:]) if best else None


def build(region, versions, out):
    atlas_dir = region/'atlas'/versions['atlas']
    day_dir = region/'cityday'/versions['day']
    places = read(day_dir/'places.json')
    geometry = read(atlas_dir/'atlas.json')['areas'][CAMPUS]['geometry']
    report, bouts = resident_day(atlas_dir, day_dir, places, campus_mask(places,geometry))
    transit_dir = region/'transit'/versions['transit']
    stops, patterns, boards = schedule(transit_dir)
    access = access_routes(places, {e for b in bouts for e in b[4:]}, stops, region/'streets'/versions['streets'])
    trips = []; misses = Counter()
    for da, p, start, dur, a, b in bouts:
        if a not in access or b not in access:
            misses['access'] += 1
            continue
        ride = match(start,dur,access[a],access[b],patterns,boards)
        if ride is None:
            misses['schedule'] += 1
        else:
            trips.append([da,p,start,dur,a,b,*ride])
    result = dict(**report, versions=versions, modes=MODES, reference=OBSERVED, totals=TOTALS, source=REPORT,
                  transitBouts=len(bouts)+report['mixedTransit'], misses=dict(misses, mixed=report['mixedTransit']), rides=sorted(trips))
    write_json(out,result)
    return result


def publish(region, versions):
    dest = region/'campus'; dest.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest) as tmp:
        file = Path(tmp)/'audit.json'
        result = build(region, versions, file)
        file.replace(dest/(versions['day']+'_'+versions['transit']+'_'+versions['streets']+'.json'))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region',type=Path,default=Path('public/data/vancouver/region'))
    parser.add_argument('--day',help='Use a published weekday under the current atlas')
    parser.add_argument('--transit',help='Use the timetable selected by the weekday replay')
    args=parser.parse_args()
    versions=read(args.region/'current.json')
    if args.day:
        versions['day']=args.day
    if args.transit:
        versions['transit']=args.transit
    r=publish(args.region,versions)
    print('Campus visits by distinct residents of other areas',r['visitingResidents'],
          'transit trips',r['transitBouts'],'matched',len(r['rides']),'misses',r['misses'])
