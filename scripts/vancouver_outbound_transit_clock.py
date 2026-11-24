"""Check and replay outbound transit timing with the original vehicles and paid shifts."""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import csv
from math import ceil, dist
from pathlib import Path
import tempfile
from zipfile import ZipFile

import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_discretionary_outings import verify_intervals
from scripts.vancouver_downtown import MODE_INDEX, MODES, station_counts
from scripts.vancouver_incoming_duration_check import DISTANCE, DURATION, SOURCE, duration_margins, summarize
from scripts.vancouver_outbound_road_jobs import digest
from scripts.vancouver_region import package, read
from scripts.vancouver_transit_commutes import pointer
from scripts.vancouver_transit_load import ride_legs


DEPARTURE_LOWER = (300,360,420,480,540,720)
VANCOUVER = "5915022"
RAIL_COUNTS = "transit_translink_tspr2025_skytrainavgalightsbrdgs_yearstationdaytypehourly.csv"


def trip_clock(row, timetable, margin):
    """Seconds on the original trip clock and the latest full minute to depart."""
    start,duration = row[2:4]
    rides = [row[6:]]
    onward = row[12] if len(row)>12 else None
    while onward:
        rides.append(onward)
        onward = onward[7] if len(onward)>7 else None
    first_board = previous_arrival = 0
    in_vehicle = interchange_wait = interchange_walk = 0
    for j,leg in enumerate(rides):
        route,run,board,alight = leg[:4]
        _,clock,times,_ = timetable[route]["rides"][run]
        depart,arrive = clock+times[2*board+1],clock+times[2*alight]
        if j:
            walk_seconds,required = leg[4:6]
            if depart-previous_arrival<required or required<walk_seconds+margin:
                raise ValueError("The published path no longer fits the interchange time")
            interchange_wait += depart-previous_arrival-walk_seconds
            interchange_walk += walk_seconds
        else:
            first_board = depart
        if arrive<=depart:
            raise ValueError("The published vehicle leg has an invalid clock")
        in_vehicle += arrive-depart
        previous_arrival = arrive
    access,egress = row[10:12]
    leave = (first_board-access-margin)//60
    arrival = previous_arrival+egress
    wait = first_board-access-start*60
    walking = access+interchange_walk+egress
    if leave<start or arrival>(start+duration)*60 or arrival-start*60!=walking+wait+interchange_wait+in_vehicle:
        raise ValueError("The retimed arrival and departure must fit the original travel window")
    return leave,arrival,(walking,wait,interchange_wait,in_vehicle)


def departure_band(minute):
    return (bisect_right(DEPARTURE_LOWER,minute%1440)-1)%6


def departure_margins(table):
    """Departure bands by distance for Vancouver residents with transit as the usual mode."""
    counts = defaultdict(dict)
    with ZipFile(table) as zone, zone.open("98100461.csv") as file:
        header = next(csv.reader([next(file).decode("utf-8-sig")]))
        i = {key:header.index(key) for key in ("DGUID","Coordinate","Statistics (3)","Main mode of commuting (11A)",
                                              "Commuting duration (7):Total - Commuting duration[1]")}
        total = i["Commuting duration (7):Total - Commuting duration[1]"]
        rows = csv.reader(line.decode("utf-8") for line in file if b"2021A00055915022" in line and b"Public transit" in line)
        for row in rows:
            if row[i["DGUID"]]!="2021A0005"+VANCOUVER or row[i["Statistics (3)"]]!="Count" or row[i["Main mode of commuting (11A)"]]!="Public transit":
                continue
            _,km,start,*_ = map(int,row[i["Coordinate"]].split("."))
            if km>=2 and 2<=start<=7:
                counts[km-2][start-2] = int(row[total]) if row[total] and not row[total+1] else None
    return {band:[cells[j] for j in range(6)] for band,cells in counts.items()
            if len(cells)==6 and None not in cells.values() and sum(cells.values())>0}


