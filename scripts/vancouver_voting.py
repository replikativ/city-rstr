"""Replay access to Vancouver's two municipal advance-voting dates under two layouts."""
import argparse
from collections import Counter, defaultdict
import hashlib
import math
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

from scripts.vancouver_atlas import largest_remainder, write_json
from scripts.vancouver_bridge_traffic import road_profile
from scripts.vancouver_campus import access_routes
from scripts.vancouver_city_transit import DirectService
from scripts.vancouver_cityday import xy
from scripts.vancouver_discretionary_outings import available_windows, verify_intervals
from scripts.vancouver_region import package, read
from scripts.vancouver_streets import access_graph, walk_graph
from scripts.vancouver_transit_commutes import pointer

OPEN, CLOSE, RATE = 480, 1200, 25
MARKING = 5  # assumed minutes after registration for the voter to mark and cast the ballot
HOUSEWORK_SHIFT = 60
RETURN_EXTENSION = 30
DEFAULT_DATE = "2025-04-01"
# Preliminary date split from the City's statement to local media. The final
# official count adds seven ballots and does not publish their dates.
ADVANCE_DAYS = {DEFAULT_DATE: (4795, 15), "2025-03-26": (2876, 9)}
WALK_SPEED, WALK_LIMIT, DRIVE_LIMIT, TRANSIT_LIMIT = 80, 20, 35, 50
BOARDING_MARGIN = 180
HALL, CENTRES = 200, (24, 4, 9, 13)
LOCATIONS_SOURCE = "https://opendata.vancouver.ca/explore/dataset/voting-places-2025/table/"
REVIEW = "https://council.vancouver.ca/20250520/documents/r3.pdf"
RESULTS = "https://council.vancouver.ca/20250415/documents/r9.pdf"
DAILY = "https://vancouver.citynews.ca/2025/04/02/vancouver-byelection-advance-voting-record-turnout/"
SCHEDULING = "https://doi.org/10.1007/s11116-022-10330-8"
TRIP_CHAINS = "https://www.translink.ca/-/media/translink/documents/about-translink/customer-service/trip-diary/2011-metro-vancouver-regional-trip-diary--analysis-report.pdf"
# Figure 1 gives approximate election-day turnout by home area. Transfer these
# proportions as relative scenario weights, separately from the April 1 volume.
HOME_WEIGHTS = {
    "Arbutus Ridge": 16.4, "Downtown": 10.2, "Dunbar-Southlands": 17.7, "Fairview": 23.3,
    "Grandview-Woodland": 26.3, "Hastings-Sunrise": 12.7, "Kensington-Cedar Cottage": 15.1,
    "Kerrisdale": 15.6, "Killarney": 10.8, "Kitsilano": 20.6, "Marpole": 10.5, "Mount Pleasant": 23.3,
    "Oakridge": 9.9, "Renfrew-Collingwood": 7.8, "Riley Park": 21.0, "Shaughnessy": 15.0,
    "South Cambie": 19.4, "Strathcona": 17.6, "Sunset": 8.39, "Victoria-Fraserview": 6.9,
    "West End": 15.5, "West Point Grey": 21.3,
}


def choose_residents(residents, demand, rng):
    by_area = defaultdict(list)
    for row in residents:
        by_area[row[4]].append(row)
    names = list(by_area)
    masses = np.array([len(by_area[name])*HOME_WEIGHTS[name] for name in names])
    allocations = largest_remainder(masses/masses.sum(), demand)
    cohort = []
    for name, count in zip(names, allocations, strict=True):
        people = by_area[name]
        cohort.extend([*people[i], int(rng.integers(OPEN, CLOSE)), int(rng.integers(0, 2**31))]
                      for i in rng.choice(len(people), size=int(count), replace=False))
    return cohort


