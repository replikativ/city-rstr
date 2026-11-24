"""Verify each published outbound transit booking and its contribution to the workplace clock."""
import argparse
from bisect import bisect_right
from collections import Counter
from math import dist
from pathlib import Path

from scripts.artifacts import pointer, read
from scripts.vancouver_incoming_duration_check import DISTANCE, DURATION, SOURCE, duration_margins, summarize
from scripts.vancouver_outbound_road_counts import verify_work_clock
from scripts.vancouver_outbound_road_jobs import digest
from scripts.vancouver_transit_load import ride_legs


def clock_check(rows, timetable, margin):
    def leg_time(leg):
        route,run,board,alight = leg[:4]
        r = timetable[route]
        pattern,clock,times,_ = r["rides"][run]
        rules = r["patterns"][pattern]
        if not (board<alight and rules["mapped"] and rules["access"][board]&1 and rules["access"][alight]&2):
            raise ValueError("A transit reservation violates the mapped boarding or alighting rules")
        return clock+times[2*board+1], clock+times[2*alight]

    journeys = Counter()
    for row in rows:
        start,duration = row[2:4]
        ride = row[6:]
        dep,arr = leg_time(ride)
        if dep < start*60+ride[4]+margin or arr<=dep:
            raise ValueError("A booked trip cannot be reached in its original diary window")
        count, onward = 1, ride[6] if len(ride)>6 else None
        while onward:
            dep,new_arr = leg_time(onward)
            if dep<arr+onward[5] or new_arr<=dep or onward[5]<onward[4]+margin:
                raise ValueError("A transfer misses its required walking or interchange time")
            arr = new_arr
            count += 1
            onward = onward[7] if len(onward)>7 else None
        if arr+ride[5] > (start+duration)*60 or count>3:
            raise ValueError("A booked trip arrives after the next activity or exceeds the transfer limit")
        journeys[count-1] += 1
    return [journeys[i] for i in range(3)]


def duration_check(rows, places, homes, timetable, table):
    cohort = []
    for row in rows:
        da,i,start,duration,a,b = row[:6]
        if a!=homes[da][i]:
            continue
        route,run,_,alight = list(ride_legs(row[6:]))[-1]
        _,clock,times,_ = timetable[route]["rides"][run]
        arrival = (clock+times[2*alight]+row[11])/60
        kilometres = dist(places[a][:2],places[b][:2])/1000
        cohort.append((("5915022",bisect_right(DISTANCE,kilometres)-1),duration,arrival-start))
    margins = duration_margins(table,["5915022"])
    return dict(source=SOURCE,digest=digest(table),distanceLowerKm=DISTANCE,durationLowerMinutes=DURATION,
                **summarize(cohort,margins))


def publish(root,version,road_version=None,table=Path("data/mobility/98100461-eng.zip")):
    base = root/"outbound-transit"/version
    report = read(base/"report.json")
    jobs = read(base/"places.json")
    day = root/"cityday"/report["versions"]["day"]
    catalogue = read(day/"day.json")
    schedule = root/"transit"/report["timetable"]
    data = {}
    rows = []
    by_city = Counter()
    for da in report["areas"]:
        for i,site,_,legs in read(base/f"{da}.json"):
            job = site+report["basePlaces"]
            if {leg[4]==job for leg in legs}!={True,False} or any(
                    leg[:2]!=[da,i] or min(leg[4:6])>=report["basePlaces"] or max(leg[4:6])!=job for leg in legs):
                raise ValueError("A worker's outbound and return trips do not share the published workplace")
            rows.extend(legs)
            by_city[jobs[site][4]] += 1
    keys = {(r[0],r[1],r[2]) for r in rows}
    if len(keys)!=len(rows) or len(rows)!=report["journeys"] or sum(by_city.values())!=report["workers"]:
        raise ValueError("Outbound transit journeys and roster differ")
    for route in {leg[0] for row in rows for leg in ride_legs(row[6:])}:
        data[route] = read(schedule/f"{route}.json")
    counts = clock_check(rows,data,report["boardingMargin"])
    check = duration_check(rows,[*read(day/"places.json"),*jobs],
                           {da:read(day/f"{da}.json")["home"] for da in report["areas"]},data,table)
    clock = verify_work_clock(root,base,report,catalogue,jobs)
    if clock["agents"]!=report["workers"]:
        raise ValueError("The workplace clock uses a different set of residents")
    if road_version:
        road = root/"outbound-road-jobs"/road_version
        roads = read(road/"report.json")
        old = read(root/"outbound-road-counts"/f"{road_version}.json")
        if roads["joint"]!=report["joint"] or old["jobs"]!=road_version:
            raise ValueError("Outbound road and transit jobs use different weekdays")
        for da in set(roads["areas"]) & set(report["areas"]):
            if {r[0] for r in read(road/f"{da}.json")} & {r[0] for r in read(base/f"{da}.json")}:
                raise ValueError("A resident has both a road and a transit workplace")
        if any(sum(t[1:])>r[0] or sum(t)!=sum(r) for t,r in zip(clock["counts"],old["workClock"]["counts"],strict=True)):
            raise ValueError("The road and transit workplace clocks do not reconcile")
    sample_rows = {}
    for da,row in clock["sample"]:
        sample_rows.setdefault(da,set()).add(row[0])
    sample_walks = {da:[r for r in read(base/f"{da}-walks.json") if r[0] in people] for da,people in sample_rows.items()}
    pointer(root/"outbound-transit-audit"/f"{version}.json",dict(release=version,joint=report["joint"],
            timetable=report["timetable"],road=road_version,direct=counts[0],oneTransfer=counts[1],twoTransfers=counts[2],
            workClock=clock,sampleWalks=sample_walks,commuteDurations=check))
    print(version,counts,"mapped",len(jobs),"at noon",sum(clock["counts"][480][1:]),"weighted groups",clock["groups"],
          "commute durations",check["compared"],check["meanMinutes"],flush=True)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--root",type=Path,default=Path("public/data/vancouver"))
    parser.add_argument("--road")
    parser.add_argument("--table",type=Path,default=Path("data/mobility/98100461-eng.zip"))
    args=parser.parse_args()
    publish(args.root,args.version,args.road,args.table)
