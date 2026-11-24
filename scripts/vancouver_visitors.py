"""Project off-campus origin shares into external UBC attendance and walkable café catchments."""
import argparse
import json
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

import duckdb
import numpy as np
from scipy.sparse.csgraph import dijkstra

from scripts.artifacts import read, write_json
from scripts.vancouver_campus import CAMPUS, campus_mask
from scripts.vancouver_cityday import xy
from scripts.vancouver_streets import walk_graph

SEED = 20261121
SITES = ["Great Dane Coffee", "Mercante", "Bean Around The World"]
OPEN, CLOSE = 660, 840
WALK_LIMIT = 400
# Conditional origin shares refer to off-campus students, but to all employees.
COHORTS = {
    "students": (49165 + 11144, .55, {"Richmond": .11, "Burnaby": .11}),
    "employees": (4087 + 11762, 1., {"Richmond": .07, "Burnaby": .06, "Surrey": .05}),
}
SOURCES = {
    "enrolment": "https://scs-senate-2021.sites.olt.ubc.ca/files/Item-7-UBC-Annual-Enrolment-Report-2025-26.pdf",
    "studentOrigins": "https://bog3.sites.olt.ubc.ca/files/2026/09/9c2_BOG_StudentAMSSurveyReport_-OPEN_20260923_Rev0.pdf",
    "employeeOrigins": "https://planning.ubc.ca/sites/default/files/2024-03/2022-11-10_-_UBC_Faculty_and_Staff_HNA_and_Programs_Review_-_FINAL.pdf",
    "employeeCounts": "https://planning.ubc.ca/sites/default/files/2024-03/CV_2050_Housing_Action_Plan_Background_Information.pdf",
}
USES = {"students": {"Academic", "Research"}, "employees": {"Academic", "Research", "Administrative", "Services", "Operations"}}


def intervals(episodes, activity):
    """Assign the whole continuous workplace/school block only when it contains the role activity."""
    spans = []
    start = end = None
    active = False
    for t, n, act, loc in episodes:
        if loc == "work-or-school":
            if start is None:
                start = t
            end = t+n
            active |= act == activity
        elif start is not None:
            if active:
                spans.append([start, end])
            start = None
            active = False
    if start is not None and active:
        spans.append([start, end])
    return spans


def buildings(geo, legal):
    out = []
    with duckdb.connect() as db:
        db.execute("load spatial")
        for f in geo["features"]:
            prop = f["properties"]
            if (not f["geometry"] or prop["CONSTR_STATUS"] != "Complete" or (prop["GBA"] or 0) <= 0
                    or prop["BLDG_USAGE"] not in USES["employees"]):
                continue
            lon,lat,inside = db.execute("""with p as (select st_pointonsurface(st_geomfromgeojson(?)) point)
                select st_x(point),st_y(point),st_covers(st_geomfromgeojson(?),point) from p""",
                [json.dumps(f["geometry"]),json.dumps(legal)]).fetchone()
            if inside:
                out.append(dict(id=prop["BLDG_UID"], name=prop["NAME"], point=xy(lon,lat),
                                use=prop["BLDG_USAGE"], area=prop["GBA"]))
    return sorted(out,key=lambda b:b["id"])


def reachable(street_dir, places, on_campus, anchors):
    graph,snap=walk_graph(read(street_dir/"network.json"))
    pts=np.asarray([p[:2] for p in places]+[b["point"] for b in anchors])
    nodes,off=snap(pts)
    sites=[];within=[]
    for name in SITES:
        matches={tuple(p[:2]) for p,inside in zip(places,on_campus) if inside and p[3]==name}
        if len(matches)!=1:
            raise ValueError(f"Expected one distinct campus location for {name}, found {len(matches)}")
        pt=next(iter(matches))
        node,offset=snap(pt)
        dist=dijkstra(graph,indices=node,limit=WALK_LIMIT)
        mask=offset+dist[nodes]+off<=WALK_LIMIT
        mask[:len(places)] &= on_campus
        sites.append(dict(name=name,point=list(pt)))
        within.append(mask)
    return sites,np.asarray(within)


def resident_catchments(atlas_dir, day_dir, within):
    m=read(day_dir/"day.json")
    ds=np.zeros((len(within),1441),dtype=int)
    unique=np.zeros(len(within),dtype=int)
    for da in m["das"]:
        people=read(atlas_dir/(da+".json"))["people"]
        plans=read(day_dir/(da+".json"))["plans"]
        buckets=defaultdict(list)
        for i,p in enumerate(people):
            buckets[p[7]].append(i)
        for k,indices in buckets.items():
            tpl=m["templates"][k]
            anchors=np.asarray([plans[i] for i in indices],dtype=int)
            lunchtime=np.zeros((len(within),len(indices)),dtype=bool)
            for start,length,mode,i,_ in tpl["parts"]:
                if mode!="stop":
                    continue
                place=anchors[:,i]
                active=within[:,place] & (place>=0)
                count=active.sum(axis=1)
                ds[:,start-240]+=count
                ds[:,start+length-240]-=count
                if start<CLOSE and start+length>OPEN:
                    lunchtime |= active
            unique+=lunchtime.sum(axis=1)
    return ds.cumsum(axis=1)[:,:-1],unique


