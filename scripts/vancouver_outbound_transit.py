"""Place residents' complete external transit commutes conditional on their existing diaries."""
import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from scripts.vancouver_atlas import largest_remainder, write_json
from scripts.vancouver_campus import access_routes
from scripts.vancouver_city_transit import DirectService
from scripts.vancouver_commuter_coverage import carry_bookings, passenger_walks
from scripts.vancouver_outbound_road_jobs import inventory
from scripts.vancouver_region import package, read
from scripts.vancouver_transit_commutes import BOARDING_MARGIN_SECONDS, pointer
from scripts.vancouver_transit_load import ANNUAL_TABLE, TABLE, BusSpaces, bus_capacity_profile, bus_load_evidence, ride_legs
from scripts.vancouver_transit_reach import INF, Reach
from scripts.vancouver_transit_transfers import OneTransfer, TwoTransfers, walk_transfers
from scripts.vancouver_work_transit import GTFS_SOURCE, priority

SEED = 10355


def workers(root, joint_id, cities):
    result, coverage = defaultdict(list), defaultdict(Counter)
    with tempfile.TemporaryFile(mode="w+") as out:
        subprocess.run(["node","scripts/vancouver_outbound_road_legs.mjs",root,joint_id,"--transit"],stdout=out,check=True)
        out.seek(0)
        for line in out:
            d,i,city,slots,legs,absent = json.loads(line)
            count = sum(leg[4] for leg in legs)
            if not count:
                continue
            row = coverage[city]
            row.update(workers=1,transitLegs=count)
            if city not in cities:
                row["outsideInventory"] += 1
            elif not all(leg[5] for leg in legs):
                row["mixedModes"] += 1
            elif absent or any(leg[2]<0 for leg in legs) or not {True,False} <= {leg[3] for leg in legs}:
                row["missingWindowOrEndpoint"] += 1
            else:
                result[city].append((d,i,slots,legs))
                row["checked"] += 1
    return result,coverage


def candidate_jobs(workers, sites, reach, places, employment, stats):
    destinations = reach.destinations(sites)

    @lru_cache(maxsize=384)
    def window(start,duration,anchor,returning):
        return reach.query(anchor,start,duration,returning,destinations)

    pending = []
    for person in workers:
        legs = person[3]
        if any(leg[2] not in reach.access for leg in legs):
            stats["anchorAccess"] += 1
            continue
        slack = np.zeros(len(sites),dtype=np.int32)
        feasible = np.ones(len(sites),dtype=bool)
        for start,duration,anchor,returning,*_ in legs:
            journeys = window(start,duration,anchor,returning)
            spare = (-start if returning else start+duration)*60 - journeys
            feasible &= (journeys < INF) & (spare >= 0)
            if not np.any(feasible):
                break
            slack[feasible] += spare[feasible]
        if not np.any(feasible):
            stats["noSameSiteInTimetable"] += 1
            continue
        tracts = defaultdict(list)
        for idx in np.flatnonzero(feasible):
            site = sites[idx]
            tracts[places[site][5]].append((site,int(slack[idx])))
        pending.append((person,tracts))

    tracts = sorted({places[i][5] for i in sites})
    target = dict(zip(tracts,largest_remainder([employment[t] for t in tracts],len(pending)),strict=True))
    print("Timetable screen",len(workers),len(pending),window.cache_info(),flush=True)
    return pending,target


class Bookings:
    def __init__(self, service, access, paths, spaces):
        self.spaces = spaces
        self.planner = OneTransfer(service,access,paths,BOARDING_MARGIN_SECONDS)
        self.two = TwoTransfers(self.planner)
        self.direct = lru_cache(maxsize=8192)(service.latest_departure(access,BOARDING_MARGIN_SECONDS))
        self.direct_available = service.latest_departure(access,BOARDING_MARGIN_SECONDS,spaces.available)

    def itinerary(self,start,dur,a,b,available=None):
        direct = self.direct if available is None else self.direct_available
        end = (start+dur)*60
        result = direct(end,a,b)
        if result and result[0] >= start:
            return result[2]
        result = self.planner.latest(end,a,b,available,earliest_minute=start)
        if result:
            return result[2]
        return self.two.journey(start*60,end,a,b,available)

    def circuit(self, da, person, legs, site):
        booked = []
        segments = set()
        for start,duration,anchor,returning,*_ in legs:
            a,b = (site,anchor) if returning else (anchor,site)
            ride = self.itinerary(start,duration,a,b)
            if ride and not self.spaces.fits(ride):
                ride = self.itinerary(start,duration,a,b,self.spaces.available)
            if not ride:
                return None
            for route,run,board,alight in ride_legs(ride):
                for i in range(board,alight):
                    key = route,run,i
                    if key in segments:
                        raise ValueError("Two work windows reserve the same vehicle segment")
                    segments.add(key)
            booked.append([da,person,start,duration,a,b,*ride])
        for row in booked:
            self.spaces.reserve(row[6:])
        return booked


