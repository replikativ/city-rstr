"""Reserve direct municipal riders on bus segments before assigning any transfers."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path

from scripts.vancouver_campus import access_routes
from scripts.vancouver_city_transit import DirectService
from scripts.vancouver_diary_transfers import income_coverage, publish_indexed_riders
from scripts.vancouver_downtown import station_counts
from scripts.vancouver_region import read
from scripts.vancouver_transit_commutes import pointer
from scripts.vancouver_transit_load import ANNUAL_TABLE, TABLE, BusSpaces, book_direct, bus_capacity_profile, bus_load_evidence


def publish(root, archive, fitted):
    directory = root/"diary-fit"
    fit = read(directory/(fitted+".json"))
    source = fit["scheduled"]["fitted"]["riders"]
    origin = root/"transit-riders"/source
    report = read(origin/"riders.json")
    versions = report["versions"]
    if report.get("transfers") or "capacityComparison" in report or any(
        versions[k]!=v for k,v in fit["locations"].items()
    ):
        raise ValueError("Capacity must be applied to the fitted weekday's direct journeys")

    schedule = root/"transit"/versions["transit"]
    service = DirectService(schedule)
    places = read(root/"cityday"/versions["day"]/"places.json")
    street_dir = root/"streets"/versions["streets"]
    raw = archive/"data/raw/probes"
    table = raw/TABLE
    profile = bus_capacity_profile(service.route_manifest,table,raw/ANNUAL_TABLE)
    limits = profile["limits"]
    spaces = BusSpaces(limits)
    planned = [row for da in report["das"] for row in read(origin/(da+".json"))]
    if len({tuple(row[:3]) for row in planned})!=len(planned) or len(planned)!=report["matched"]:
        raise ValueError("The direct timetable has missing or repeated trips")
    endpoints = {x for row in planned if row[6] in limits for x in row[4:6]}
    access = access_routes(places,endpoints,service.stations,street_dir)
    find_ride = service.matcher(access,available=spaces.available)
    admitted, denied, rerouted = book_direct(planned, spaces, find_ride)
    rejected = len(denied)
    by_da = defaultdict(list)
    for row in admitted:
        by_da[row[0]].append(row)
    before = bus_load_evidence(schedule,service.route_manifest,planned,table,limits)
    after = bus_load_evidence(schedule,service.route_manifest,admitted,table,limits)
    if after["above"] or rejected != len(planned)-len(admitted):
        raise ValueError("The direct rider capacity checks do not reconcile")
    by_route, examples = Counter(), {}
    for rows in by_da.values():
        rows.sort(key=lambda row:(row[1],row[2]))
        for row in rows:
            id = row[6]
            by_route[id] += 1
            if id not in examples or abs(row[2]-720)<abs(examples[id][2]-720):
                examples[id] = row
    comparison = dict(sourceRelease=source,kept=len(admitted)-rerouted,rerouted=rerouted,rejected=rejected,
                      planned=len(planned),admitted=len(admitted),busBefore=before["above"],busAfter=after["above"])
    report.update(matched=len(admitted),das=sorted(by_da),byRoute=by_route,examples=examples,
                  capacityComparison=comparison,bus=dict(before=before,after=after),capacitySources=profile["sources"])
    report["excluded"]["capacity"] = rejected
    downtown = read(origin/"downtown.json")
    downtown["rail"] = station_counts(raw/"transit_translink_tspr2025_skytrainavgalightsbrdgs_yearstationdaytypehourly.csv",
                                     schedule,service.route_manifest,by_da)
    downtown["capacityChecked"] = True
    result = publish_indexed_riders(root,report,downtown,by_da)
    pointer(directory/(fitted+"_capacity.json"),dict(atlas=fitted,day=versions["day"],riders=result,
                                                     transit=versions["transit"],comparison=comparison,
                                                     income=income_coverage(root,fit,by_da)))
    print(result,comparison,flush=True)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path)
    parser.add_argument("fitted_atlas")
    parser.add_argument("--root",type=Path,default=Path("public/data/vancouver"))
    args=parser.parse_args()
    publish(args.root,args.archive,args.fitted_atlas)