def sites(inventory, areas, offset):
    by_id = {row["fields"]["vp_id"]: row["fields"] for row in read(inventory)["records"]}
    output = []
    for id in (HALL, *CENTRES):
        record = by_id[id]
        lat, lon = record["geom"]
        position = [*xy(lon, lat), areas.index(record["local_area"]), record["facility_name"]]
        output.append(dict(id=id, place=offset+len(output), position=position, address=record["facility_address"],
                           entrance=record["accessibility"]))
    return output


def route_options(places, choices, network, profile, homes, origins=()):
    coordinates = np.array([p[:2] for p in places])
    homes = set(homes)
    locations = np.asarray(sorted(homes|set(origins)), dtype=int)
    results = defaultdict(list)
    directed = {}
    for mode in ("walk", "car-driver"):
        if mode == "walk":
            graph, snap = walk_graph(network)
            scale, pace, minutes, connector = WALK_SPEED, 1, WALK_LIMIT, 500
        else:
            graph, snap = access_graph(network, 2, 4, speeds=profile["kmh"])
            scale, minutes, connector = 1, DRIVE_LIMIT, profile["connectorMetres"]
            pace = profile["connectorKmh"]*1000/60
        anchors, lengths = snap(coordinates, lowest_id_on_ties=True)
        reverse = graph.T.tocsr()
        for site in choices:
            place, limit = site["place"], minutes*scale
            if lengths[place] > connector:
                continue
            extra = (lengths[locations]+lengths[place])/pace
            root = int(anchors[place])
            there = dijkstra(reverse, indices=root, limit=limit)[anchors[locations]]+extra
            back = dijkstra(graph, indices=root, limit=limit)[anchors[locations]]+extra
            fits = ((there<=limit)|(back<=limit))&(lengths[locations]<=connector)
            for h,outward,returning in zip(locations[fits], there[fits], back[fits], strict=True):
                out = max(1,math.ceil(outward/scale)) if outward<=limit else None
                ret = max(1,math.ceil(returning/scale)) if returning<=limit else None
                if h in homes and out and ret:
                    results[int(h)].append((site["id"], place, mode, out, ret))
                if origins:
                    directed[int(h),site["id"],mode] = out,ret
    return results, directed


def connect_sites(offices, network):
    graph,snap = walk_graph(network)
    _,components = connected_components(graph,directed=False)
    size = np.bincount(components)
    nodes = np.flatnonzero(components==size.argmax())
    points = np.asarray(network["nodes"])
    tree = cKDTree(points[nodes])
    for site in offices:
        point = site["position"][:2]
        node,_ = snap(point)
        if components[node]==size.argmax():
            continue
        offset,i = tree.query(point)
        if offset>75:
            raise ValueError("A voting site has no connected pedestrian entrance near its official point")
        site["anchor"] = [*points[nodes[i]].tolist(),*site["position"][2:]]
        site["anchorOffset"] = round(float(offset),1)


def plan_voter(windows, routes, offices, can_drive, preferred):
    best, key = None, None
    for id, place, mode, there, back in routes:
        if id not in offices or (mode=="car-driver" and not can_drive):
            continue
        for start,end in windows:
            lo = max(start+there, OPEN)
            hi = min(end-back-MARKING-1, CLOSE-1)
            if lo>hi:
                continue
            arrival = min(hi,max(lo,preferred))
            candidate = (mode!="walk",there+back,abs(arrival-preferred),id,arrival)
            if key is None or candidate<key:
                key,best = candidate,(id,place,mode,arrival,there,back,end-back,None)
    return best


