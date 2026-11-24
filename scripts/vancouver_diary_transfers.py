"""Add capacity-checked transfers to a municipal diary replay's direct rides."""
import argparse
from collections import Counter, defaultdict
from itertools import chain
from pathlib import Path

import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_city_transit import DirectService, publish_walks, resident_trips
from scripts.vancouver_downtown import station_counts
from scripts.vancouver_income_travel import roster_bands
from scripts.vancouver_joint_weekday import timetable_with_transfers
from scripts.vancouver_region import package, read
from scripts.vancouver_street_scenarios import CITY_TRANSIT, publish_index
from scripts.vancouver_transit_commutes import BOARDING_MARGIN_SECONDS, pointer
from scripts.vancouver_transit_load import ANNUAL_TABLE, TABLE, BusSpaces, book_connections, bus_capacity_profile, bus_load_evidence
from scripts.vancouver_work_transit import transfer_inputs


def add_connections(root, report, original, schedule, raw, unbooked):
    versions = report["versions"]
    day = root/"cityday"/versions["day"]
    atlas = root/"atlas"/versions["atlas"]
    streets = root/"streets"/versions["streets"]
    service = DirectService(schedule)
    places = read(day/"places.json")
    by_da = defaultdict(list, {da: read(original/(da+".json")) for da in report["das"]})
    direct = list(chain.from_iterable(by_da.values()))
    reserved = {tuple(row[:3]) for row in direct}
    if len(reserved) != len(direct) or len(direct) != report["matched"]:
        raise ValueError("The direct rider release has missing or repeated itineraries")
    denied = set()
    if unbooked is not None:
        raw_report = read(unbooked/"riders.json")
        original_keys = {tuple(row[:3]) for da in raw_report["das"] for row in read(unbooked/(da+".json"))}
        if not reserved <= original_keys:
            raise ValueError("The capacity release contains unexpected direct trips")
        denied = original_keys - reserved
    if len(denied) != report["excluded"].get("capacity",0):
        raise ValueError("The direct capacity exclusions do not reconcile")
    bouts, _ = resident_trips(atlas, day)
    unfilled = [row for row in bouts if tuple(row[:3]) not in reserved and places[row[4]][:2]!=places[row[5]][:2]]
    windows = {(s,s+n,a,b) for _,_,s,n,a,b in unfilled}
    access, planner = transfer_inputs(windows, places, service, streets, schedule)
    candidates = [row for row in unfilled if row[4] in access and row[5] in access]
    if len(candidates) != report["excluded"]["schedule"]+len(denied):
        raise ValueError("The transfer search and direct trips have different stop access")

    manifest = service.route_manifest
    table = raw/TABLE
    limits = bus_capacity_profile(manifest,table,raw/ANNUAL_TABLE)["limits"]
    spaces = BusSpaces(limits)
    spaces.preload(row[6:10] for row in direct)
    admitted, schedule_missing, capacity_missing, recovered = book_connections(candidates, planner, spaces, denied)

    before = bus_load_evidence(schedule,manifest,direct,table,limits)
    after = bus_load_evidence(schedule,manifest,chain(direct,admitted),table,limits)
    if before["above"] != after["above"] or (unbooked is not None and after["above"]):
        raise ValueError("Added connections overloaded a bus run")
    return by_da, admitted, schedule_missing, capacity_missing, recovered, before, after


def income_coverage(root, fit, rows):
    atlas = root/"atlas"/fit["fittedAtlas"]
    valid = {int(i):row for i,row in fit["results"].items()}
    counts = defaultdict(Counter)
    for da, trips in rows.items():
        roster = read(atlas/(da+".json"))
        bands = roster_bands(roster)
        for row in trips:
            i = row[1]
            age = roster["people"][i][0]
            if bands[i] in valid and 3 <= age <= 13:
                counts[bands[i]]["transfers" if len(row)>12 else "direct"] += 2 if age==3 else 5
    result = {}
    for band, data in valid.items():
        averages = data["assigned"]["fitted"][:6]
        total = sum(averages)*data["adults"]
        diary = averages[2]*data["adults"]
        direct, transfers = (counts[band][k]/5 for k in ("direct","transfers"))
        if direct+transfers>diary+1e-6:
            raise ValueError("Scheduled rides outnumber recorded transit bouts in an income bracket")
        result[band] = dict(linkedTrips=total,transitBouts=diary,direct=direct,transfers=transfers)
    return result