def donor_pool(diaries,group,split):
    activity="study" if group=="students" else "paid-work"
    pool=[d for d in diaries if d["split"]==split and
          (d["enrolledAfterHighSchool"] if group=="students" else d["role"]=="worker")]
    days=[intervals(d["episodes"],activity) for d in pool]
    weights=np.asarray([d["weight"] for d in pool],dtype=float)
    if not len(pool) or not weights.sum():
        raise ValueError("No eligible diaries for "+group+" "+split)
    weights/=weights.sum()
    support=dict(diaries=len(days), attending=sum(bool(d) for d in days),
                 weekdayShare=float(sum(w for w,d in zip(weights,days) if d)))
    return days,weights,support


def visitors(diaries,group,anchors,within,seed):
    days,weights,fit=donor_pool(diaries,group,"fit")
    _,_,holdout=donor_pool(diaries,group,"holdout")
    eligible=np.asarray([i for i,b in enumerate(anchors) if b["use"] in USES[group]])
    sizes=np.array([anchors[i]["area"] for i in eligible],dtype=float)
    base,share,origins=COHORTS[group]
    ds=np.zeros((len(within)+1,1441),dtype=int)
    unique=np.zeros(len(within),dtype=int)
    groups=[]; attendees=0
    for ix,(city,fraction) in enumerate(origins.items()):
        diary_rng,building_rng=(np.random.default_rng([SEED,seed,ix,stream]) for stream in (0,1))
        n=round(base*share*fraction)
        templates=diary_rng.choice(len(days),n,p=weights)
        assignments=building_rng.choice(eligible,n,p=sizes/sizes.sum())
        roster=[];attending=0
        for tpl,b in zip(templates,assignments):
            roster.append([int(tpl),int(b)])
            spans=days[tpl]
            if not spans:
                continue
            attending+=1
            reachable_sites=np.flatnonzero(within[:,b])
            if any(s<CLOSE and e>OPEN for s,e in spans):
                unique[reachable_sites]+=1
            for s,e in spans:
                ds[0,s-240]+=1;ds[0,e-240]-=1
                ds[reachable_sites+1,s-240]+=1;ds[reachable_sites+1,e-240]-=1
        groups.append(dict(city=city,share=fraction,roster=roster,attending=attending))
        attendees+=attending
    counts=ds.cumsum(axis=1)[:,:-1]
    assert (counts>=0).all() and (counts[1:]<=counts[0]).all() and counts[0].max()<=attendees
    return dict(base=base,offCampusShare=share,groups=groups,templates=days,fit=fit,holdout=holdout,
                presence=counts.tolist(),lunch=unique.tolist(),attendees=attendees)


def build(region,versions,inputs,diaries):
    atlas_dir=region/"atlas"/versions["atlas"]
    day_dir=region/"cityday"/versions["day"]
    places=read(day_dir/"places.json")
    legal=read(atlas_dir/"atlas.json")["areas"][CAMPUS]["geometry"]
    on_campus=campus_mask(places,legal)
    anchor=buildings(read(inputs/"ubc-buildings.geojson"),legal)
    sites,within=reachable(region/"streets"/versions["streets"],places,on_campus,anchor)
    resident_counts,resident_unique=resident_catchments(atlas_dir,day_dir,within[:,:len(places)])
    for i,site in enumerate(sites):
        site.update(residents=resident_counts[i].tolist(),lunch=int(resident_unique[i]),
                    buildings=np.flatnonzero(within[i,len(places):]).tolist())
    layers={group:visitors(diaries,group,anchor,within[:,len(places):],i) for i,group in enumerate(COHORTS)}
    return dict(versions=versions,buildings=anchor,sites=sites,cohorts=layers,open=OPEN,close=CLOSE,
                walkMetres=WALK_LIMIT,sources=SOURCES)


def publish(archive,region,versions,inputs):
    diaries=json.loads(subprocess.check_output(["clojure","-M","-m","city.vancouver.atlas-diaries",str(archive),"--attendance"]))
    result=build(region,versions,inputs,diaries)
    dest=region/"visitors";dest.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest) as tmp:
        file=Path(tmp)/"cohorts.json";write_json(file,result)
        file.replace(dest/(versions["day"]+"_"+versions["streets"]+".json"))
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path)
    parser.add_argument("--region",type=Path,default=Path("public/data/vancouver/region"))
    parser.add_argument("--inputs",type=Path,default=Path("data/region"))
    parser.add_argument("--day",help="Use a published weekday under the current atlas")
    args=parser.parse_args()
    versions=read(args.region/"current.json")
    if args.day:
        versions["day"]=args.day
    result=publish(args.archive,args.region,versions,args.inputs)
    for k,c in result["cohorts"].items():
        print(k,c["fit"],c["holdout"],c["attendees"],c["lunch"])