def allocate(workers, sites, reach, places, employment, planner, rng, stats, das, max_candidates):
    pending,target = candidate_jobs(workers,sites,reach,places,employment,stats)
    used = Counter()
    matches = []
    def order(entry):
        (d,i,_,legs), tracts = entry
        start,duration,*_ = min(legs,key=lambda leg:leg[0]+leg[1])
        return len(tracts),priority((das[d],i,start,duration))
    for (d,i,slots,legs), tracts in sorted(pending,key=order):
        for attempt in range(max_candidates):
            if not tracts:
                break
            names = sorted(tracts)
            weights = np.asarray([max(0,target[t]-used[t]) for t in names],dtype=float)
            if not np.any(weights):
                weights = np.asarray([employment[t] for t in names],dtype=float)
            tract = names[int(rng.choice(len(names),p=weights/weights.sum()))]
            options = tracts[tract]
            # Prefer shorter complete journeys, with a seeded spread across viable sites.
            p = max(range(len(options)),key=lambda j:options[j][1]+rng.gumbel(0,180))
            site,_ = options.pop(p)
            if not options:
                del tracts[tract]
            rows = planner.circuit(das[d],i,legs,site)
            if rows:
                used[tract] += 1
                matches.append((das[d],i,site,slots,rows))
                stats["placed"] += 1
                stats["bookedLegs"] += len(rows)
                stats["workedFirstCandidate"] += attempt == 0
                break
        if not matches or matches[-1][:2] != (das[d],i):
            stats["searchLimit" if tracts else "noBookableSite"] += 1
    return matches,{t:[int(target[t]),used[t]] for t in target}


def reservations(root,joint,incoming):
    original = root/"transit"/joint["transit"]
    schedule = root/"transit"/incoming["timetable"]
    residents = root/"transit-riders"/joint["riders"]
    r = read(residents/"riders.json")
    trips = [leg for da in r["das"] for row in read(residents/f"{da}.json") for leg in ride_legs(row[6:])]
    existing = carry_bookings(original,schedule,trips)
    if len(existing)!=incoming["reservedLegs"]:
        raise ValueError("The incoming release and resident reservations disagree")
    return existing