def publish_indexed_riders(root, report, downtown, by_da):
    model = read(root/"cityday"/report["versions"]["day"]/"day.json")
    da_indexes = {da:d for d,da in enumerate(model["das"])}
    sample_keys = {(model["das"][d],i) for d,i,*_ in model["sample"]}
    all_rows = list(chain.from_iterable(by_da.values()))
    if (len(all_rows)!=report["matched"] or report["matched"]+sum(report["excluded"].values())!=report["total"]):
        raise ValueError("The paired timetable outcomes do not reconcile")

    def stage(out):
        for da,rows in by_da.items():
            write_json(out/(da+".json"),rows)
        write_json(out/"riders.json",report)
        write_json(out/"downtown.json",downtown)
        write_json(out/"departures.json",[[da_indexes[da],i,start] for da,i,start,*_ in all_rows])
        write_json(out/"sample.json",[row for row in all_rows if tuple(row[:2]) in sample_keys])

    version = package(root,"transit-riders",stage)
    publish_walks(root,version)
    publish_index(root,CITY_TRANSIT,version)
    return version


def publish(root, archive, fitted, booked_direct=False):
    fit = read(root/"diary-fit"/(fitted+".json"))
    release = fit["scheduled"]["fitted"]["riders"]
    unbooked = None
    if booked_direct:
        capacity = read(root/"diary-fit"/(fitted+"_capacity.json"))
        comparison = capacity["comparison"]
        if capacity["atlas"] != fitted or comparison["sourceRelease"] != release or comparison["busAfter"] != 0:
            raise ValueError("The direct capacity release must use the fitted timetable with no overloaded bus runs")
        unbooked = root/"transit-riders"/release
        release = capacity["riders"]
    original = root/"transit-riders"/release
    report = read(original/"riders.json")
    versions = report["versions"]
    if report.get("transfers") or any(versions[k]!=v for k,v in fit["locations"].items()):
        raise ValueError("The transfer comparison requires the fitted weekday's direct rider release")
    if booked_direct and (report.get("capacityComparison") != comparison or capacity["transit"] != versions["transit"]):
        raise ValueError("The reported direct bookings do not match the capacity comparison")
    raw = archive/"data/raw/probes"
    timetable = timetable_with_transfers(root,fitted,versions["transit"],raw/"transit_translink_gtfs_static.zip")
    schedule = root/"transit"/timetable
    by_da, added, missing, capacity_missing, recovered, before, after = add_connections(
        root,report,original,schedule,raw,unbooked)
    for row in added:
        by_da[row[0]].append(row)
        for route in (row[6],row[12][0]):
            report["byRoute"][route] = report["byRoute"].get(route,0)+1
            report["examples"].setdefault(route,row)
    for rows in by_da.values():
        rows.sort(key=lambda row: (row[1],row[2]))
    report["transfers"] = dict(direct=report["matched"],added=len(added),candidates=len(added)+missing+capacity_missing,
                               capacity=capacity_missing,sourceRelease=release,marginSeconds=BOARDING_MARGIN_SECONDS,
                               example=min(added,key=lambda row:(abs(row[2]-480), row[:3]),default=None))
    if booked_direct:
        report["transfers"].update(bookedDirect=True,recoveredDirect=recovered)
    report["matched"] += len(added)
    report["excluded"]["schedule"] = missing
    report["excluded"]["capacity"] = capacity_missing
    report["bus"] = dict(before=before,after=after)
    report["versions"]["transit"] = timetable
    report["das"] = sorted(by_da)
    downtown = read(original/"downtown.json")
    table = raw/"transit_translink_tspr2025_skytrainavgalightsbrdgs_yearstationdaytypehourly.csv"
    downtown["rail"] = station_counts(table,schedule,read(schedule/"transit.json"),by_da)
    downtown["transfers"] = True

    version = publish_indexed_riders(root,report,downtown,by_da)
    suffix = "_booked_transfers.json" if booked_direct else "_transfers.json"
    pointer(root/"diary-fit"/(fitted+suffix),dict(day=versions["day"],atlas=fitted,riders=version,
                                                          transit=timetable,comparison=report["transfers"],
                                                          income=income_coverage(root,fit,by_da)))
    print(version,report["transfers"],flush=True)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path)
    parser.add_argument("fitted_atlas")
    parser.add_argument("--root",type=Path,default=Path("public/data/vancouver"))
    parser.add_argument("--booked-direct",action="store_true",help="start from already capacity-checked direct riders")
    args = parser.parse_args()
    publish(args.root,args.archive,args.fitted_atlas,args.booked_direct)
