"""Check whether geocoded outbound jobs change the combined weekday's road counts."""
import argparse
from pathlib import Path
import tempfile

import numpy as np

from scripts.artifacts import pointer, read
from scripts.vancouver_bridge_traffic import ARCHIVE, IRONWORKERS_FILE, score_window
from scripts.vancouver_discretionary_outings import verify_intervals
from scripts.vancouver_incoming_road_crossings import CITY_LIMIT_SOURCE, Cordon, PassageCounter, city_ring, road_screens
from scripts.vancouver_outbound_road_jobs import digest
from scripts.vancouver_workplace_drives import score


def driving_legs(directory, report, day):
    das = {da:i for i,da in enumerate(day["das"])}
    rows = []
    for da in report["areas"]:
        for i,site,_,legs in read(directory/f"{da}.json"):
            job = report["basePlaces"]+site
            for start,duration,anchor,from_work,driver,elapsed in legs:
                if driver:
                    a,b = (job,anchor) if from_work else (anchor,job)
                    rows.append([1,a,b,start,duration,das[da],i])
    if len(rows) != sum(row.get("locatedDriverLegs",0) for row in report["coverage"].values()):
        raise ValueError("The road replay and feasible outbound workplaces have different trip counts")
    return np.asarray(rows, dtype=int).reshape(-1,7)


def verify_work_clock(root, folder, report, catalogue, jobs):
    """Reclassify external workers from municipality-only to a known location."""
    base = root/"outbound"/report["workplaces"]["outbound"]
    outbound = read(base/"report.json")
    groups = read(base/"assignments.json")
    atlas = root/"atlas"/report["versions"]["atlas"]
    da_index = {da:i for i,da in enumerate(catalogue["das"])}
    names = sorted({row[4] for row in jobs})
    cities = {name:i for i,name in enumerate(names,1)}
    cols = len(cities)+1
    changes = np.zeros((1441,cols),dtype=np.int32)
    base_stock = np.zeros((1440,cols),dtype=np.int32)
    base_stock[:,0] = outbound["externalByMinute"]
    schedules = []
    sample = {(d,i) for d,i,*_ in catalogue["sample"]}
    preview = []
    for da in report["areas"]:
        d = da_index[da]
        census = {i:outbound["destinations"][place] for i,place,*_ in groups[d]}
        people = read(atlas/f"{da}.json")["people"]
        for row in read(folder/f"{da}.json"):
            i,site,slots,_ = row
            city = jobs[site][4]
            template = people[i][7]
            if census[i]!=city or set(slots)!=set(outbound["slots"][template]):
                raise ValueError("An external workplace altered its resident's destination or paid work slots")
            zone = cities[city]
            intervals = [(start-240,start+duration-240) for start,duration,mode,a,_ in catalogue["templates"][template]["parts"]
                         if mode=="stop" and a in slots]
            schedules.append(tuple((start*cols,end*cols,zone) for start,end in intervals))
            for start,end in intervals:
                changes[start:end,0] -= 1
                changes[start:end,zone] += 1
            if (d,i) in sample:
                preview.append([da,row])
    with tempfile.TemporaryDirectory(dir=root/"outbound-road-jobs") as tmp:
        result = verify_intervals(schedules,changes,base_stock,Path(tmp),"jvm")
    return dict(backend=result["backend"],agents=result["agents"],groups=result["groups"],municipalities=names,
                counts=(base_stock+changes[:-1]).tolist(),sample=preview)


def publish(root, archive, version, ironworkers):
    folder = root/"outbound-road-jobs"/version
    report = read(folder/"report.json")
    day = root/"cityday"/report["versions"]["day"]
    places = read(day/"places.json")
    if len(places)!=report["basePlaces"]:
        raise ValueError("The new jobs do not align with the existing places")
    jobs = read(folder/"places.json")
    coords = [p[:2] for p in [*places,*jobs]]
    catalogue = read(day/"day.json")
    rows = driving_legs(folder,report,catalogue)
    work_clock = verify_work_clock(root,folder,report,catalogue,jobs)
    road = root/"commuter-drive"/report["network"]
    network,profile = (read(road/f"{name}.json") for name in ("network","profile"))
    counters = archive/"data/raw/probes"/ARCHIVE
    sites,arcs = road_screens(network,counters,ironworkers)
    coverage,_ = score_window(rows,coords,network,sites,catalogue["das"],scenarios=1,profile=profile,arcs=arcs,elapsed=True)
    for site in sites:
        scenario, = site.pop("scenarios")
        site.update(scenario)
    boundary = archive/"data/raw/statcan/vancouver_city_boundary.geojson"
    cordon = Cordon(city_ring(boundary),network["nodes"],coords)
    passages = PassageCounter(network["nodes"],coords,catalogue["das"],cordon,{},1,work_inside=False,record_start=True)
    ordered = [[d,i,start,duration,a,b,a,b,int(a<report["basePlaces"])] for _,a,b,start,duration,d,i in rows]
    score(ordered,coords,network,profile,{"corridors":[]},on_paths=passages)
    scope = dict(passages.outcomes[0])
    if scope["feasible"]!=len(rows):
        raise ValueError("The city limit check did not reproduce all placed work drives")
    witnesses = {(catalogue["das"][d],int(i),int(start)): [int(start),int(n),int(a),int(b)]
                 for _,a,b,start,n,d,i in rows}
    examples = [[None]*24 for _ in range(2)]
    for d in range(2):
        for h in range(24):
            example = passages.examples.get((0,0,d,h))
            if example:
                da,i,minute,point,start = example
                leg = witnesses[da,i,start]
                examples[d][h] = [da,i,minute,*leg,point]
    sites.insert(0,dict(key="city",name="Vancouver city limit",directions=["Into Vancouver","Out of Vancouver"],
                        source=CITY_LIMIT_SOURCE,counts=passages.counts[0,0].tolist(),examples=examples))
    sources = {p.name:digest(p) for p in (counters,ironworkers,boundary)}
    pointer(root/"outbound-road-counts"/f"{version}.json",dict(jobs=version,joint=report["joint"],network=report["network"],
            clock=report["clock"],coverage=coverage[0],boundary=scope,workClock=work_clock,sources=sources,sites=sites))
    print(version,coverage[0],scope,{site["key"]:np.asarray(site["counts"])[:,7:9].sum(axis=1).tolist() for site in sites},flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path)
    parser.add_argument("version")
    parser.add_argument("--root",type=Path,default=Path("public/data/vancouver"))
    parser.add_argument("--ironworkers",type=Path,default=Path("data/mobility")/IRONWORKERS_FILE)
    args = parser.parse_args()
    publish(args.root,args.archive,args.version,args.ironworkers)