def publish(root,archive,pbf,geography,joint_id,incoming_id,max_candidates):
    joint = read(root/"joint-weekday"/joint_id/"report.json")
    incoming_dir = root/"incoming-transit"/incoming_id
    incoming = read(incoming_dir/"report.json")
    if incoming["joint"]!=joint_id or incoming["residentRiders"]!=joint["riders"] or incoming["versions"]!=joint["versions"]:
        raise ValueError("The outbound release needs compatible incoming bookings and resident diaries")
    walk = root/"commuter-walk"/incoming["walking"]
    street = read(walk/"report.json")
    jobs,employment,sources = inventory(archive,pbf,geography,street["bounds"])
    if sources[pbf.name]!=street["sourceDigest"]:
        raise ValueError("The workplace inventory and metro walk graph use different OSM archives")
    groups,coverage = workers(root,joint_id,jobs)
    day_dir = root/"cityday"/joint["versions"]["day"]
    day = read(day_dir/"day.json")
    places = read(day_dir/"places.json")
    base = len(places)
    sites = defaultdict(list)
    for city,positions in sorted(jobs.items()):
        for x,y,label,tract in positions:
            sites[city].append(len(places))
            places.append([x,y,-1,label,city,tract])
    schedule = root/"transit"/incoming["timetable"]
    service = DirectService(schedule)
    probes = archive/"data/raw/probes"
    profile = bus_capacity_profile(service.route_manifest,probes/TABLE,probes/ANNUAL_TABLE)
    reserved = reservations(root,joint,incoming)
    for group,(_,matched) in incoming["groups"].items():
        if matched:
            reserved.extend(leg for row in read(incoming_dir/f"{group}.json") for leg in ride_legs(row[6:]))
    spaces = BusSpaces(profile["limits"])
    spaces.preload(reserved)
    endpoints = {a for entries in groups.values() for *_,legs in entries for _,_,a,*_ in legs}
    endpoints.update(range(base,len(places)))
    print(f"Finding walks for {len(endpoints):,} endpoints and {len(service.stations):,} stops",flush=True)
    access = access_routes(places,endpoints,service.stations,walk)
    paths = walk_transfers(service,read(schedule/"transfers.json")["pairs"],walk/"network.json",BOARDING_MARGIN_SECONDS)
    reach = Reach(service,access,paths,BOARDING_MARGIN_SECONDS)
    planner = Bookings(service,access,paths,spaces)
    rng = np.random.default_rng(SEED)
    assigned,tract_counts = [],{}
    for city,entries in sorted(groups.items()):
        print(city,len(entries),flush=True)
        matched,tract_counts[city] = allocate(entries,sites[city],reach,places,employment,planner,rng,coverage[city],day["das"],max_candidates)
        assigned.extend(matched)
        print(city,dict(coverage[city]),flush=True)
    booked = [row for *_,rows in assigned for row in rows]
    bus = bus_load_evidence(schedule,service.route_manifest,booked,probes/TABLE,profile["limits"],reserved=reserved)
    if bus["above"] or not booked:
        raise ValueError("The outbound commute layer must have capacity-checked journeys")
    paths = passenger_walks(read(walk/"network.json"),service,places,booked)
    selected = sorted({site for _,_,site,*_ in assigned})
    index = {site:j for j,site in enumerate(selected,base)}
    grouped = defaultdict(list)
    for da,i,site,slots,rows in assigned:
        rewrites = [[*r[:4],*(index.get(p,p) for p in r[4:6]),*r[6:]] for r in rows]
        grouped[da].append([i,index[site]-base,slots,rewrites])
    examples = {}
    for da,rows in grouped.items():
        for i,site,_,legs in rows:
            prep = [r for r in legs if r[5]>=base]
            first = prep[0]
            city = places[selected[site]][4]
            rank = (abs(first[2]-480),da,i)
            if city not in examples or rank<examples[city][0]:
                examples[city] = rank,[da,i,first[2]]
    report = dict(joint=joint_id,versions=joint["versions"],workplaces=joint["workplaces"],incoming=incoming_id,
                  timetable=incoming["timetable"],walking=incoming["walking"],serviceDate=service.route_manifest["date"],
                  basePlaces=base,areas=sorted(grouped),workers=len(assigned),journeys=len(booked),coverage=coverage,
                  maxCandidates=max_candidates,transferLimit=2,boardingMargin=BOARDING_MARGIN_SECONDS,
                  examples={k:v[1] for k,v in sorted(examples.items())},censusTracts=tract_counts,
                  sources=sources,bus=bus,capacitySources=profile["sources"],reservedLegs=len(reserved),gtfsSource=GTFS_SOURCE)

    def build(out):
        write_json(out/"report.json",report)
        write_json(out/"places.json",[places[i] for i in selected])
        for da,rows in grouped.items():
            write_json(out/f"{da}.json",sorted(rows))
            write_json(out/f"{da}-walks.json",sorted(paths[da],key=lambda r:r[:2]))
    version = package(root,"outbound-transit",build)
    pointer(root/"outbound-transit"/f"{joint_id}_{incoming_id}.json",dict(version=version))
    print(version,len(assigned),len(booked),flush=True)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path)
    parser.add_argument("joint")
    parser.add_argument("incoming")
    parser.add_argument("--root",type=Path,default=Path("public/data/vancouver"))
    parser.add_argument("--pbf",type=Path,default=Path("data/region/vancouver.osm.pbf"))
    parser.add_argument("--geography",type=Path,default=Path("data/mobility"))
    parser.add_argument("--max-candidates",type=int,default=8)
    args = parser.parse_args()
    if args.max_candidates<1:
        parser.error("An address search needs at least one candidate")
    publish(args.root,args.archive,args.pbf,args.geography,args.joint,args.incoming,args.max_candidates)