def departure_check(rows, margins):
    baseline,timed,expected = np.zeros(6,dtype=int),np.zeros(6,dtype=int),np.zeros(6)
    n = 0
    for band,first,leave in rows:
        if band not in margins:
            continue
        prior = np.asarray(margins[band])
        expected += prior/prior.sum()
        baseline[departure_band(first)] += 1
        timed[departure_band(leave)] += 1
        n += 1
    if n==0:
        raise ValueError("No Census departure bands match the outbound home trips")
    error = lambda model: float(np.abs(model-expected).sum()*100/(n*len(expected)))
    return dict(compared=n,lowerMinutes=DEPARTURE_LOWER,recorded=baseline.tolist(),timed=timed.tolist(),
                expected=expected.tolist(),maePoints=[error(baseline),error(timed)])


def publish(root,archive,release,table,road):
    parent = root/"outbound-transit"/release
    report = read(parent/"report.json")
    audit = read(root/"outbound-transit-audit"/f"{release}.json")
    if report["joint"]!=audit["joint"] or release!=audit["release"] or report["timetable"]!=audit["timetable"] or audit["road"]!=road:
        raise ValueError("The outbound audit does not cover this pair of road and transit layers")
    day_dir = root/"cityday"/report["versions"]["day"]
    atlas_dir = root/"atlas"/report["versions"]["atlas"]
    day = read(day_dir/"day.json")
    areas = day["areas"]
    atlas = read(atlas_dir/"atlas.json")
    district = {da:areas.index(name) for name,value in atlas["areas"].items() for da in value["das"]}
    original = read(day_dir/"places.json")
    places = original+read(parent/"places.json")
    if len(original)!=report["basePlaces"]:
        raise ValueError("The jobs layer and weekday use different places")
    core, travel, missing, external = areas.index("Downtown"),len(areas),len(areas)+1,len(areas)+2
    cols = external+1
    joint = root/"joint-weekday"/report["joint"]
    raw_stock = np.asarray(read(joint/"occupancy.json"))
    road_clock = read(root/"outbound-road-counts"/f"{road}.json")["workClock"]
    paid_transit = np.asarray(audit["workClock"]["counts"])[:,1:].sum(axis=1)
    paid_road = np.asarray(road_clock["counts"])[:,1:].sum(axis=1)
    baseline = np.column_stack([raw_stock, paid_road+paid_transit])
    baseline[:,missing] -= baseline[:,external]
    if np.any(baseline<0) or not np.all(baseline.sum(axis=1)==day["population"]):
        raise ValueError("Mapped external jobs must be reclassified from the unresolved count")

    timetable_dir = root/"transit"/report["timetable"]
    manifest = read(timetable_dir/"transit.json")
    timetable = {}
    durations,dep_times,delta_windows = [],[],{}
    phases = Counter()
    by_da = defaultdict(list)
    schedules = []
    moved = np.zeros((1441,cols),dtype=np.int32)
    flows = np.zeros((24,len(areas),2,len(MODES)),dtype=np.int32)
    trips = delayed = shortened = 0
    def zone(p):
        if p>=len(original):
            return external
        return places[p][2] if places[p][2]>=0 else missing

    for da in report["areas"]:
        homes = read(day_dir/f"{da}.json")["home"]
        people = read(atlas_dir/f"{da}.json")["people"]
        local = []
        for i,_,_,rows in read(parent/f"{da}.json"):
            parts = {part[0]:part[2] for part in day["templates"][people[i][7]]["parts"]}
            intervals,patch = [],[]
            for row in rows:
                _,_,start,duration,a,b = row[:6]
                for route,*_ in ride_legs(row[6:]):
                    if route not in timetable:
                        timetable[route] = read(timetable_dir/f"{route}.json")
                leave,arrival,components = trip_clock(row,timetable,report["boardingMargin"])
                finish = ceil(arrival/60)
                end = start+duration
                a_zone,b_zone = zone(a),zone(b)
                trips += 1
                delayed += int(leave>start)
                shortened += int(finish<end)
                patch.append([start,leave,arrival])
                by_da[da].append(row)
                for lo,hi,area in ((start,leave,a_zone),(finish,end,b_zone)):
                    if lo<hi:
                        intervals.append(((lo-240)*cols+travel,(hi-240)*cols+travel,area-travel))
                        moved[lo-240:hi-240,area] += 1
                        moved[lo-240:hi-240,travel] -= 1
                if (a_zone==core)!=(b_zone==core):
                    arriving = b_zone==core
                    moment = end if arriving else start
                    timed = finish if arriving else leave
                    idx = district[da],0 if arriving else 1, MODE_INDEX.get(parts[start],len(MODES)-1)
                    flows[(moment//60%24,*idx)] -= 1
                    flows[(timed//60%24,*idx)] += 1
                if a==homes[i]:
                    km = dist(places[a][:2],places[b][:2])/1000
                    band = bisect_right(DISTANCE,km)-1
                    durations.append(((VANCOUVER,band),arrival/60-start,arrival/60-leave))
                    dep_times.append((band,start,leave))
                    for key,value in zip(("walking","initialWait","transferWait","onVehicles"),components,strict=True):
                        phases[key] += value
                    phases["atOrigin"] += (leave-start)*60
            if intervals:
                schedules.append(tuple(intervals))
            local.append([i,patch])
        if local:
            delta_windows[da] = local
    if trips!=report["journeys"] or not np.all(flows.sum(axis=0)==0):
        raise ValueError("The retimed journeys and Downtown boundaries do not reconcile")
    old_flows = read(root/"transit-riders"/read(joint/"report.json")["riders"]/"downtown.json")
    if old_flows["areas"]!=areas or old_flows["modes"]!=MODES or np.any(np.asarray(old_flows["counts"])+flows<0):
        raise ValueError("The retimed Downtown trips do not fit the baseline counts")
    rail = station_counts(archive/"data/raw/probes"/RAIL_COUNTS,timetable_dir,manifest,by_da)
    with tempfile.TemporaryDirectory(dir=root/"outbound-transit") as tmp:
        clock = verify_intervals(schedules,moved,baseline,Path(tmp),"jvm")
    margins = duration_margins(table,[VANCOUVER])
    check = summarize(durations,margins)
    n = len(durations)
    mean = {key:v/(60*n) for key,v in phases.items()}
    check["diaryMinutes"] = audit["commuteDurations"]["meanMinutes"][0]
    result = dict(release=release,road=road,joint=report["joint"],timetable=report["timetable"],areas=areas,
                  source=SOURCE,digest=digest(table),rail=rail,departures=departure_check(dep_times,departure_margins(table)),
                  distanceLowerKm=DISTANCE,durationLowerMinutes=DURATION,
                  durations=check,meanMinutesByStage=mean,journeys=trips,departuresMoved=delayed,arrivalsMoved=shortened,
                  windows=delta_windows,downtownDelta=flows.tolist(),
                  occupancyDelta=clock.pop("occupancyDelta"),execution=clock)
    def build(folder):
        write_json(folder/"clock.json",result)
    version = package(root,"outbound-transit-clock",build)
    pointer(root/"outbound-transit-clock"/f"{release}.json",dict(version=version))
    print(version,"duration",check["meanMinutes"],"stages",mean,"departures",result["departures"],
          "retimed",delayed,shortened,"raster",clock,flush=True)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path)
    parser.add_argument("release")
    parser.add_argument("--road",required=True)
    parser.add_argument("--root",type=Path,default=Path("public/data/vancouver"))
    parser.add_argument("--table",type=Path,default=Path("data/mobility/98100461-eng.zip"))
    args=parser.parse_args()
    publish(args.root,args.archive,args.release,args.table,args.road)