class VotingTransit:
    def __init__(self, folder, places, offices, homes, streets):
        self.service = DirectService(folder)
        access = access_routes(places,{*homes,*(s["place"] for s in offices)},self.service.stations,streets)
        self.connected = self.service.accessible_positions(access)
        self.latest = self.service.latest_departure(access,BOARDING_MARGIN)
        self.earliest = self.service.matcher(access,boarding_margin=BOARDING_MARGIN,mapped_only=True,arrival_time=True)
        self.offices = offices
        self.release = folder.name

    def feasible_sites(self, home, offices):
        begin,end = self.connected(home,True),self.connected(home,False)
        return [s for s in self.offices if s["id"] in offices and
                begin.keys()&self.connected(s["place"],False).keys() and
                end.keys()&self.connected(s["place"],True).keys()]

    def plan(self, home, sites, windows, preferred):
        best,key = None,None
        for site in sites:
            place = site["place"]
            for start,end in windows:
                lo,hi = max(OPEN,start+5),min(CLOSE-1,end-MARKING-6)
                if lo>hi:
                    continue
                return_boundary = self.latest(end*60,place,home)
                if not return_boundary:
                    continue
                last,reach,inward = return_boundary
                hi = min(hi,last-MARKING-1)
                if lo>hi or math.ceil(reach/60)-last>TRANSIT_LIMIT:
                    continue
                for deadline in dict.fromkeys((min(hi,max(lo,preferred)),hi,(lo+hi)//2)):
                    found = self.latest(deadline*60,home,place)
                    if not found:
                        continue
                    leave,reach_poll,outward = found
                    arrival = math.ceil(reach_poll/60)
                    there = arrival-leave
                    if leave<start or arrival<OPEN or not 0<there<=TRANSIT_LIMIT:
                        continue
                    back = math.ceil(reach/60)-last
                    candidate = (there+back,abs(arrival-preferred),site["id"],arrival)
                    if key is None or candidate<key:
                        key,best = candidate,(site["id"],place,"transit",arrival,there,back,last,(outward,inward,end))
        return best

    def returning(self, home,place,leave,latest,back,transit):
        outward,inward,end = transit
        trip = self.earliest(leave,min(TRANSIT_LIMIT,end-leave),place,home) if leave<latest else None
        if trip:
            reach,ride = trip
            return leave,math.ceil(reach/60)-leave,[outward,list(ride)]
        return latest,back,[outward,inward]


def choose_plan(road, train):
    if road is None or (train is not None and road[2]!="walk" and sum(train[4:6])<sum(road[4:6])):
        return train
    return road


def register(voters, staff, transit=None):
    """Assign a first-come, first-served slot, with each voter free to leave."""
    capacity = staff*RATE
    service_slot = 0
    for d,i,home,id,place,mode,arrival,there,back,latest,rides,tie in sorted(voters,key=lambda v:(v[6],v[-1])):
        # Finish the next registration after its share of service time.
        slot = max(service_slot, ((arrival-OPEN)*capacity)//60)
        ready = OPEN+math.ceil((slot+1)*60/capacity)
        if ready+MARKING<=latest:
            completed = ready+MARKING
            service_slot = slot+1
            leave = completed
        else:
            completed = None
            leave = latest
        if rides is not None:
            leave,back,rides = transit.returning(home,place,leave,latest,back,rides)
        yield [d,i,home,place,mode,arrival-there,there,leave,back,completed,id,
               ready if completed is not None else None,rides]


def allocate_registrars(offices, registrars, plans):
    minimum, extra = divmod(registrars, len(offices))
    if minimum < 1:
        raise ValueError("Every selected voting place needs at least one registrar")
    busiest = sorted(offices, key=lambda site: (-len(plans[site]), site))
    return {site: minimum + (rank < extra) for rank, site in enumerate(busiest)}


def flexible_home_windows(windows, chores, blocks):
    """Keep each chore intact and on the same side of protected appointments."""
    reserved = sorted([*blocks, *((s, s+n) for s,n,_ in chores
                                  if any(s < b and a < s+n for a,b in blocks))])
    for start, end in available_windows(windows, reserved):
        tasks = [task for task in chores if start <= task[0] and task[0]+task[1] <= end]
        if not tasks:
            continue
        earliest, latest = [start], [end]
        for minute, duration, _ in tasks:
            earliest.append(max(earliest[-1], minute-HOUSEWORK_SHIFT)+duration)
        for minute, duration, _ in reversed(tasks):
            latest.append(min(latest[-1]-duration, minute+HOUSEWORK_SHIFT))
        yield start, end, tasks, list(zip(earliest, reversed(latest), strict=True))


def reschedule_housework(trip, blocks):
    start, end = trip[5], trip[7]+trip[8]
    candidates = []
    for lo, hi, chores, windows in blocks:
        for cut, (first, last) in enumerate(windows):
            if not first <= start < end <= last:
                continue
            before, after = [], []
            deadline = start
            for minute, duration, label in reversed(chores[:cut]):
                revised = min(minute, deadline-duration)
                before.append([minute, duration, label, revised])
                deadline = revised
            ready = end
            for minute, duration, label in chores[cut:]:
                revised = max(minute, ready)
                after.append([minute, duration, label, revised])
                ready = revised+duration
            tasks = list(reversed(before))+after
            if not all(lo <= revised <= hi-duration and abs(revised-minute) <= HOUSEWORK_SHIFT
                       for minute,duration,_,revised in tasks):
                raise ValueError("A household task was shifted outside its available time")
            candidates.append((sum(abs(revised-minute) for minute,_,_,revised in tasks), lo, hi, tasks))
    if not candidates:
        raise ValueError("A flexible polling visit leaves too little time for housework")
    shift, lo, hi, tasks = min(candidates)
    return [lo, hi, tasks] if shift else None


def polling_plan(windows, options, offices, driver, preferred, home, transit):
    road = plan_voter(windows,options,offices,driver,preferred)
    sites = transit.feasible_sites(home,offices) if road is None or road[2]!="walk" else ()
    return choose_plan(road,transit.plan(home,sites,windows,preferred)), sites


def return_legs(root, versions, joint, day, places, cohorts, windows, blocked):
    atlas_dir, day_dir = root/"atlas"/versions["atlas"], root/"cityday"/versions["day"]
    diaries = read(atlas_dir/"atlas.json")["templates"]
    tract = read(root/"tract-workplaces"/joint["workplaces"]["tract-workplaces"]/"worksites.json")
    if not tract["preserveDiaryModes"] or any(tract[k]!=v for k,v in versions.items()):
        raise ValueError("Polling detours require the combined weekday with recorded travel modes")
    workers = root/"outbound"/joint["workplaces"]["outbound"]
    external = [{row[0] for row in rows} for rows in read(workers/"assignments.json")]
    job_slots = read(workers/"report.json")["slots"]
    sampled = {(row[0],row[1]) for cohort in cohorts.values() for row in cohort}
    changes = {(d,i,a): b for d,i,a,_,b in tract["changes"] if (d,i) in sampled}
    plans = {d:read(day_dir/(day["das"][d]+".json"))["plans"] for d in sorted({d for d,_ in sampled})}
    legs = defaultdict(list)
    for cohort in cohorts.values():
        for d,i,home,tpl,*_ in cohort:
            if home<0 or places[home][2]<0:
                continue
            reserved = blocked.get((d,i),())
            home_time = list(available_windows(windows[tpl], reserved))
            template = day["templates"][tpl]
            plan = plans[d][i]
            for start, duration, mode, a, b in template["parts"]:
                end = start+duration
                if (mode not in ("walk", "car-driver") or min(a,b)<0 or template["slots"][b]!="home"
                        or plan[b]!=home or end<=OPEN or start>=CLOSE or
                        (i in external[d] and a in job_slots[tpl]) or
                        any(start < hi and lo < end for lo,hi in reserved)):
                    continue
                if any(location!=mode for s,n,_,location in diaries[tpl]["episodes"] if s < end and start < s+n):
                    continue
                origin = changes.get((d,i,a),plan[a])
                if origin<0 or origin==home or places[origin][2]<0:
                    continue
                until = next((min(hi,end+RETURN_EXTENSION) for lo,hi in home_time if lo<=end<hi),end)
                legs[d,i].append((origin,start,end,until,mode,template["slots"][a]))
    return legs


def plan_detour(home, legs, offices, paths, preferred):
    best, key = None, None
    for origin,start,end,until,mode,purpose in legs:
        for site in offices:
            there,_ = paths.get((origin,site["id"],mode),(None,None))
            _,back = paths.get((home,site["id"],mode),(None,None))
            if not there or not back:
                continue
            arrive, latest = start+there, until-back
            if not OPEN<=arrive<CLOSE or arrive+MARKING+1>latest:
                continue
            candidate = (max(0,arrive+MARKING+1+back-end),there+back,abs(arrive-preferred),site["id"],start)
            if key is None or candidate<key:
                key = candidate
                best = ((site["id"],site["place"],mode,arrive,there,back,latest,None),[origin,end,purpose])
    return best


def simulate(cohort, offices, registrars, opportunities, routes, blocked, transit, *, flexible=False, detours=None):
    demand = dict.fromkeys(offices)
    raw = defaultdict(list)
    misses, rescheduled, chained = Counter(), {}, {}
    for d,i,home,tpl,area,driver,age,employed,preferred,tie in cohort:
        reserved = blocked.get((d,i),())
        windows = list(available_windows(opportunities["windows"][tpl], reserved))
        options = routes.get(home,())
        assignment, sites = polling_plan(windows, options, demand, driver, preferred, home, transit)
        has_route = sites or any(r[0] in offices and (r[2]=="walk" or driver) for r in options)
        if flexible and assignment is None and has_route:
            extras = list(flexible_home_windows(opportunities["flexible"][tpl], opportunities["chores"][tpl], reserved))
            expanded = [window for _,_,_,bounds in extras for window in bounds if window[1]>window[0]]
            if expanded:
                assignment, _ = polling_plan(expanded, options, demand, driver, preferred, home, transit)
                if assignment is not None:
                    rescheduled[d,i] = extras
        if assignment is None and detours:
            legs, polling_sites, paths = detours
            chain = plan_detour(home,legs.get((d,i),()),polling_sites,paths,preferred)
            if chain:
                assignment, chained[d,i] = chain
        if assignment is None:
            misses["route"] += not has_route
            continue
        id,place,mode,arrive,there,back,latest,rides = assignment
        raw[id].append([d,i,home,id,place,mode,arrive,there,back,latest,rides,tie])
    staff = allocate_registrars(offices, registrars, raw)
    trips = sorted(row for id in offices for row in register(raw[id],staff[id],transit))
    for row in trips:
        key = tuple(row[:2])
        if key in rescheduled:
            schedule = reschedule_housework(row, rescheduled[key])
            if schedule:
                row.append(schedule)
        if key in chained:
            row.extend([None,chained[key]])
    return trips, staff, dict(route=misses["route"], schedule=len(cohort)-len(trips)-misses["route"])


def voting_clock(tours, places, occupancy, areas, scratch, backend):
    """Replace the original return leg in the clock wherever a poll is on the way."""
    cols = len(areas)+2
    moving = cols-2
    changes = np.zeros((1441,cols), dtype=np.int32)
    schedules = []
    for row in tours:
        _,_,home,site,_,start,there,leave,back,*_ = row
        chain = row[14] if len(row)>14 else None
        original_end = chain[1] if chain else start
        if not 240 <= start < start+there < leave < leave+back <= 1680:
            raise ValueError("Voting itinerary outside the civil day")
        bound = max(original_end,leave+back)
        home_area, poll_area = places[home][2],places[site][2]
        if min(home_area,poll_area)<0:
            raise ValueError("Voting itinerary lost a mapped home or polling place")
        pieces = []
        knots = sorted({start,start+there,leave,leave+back,original_end,bound})
        for a,b in zip(knots,knots[1:]):
            base = moving if a<original_end else home_area
            alternative = home_area if a>=leave+back else poll_area if start+there<=a<leave else moving
            a,b = a-240,b-240
            changes[a:b,base] -= 1
            changes[a:b,alternative] += 1
            pieces.append((a*cols+base,b*cols+base,alternative-base))
        schedules.append(tuple(pieces))
    return verify_intervals(schedules,changes,occupancy,scratch,backend)


def metrics(cohort, trips, offices):
    outputs = {id: dict(arrivals=[0]*1440, ballots=[0]*1440, waiting=[0]*1440) for id in offices}
    voters = {tuple(row[:2]):row for row in trips}
    by_area, by_age, employment = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    travel_minutes, wait_minutes = [], []
    for d,i,_,_,area,_,age,working,*_ in cohort:
        row = voters.get((d,i))
        band = "20–39" if age<=7 else "40–64" if age<=11 else "65+"
        for counts in (by_area[area],by_age[band],employment["Employed" if working else "Other residents"]):
            counts["assigned"]+=1
            counts["reach"]+=row is not None
            counts["cast"]+=row is not None and row[9] is not None
    for _,_,_,_,_,start,there,leave,back,cast,id,ready,_,*_ in trips:
        site = outputs[id]
        arrival = start+there-240
        site["arrivals"][arrival]+=1
        if cast is not None:
            site["ballots"][cast-240]+=1
        for m in range(arrival,(ready if ready is not None else leave)-240):
            site["waiting"][m]+=1
        travel_minutes.append(there+back)
        wait_minutes.append((ready if ready is not None else leave)-start-there)
    return dict(sites=outputs,area=by_area,age=by_age,employment=employment,
                trips=len(trips),modes=dict(Counter(row[4] for row in trips)),cast=sum(row[9] is not None for row in trips),
                medianTravel=float(np.median(travel_minutes)),medianWait=float(np.median(wait_minutes)))


def housework_effect(original, revised):
    before = {tuple(row[:2]):row for row in original}
    after = {tuple(row[:2]):row for row in revised}
    if not before.keys() <= after.keys() or any(row[3:7] != after[key][3:7] for key,row in before.items()):
        raise ValueError("Allowing housework shifts changed an existing trip to the poll")
    shifts = [abs(new_start-old_start) for row in revised if len(row)>13
              for old_start,_,_,new_start in row[13][2] if old_start!=new_start]
    return dict(added=len(after)-len(before), residents=sum(len(row)>13 for row in revised),
                tasks=len(shifts), medianShift=float(np.median(shifts)) if shifts else 0)


def detour_effect(original, revised):
    prior = {tuple(row[:2]):row for row in original}
    added = [row for row in revised if len(row)>14]
    continuing = {tuple(row[:2]):row for row in revised if len(row)<=14}
    if (continuing.keys()!=prior.keys() or any(row[3:7]!=continuing[key][3:7] for key,row in prior.items())
            or any(tuple(row[:2]) in prior for row in added)):
        raise ValueError("A detour altered an existing trip to the poll")
    later = [max(0,row[7]+row[8]-row[14][1]) for row in added]
    return dict(added=len(added), cast=sum(row[9] is not None for row in added),
                fromWork=sum(row[14][2]=="job" for row in added), modes=dict(Counter(row[4] for row in added)),
                medianLater=float(np.median(later)) if later else 0)


def paired_access(itineraries):
    a,b = ({tuple(row[:2]):row[6]+row[8] for row in itineraries[k]} for k in ("hall","centres"))
    common = a.keys()&b.keys()
    return dict(both=len(common),gained=len(b.keys()-a.keys()),lost=len(a.keys()-b.keys()),
                shorter=sum(b[k]<a[k] for k in common),same=sum(b[k]==a[k] for k in common),
                longer=sum(b[k]>a[k] for k in common))


def prepare_day(root, versions, joint_id, joint, day):
    """Reserve previously assigned outings before inserting any civic trips."""
    base = root/"joint-weekday"/joint_id if joint else None
    short_walks = (base/"short-walks.json" if base else
                   root/"short-walks"/(versions["day"]+"_"+versions["streets"]+".json"))
    walks = read(short_walks)
    if any(walks[k]!=v for k,v in versions.items()):
        raise ValueError("Protected short walks use a different weekday")
    blocked = defaultdict(list)
    for d,i,start,duration,*_ in walks["walks"]:
        blocked[d,i].append((start,start+duration))
    occupancy = np.asarray(day["occupancy"]) + np.asarray(walks["occupancyDelta"])
    lunch = None
    if joint:
        occupancy = np.asarray(read(base/"occupancy.json"))
        paths = [root/"discretionary-outings"/joint["outings"]/"tours.json"]
        lunch_pointer = root/"workplace-lunch"/(joint_id+".json")
        if lunch_pointer.is_file():
            lunch = read(lunch_pointer)["version"]
            lunch_base = root/"workplace-lunch"/lunch
            lunch_report = read(lunch_base/"report.json")
            if lunch_report["joint"] != joint_id or lunch_report["versions"] != versions:
                raise ValueError("Workplace lunches use a different weekday")
            paths.append(lunch_base/"tours.json")
            occupancy += np.asarray(lunch_report["occupancyDelta"])
        for path in paths:
            for d,i,_,_,_,_,start,there,dwell,back,*_ in read(path):
                blocked[d,i].append((start,start+there+dwell+back))
    for spans in blocked.values():
        spans.sort()
    return blocked, occupancy, lunch


def publish(root, inventory, backend, day_id=None, joint_id=None):
    atlas_day = read(root/"cityday/current.json")
    joint = read(root/"joint-weekday"/joint_id/"report.json") if joint_id else None
    versions = (joint["versions"] if joint else
                dict(atlas=atlas_day["atlas"],day=day_id or atlas_day["version"],streets=read(root/"streets/current.json")["version"]))
    atlas = root/"atlas"/versions["atlas"]
    day_path = root/"cityday"/versions["day"]
    day, places = read(day_path/"day.json"),read(day_path/"places.json")
    base_places = len(places)
    offices = sites(inventory,day["areas"],base_places)
    blocked, occupancy, lunch = prepare_day(root, versions, joint_id, joint, day)
    streets = root/"streets"/versions["streets"]
    network = read(streets/"network.json")
    connect_sites(offices,network)
    places.extend(site.get("anchor",site["position"]) for site in offices)
    profile,roads = road_profile(root,versions["streets"],"time")
    results, itineraries, date_reports = {}, {}, {}
    with tempfile.TemporaryDirectory() as temporary:
        scratch = Path(temporary)
        estimates = scratch/"opportunities.json"
        subprocess.run(["clojure","-J-Xmx2g","-M","-m","city.vancouver.voting-opportunities",atlas,day_path,estimates],check=True)
        opportunities = read(estimates)
        candidates = opportunities["residents"]
        cohorts = {}
        for date, (demand, _) in ADVANCE_DAYS.items():
            seed = int(date.replace("-", ""))
            cohort = choose_residents(candidates, demand, np.random.default_rng(seed))
            cohorts[date] = cohort
            sampled = {tuple(row[:2]) for row in cohort}
            candidates = [row for row in candidates if tuple(row[:2]) not in sampled]
        homes = [row[2] for cohort in cohorts.values() for row in cohort if row[2]>=0]
        allow_detours = joint and joint["preserveDiaryModes"]
        returns = (return_legs(root,versions,joint,day,places,cohorts,opportunities["windows"],blocked)
                   if allow_detours else {})
        routes, single_legs = route_options(places,offices,network,profile,homes,
                                            {leg[0] for legs in returns.values() for leg in legs})
        transit_pointer = root/"transit-riders"/("_".join(versions[k] for k in ("atlas","day","streets"))+".json")
        timetable = joint["transit"] if joint else read(transit_pointer)["transit"]
        transit = VotingTransit(root/"transit"/timetable,places,offices,homes,streets)
        for date, (demand, registrars) in ADVANCE_DAYS.items():
            cohort = cohorts[date]
            policies = {}
            for policy in ("recorded", "flex", "on-way") if allow_detours else ("recorded", "flex"):
                layout_keys, date_itineraries = {}, {}
                for layout, ids in (("hall",(HALL,)),("centres",(HALL,*CENTRES))):
                    key = layout if date == DEFAULT_DATE else f"{date}-{layout}"
                    if policy != "recorded":
                        key += f"-{policy}"
                    detours = (returns,[site for site in offices if site["id"] in ids],single_legs) if policy=="on-way" else None
                    tours, staff, missed = simulate(cohort, ids, registrars, opportunities, routes, blocked,
                                                    transit, flexible=policy!="recorded",detours=detours)
                    summary = metrics(cohort,tours,ids)
                    if policy == "flex":
                        recorded = policies["recorded"]["layouts"][layout]
                        summary["housework"] = housework_effect(itineraries[recorded], tours)
                    if policy == "on-way":
                        flexible = policies["flex"]["layouts"][layout]
                        summary["detours"] = detour_effect(itineraries[flexible], tours)
                    for d,i,home,site,mode,start,there,leave,back,*_ in tours:
                        if not start+there<leave or any(start < b and a < leave+back for a,b in blocked[d,i]):
                            raise ValueError("A voter visit conflicts with their existing activities")
                    clock = voting_clock(tours,places,occupancy,day["areas"],scratch,backend)
                    results[key] = dict(summary,**clock,misses=missed,staff=staff)
                    itineraries[key] = date_itineraries[layout] = tours
                    layout_keys[layout] = key
                    print(date,layout,policy,{k:summary[k] for k in ("trips","cast","medianTravel","medianWait")},
                          summary.get("detours",summary.get("housework",missed)),flush=True)
                policies[policy] = dict(layouts=layout_keys, paired=paired_access(date_itineraries))
            date_reports[date] = dict(demand=demand, registrars=registrars, **policies["recorded"], flex=policies["flex"])
            if allow_detours:
                date_reports[date]["on-way"] = policies["on-way"]
    default = date_reports[DEFAULT_DATE]
    report = dict(schema=1,versions=versions,basePlaces=base_places,offices=offices,results=results,
                  demand=default["demand"],opening=[OPEN,CLOSE],registrars=default["registrars"],registrationRate=RATE,marking=MARKING,
                  officialAdvanceBallots=7678,paired=default["paired"],dates=date_reports,defaultDate=DEFAULT_DATE,
                  transit=dict(release=transit.release,date=transit.service.route_manifest["date"],
                               routes=transit.service.route_manifest["routes"]),
                  walkMetresPerMinute=WALK_SPEED,source=REVIEW,locations=LOCATIONS_SOURCE,ballotsSource=RESULTS,
                  dailySource=DAILY,locationsDigest=hashlib.sha256(inventory.read_bytes()).hexdigest(),roads=roads,
                  joint=joint_id,lunch=lunch,houseworkShift=HOUSEWORK_SHIFT,schedulingSource=SCHEDULING)
    if allow_detours:
        report["onWay"] = dict(maxExtension=RETURN_EXTENSION, source=TRIP_CHAINS, candidateLegs=sum(map(len,returns.values())))
    family = "voting"

    def build(out):
        write_json(out/"report.json",report)
        for name, rows in itineraries.items():
            write_json(out/(name+".json"),rows)

    release = package(root,family,build)
    key = joint_id or "_".join(versions[k] for k in ("atlas","day","streets"))
    pointer(root/family/(key+".json"),{"version":release})
    print(release,{date:data["paired"] for date,data in date_reports.items()},flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path("public/data/vancouver"))
    parser.add_argument("--inventory",type=Path,default=Path("data/civic/vancouver-voting-places-2025.json"))
    parser.add_argument("--backend",default="jvm")
    parent = parser.add_mutually_exclusive_group()
    parent.add_argument("--day",help="Use a published weekday under the current atlas")
    parent.add_argument("--joint",help="Use a published combined weekday and protect its existing activities")
    args=parser.parse_args()
    publish(args.root,args.inventory,args.backend,args.day,args.joint)
