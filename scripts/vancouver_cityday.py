"""Locate the atlas residents' complete weekdays and publish version-matched city geometry."""
import argparse
import csv
import hashlib
import json
import math
import re
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from scripts.artifacts import write_json
from scripts.vancouver_mobility import MobilityAudit
from scripts.vancouver_walks import MOBILE

# Local metres, east and south positive, shared with the population atlas.
ORIGIN = (-123.1,49.26)
SCALE = (72600,-111195)
SPEED = {"walk":75,"bike":220,"transit":260,"car-driver":380,"car-passenger":380,
         "motorcycle":380,"taxi":380,"ridehail":380,"travel-ns":85}
VENUE_TYPES = {"store":"store|shopping|market|bakery|pharmacy","restaurant":"restaurant|cafe|coffee_shop|pub$|fast_food",
               "outdoors":"park$|beach|garden","sports-venue":"sports|fitness|gym","culture":"gallery|museum|theater|library",
               "worship":"church|mosque|synagogue|temple","clinic":"clinic|hospital|doctor|dentist",
               "college":"college|university|higher_education"}


def xy(lon,lat):
    return [round((lon-ORIGIN[0])*SCALE[0]),round((lat-ORIGIN[1])*SCALE[1])]


def receipts(folder,dataset,field):
    for f in sorted(folder.glob("*.receipt.edn")):
        note=f.read_text()
        match=re.search(field,note)
        if f':dataset "{dataset}"' in note and match and not match[1].startswith("DA "):
            yield Path(str(f).removesuffix(".receipt.edn"))


def licensed_jobs(ods):
    jobs=Counter()
    for f in receipts(ods,"business-licences",r':where "localarea=\\"([^"\\]+)\\""'):
        latest={}
        for r in json.loads(f.read_text()):
            if r["folderyear"]=="25":
                k=r["licencenumber"]
                if k not in latest or r["licencerevisionnumber"]>latest[k]["licencerevisionnumber"]:
                    latest[k]=r
        for r in latest.values():
            p=r["geo_point_2d"]
            if r["status"]=="Issued" and p and (r["numberofemployees"] or 0)>0:
                jobs[p["lon"],p["lat"]]+=r["numberofemployees"]
    return jobs


def overture_venues(raw):
    seen = set()
    for receipt in sorted((raw / "overture-places").glob("*.receipt.edn")):
        if not re.search(r':local-area "(?!DA )[^"]+"', receipt.read_text()):
            continue
        with Path(str(receipt).removesuffix(".receipt.edn")).open() as stream:
            for line in stream:
                record = json.loads(line)
                if record["id"] in seen:
                    continue
                seen.add(record["id"])
                category = record["category"] or ""
                kind = next((key for key, pattern in VENUE_TYPES.items() if re.search(pattern, category)),
                            "business")
                yield record["lon"], record["lat"], kind, record["name"]


def catalogue(raw, da_ids, da_shapes, extra_places=(), regional_ids=()):
    points=[]; labels=[]; kinds=defaultdict(list); weights=[]
    def add(lon,lat,kind,label="",weight=1):
        kinds[kind].append(len(points));points.append((lon,lat));labels.append(label or "");weights.append(weight)
    seen=set()
    ods=raw/"vancouver-ods"
    for f in receipts(ods,"property-addresses",r':where "geo_local_area=\\"([^"\\]+)\\""'):
        for feat in json.loads(f.read_text())["features"]:
            pt=tuple(feat["geometry"]["coordinates"][:2])
            if pt not in seen:
                seen.add(pt);add(*pt,"home")
    jobs=licensed_jobs(ods)
    for pt,n in sorted(jobs.items()):add(*pt,"job","Workplace",n)
    for lon, lat, kind, label in overture_venues(raw):
        add(lon, lat, kind, label)
    with (raw/"probes/anchors_bc_k12_schools.csv").open(encoding="utf-8-sig") as stream:
        for school in csv.DictReader(stream):
            level=school["SCHOOL_EDUCATION_LEVEL"]
            if (school["PHYSICAL_ADDRESS_CITY"].upper() not in ({"VANCOUVER","NORTH VANCOUVER","WEST VANCOUVER"} if regional_ids else {"VANCOUVER"}) or not school["LATITUDE"]
                    or not school["LONGITUDE"] or school["FACILITY_TYPE"]=="Continuing Education School"):
                continue
            for name in ("Elementary","Secondary"):
                if name in level:
                    add(float(school["LONGITUDE"]),float(school["LATITUDE"]),name.lower(),school["SCHOOL_NAME"])
    extra_start=len(points)
    for lon,lat,kind,label,weight in extra_places:
        add(lon,lat,kind,label,weight)
    lonlat=np.array(points); da_index=np.full(len(points),-1,dtype=int)
    with duckdb.connect() as db:
        db.execute("LOAD spatial")
        db.register("boundaries",pd.DataFrame({"d":range(len(da_ids)),"g":[json.dumps(g) for g in da_shapes]}))
        db.register("pts",pd.DataFrame({"i":range(len(points)),"x":lonlat[:,0],"y":lonlat[:,1]}))
        db.execute("create temp table polys as select d,st_geomfromgeojson(g) as poly from boundaries")
        matches=db.execute("""select i,min(d) from (select i,st_point(x,y) as p from pts) q
                              join polys on st_covers(poly,p) group by i""").fetchnumpy()
        da_index[matches["i"]]=matches["min(d)"]
        fallback=db.execute("select st_x(st_pointonsurface(poly)),st_y(st_pointonsurface(poly)) from polys order by d").fetchall()
    if regional_ids:
        extra=da_index[extra_start:]
        extra[~np.isin(extra,[i for i,d in enumerate(da_ids) if d in regional_ids])]=-1
    homes=defaultdict(list)
    for i in kinds["home"]:
        if da_index[i]>=0:homes[da_index[i]].append(i)
    proxy_das=set()
    for i in kinds.get("home-proxy",[]):
        d=da_index[i]
        if d>=0 and (not homes[d] or d in proxy_das):
            homes[d].append(i);kinds["home"].append(i);proxy_das.add(d)
    fallback_das=[]
    for d,pt in enumerate(fallback):
        if not homes[d]:
            homes[d].append(len(points));add(*pt,"home","Census area anchor")
            fallback_das.append(d)
    da_index=np.concatenate([da_index,np.array(fallback_das,dtype=int)])
    coords=np.rint((np.array(points)-ORIGIN)*SCALE).astype(int)
    kinds.pop("home-proxy",None)
    pools={k:np.array([i for i in ids if da_index[i]>=0],dtype=int) for k,ids in kinds.items()}
    if any(len(pools.get(k,[]))==0 for k in ["home","job","elementary","secondary",*VENUE_TYPES]):
        raise ValueError("Missing a required place class")
    if regional_ids:
        # Retain only destinations available to this regional model in the browser catalogue.
        used=np.unique(np.concatenate(list(pools.values())))
        remap=np.full(len(coords),-1,dtype=int);remap[used]=np.arange(len(used))
        homes={d:remap[v] for d,v in homes.items()}
        pools={k:remap[v] for k,v in pools.items()}
        coords=coords[used];da_index=da_index[used];weights=np.asarray(weights)[used]
        labels=[labels[i] for i in used]
    trees={k:cKDTree(coords[v]) for k,v in pools.items()}
    return coords,labels,da_index,homes,pools,trees,np.array(weights),fallback_das,sorted(proxy_das)


def compile_day(episodes):
    """A location slot for each stationary stop and two surrounding slots per bounded travel bout."""
    slots=[]; parts=[]; i=0
    while i<len(episodes):
        start,dur,act,loc=episodes[i]
        if loc in MOBILE:
            j=i+1
            while j<len(episodes) and episodes[j][3] in MOBILE:j+=1
            modes=Counter()
            for _,length,_,mode in episodes[i:j]:modes[mode]+=length
            mode=modes.most_common(1)[0][0]
            parts.append([start,sum(modes.values()),mode,-1,-1])
            i=j
        else:
            j=i+1
            while j<len(episodes) and episodes[j][3]==loc:j+=1
            activities=[e[2] for e in episodes[i:j]]
            kind="school" if loc=="work-or-school" and "study" in activities else "job" if loc=="work-or-school" else loc
            slot=len(slots);slots.append(kind)
            parts.append([start,sum(e[1] for e in episodes[i:j]),"stop",slot,slot]);i=j
    for k,part in enumerate(parts):
        if part[2]!="stop":
            part[3]=parts[k-1][4] if k and parts[k-1][2]=="stop" else -1
            part[4]=parts[k+1][3] if k+1<len(parts) and parts[k+1][2]=="stop" else -1
    return {"slots":slots,"parts":parts}


def assign_plans(tpl,home,ages,coords,pools,trees,weights,rng):
    n=len(home);slots=tpl["slots"];plans=np.full((n,len(slots)),-1,dtype=int);last=home
    fixed={}
    for k,part in enumerate(tpl["parts"]):
        _,_,mode,i,_=part
        if mode!="stop":continue
        kind=slots[i]
        if kind=="home":chosen=home
        elif kind in fixed:chosen=fixed[kind]
        elif kind in ("unknown","elsewhere"):continue
        elif kind=="school":
            # Age is released in five- or ten-year bands. Split the two bands
            # spanning school transitions with a uniform within-band age prior.
            u=rng.random(n)
            group=np.where((ages==1)|((ages==2)&(u<.6)),"elementary",
                           np.where((ages==2)|((ages==3)&(u<.6)),"secondary","college"))
            if tpl.get("childSchedule"):
                group=np.where(ages==88,"elementary",group)
            chosen=np.empty(n,dtype=int)
            for school in np.unique(group):
                mask=group==school
                _,near=trees[school].query(coords[home[mask]],k=1)
                chosen[mask]=pools[school][near]
            fixed[kind]=chosen
        else:
            source=kind if kind in pools else "home" if kind in ("other-home","neighbourhood") else "business"
            prev=tpl["parts"][k-1] if k else None
            if prev and prev[2] in ("air","ferry"):
                continue
            travel=prev and prev[2]!="stop"
            distance=prev[1]*SPEED.get(prev[2],220)*.76 if travel else rng.uniform(400,4500,n)
            origin=coords[last] if travel else coords[home]
            angle=rng.uniform(0,math.tau,n)
            target=origin+np.column_stack((np.cos(angle)*distance,np.sin(angle)*distance))
            if kind=="job":
                _,near=trees[source].query(target,k=min(5,len(pools[source])))
                candidates=pools[source][np.asarray(near).reshape(n,-1)]
                w=weights[candidates];cum=np.cumsum(w,axis=1)
                ix=(cum<rng.random((n,1))*cum[:,-1:]).sum(axis=1)
                chosen=candidates[np.arange(n),ix];fixed[kind]=chosen
            else:
                _,near=trees[source].query(target)
                chosen=pools[source][near]
        plans[:,i]=chosen;last=chosen
    return plans


def build(archive,atlas_root,out,*,extra_shapes=None,extra_places=(),paired=None):
    manifest=json.loads((atlas_root/"atlas.json").read_text())
    ids=sorted(manifest["das"]); areas=sorted(manifest["areas"])
    region=np.zeros(len(ids),dtype=int)
    index={d:i for i,d in enumerate(ids)}
    for j,name in enumerate(areas):
        for da in manifest["areas"][name]["das"]:region[index[da]]=j
    # The release includes the polygon used to generate each roster. This also
    # covers municipal areas absent from the early spatial extraction.
    shapes=[json.loads((atlas_root/(d+".json")).read_bytes())["geometry"] for d in ids]
    coords,labels,da_index,homes,pools,trees,weights,fallback,proxies=catalogue(archive/"data/raw",ids,shapes,extra_places,extra_shapes or ())
    dest=np.where(da_index<0,-1,region[da_index])
    places=[[int(x),int(y),int(d),label] for (x,y),d,label in zip(coords,dest,labels)]
    write_json(out/"places.json",places)
    templates=[compile_day(t["episodes"]) for t in manifest["templates"]]
    for tpl,source in zip(templates,manifest["templates"]):
        tpl["childSchedule"]=source["source"].startswith("Illustrative school")
    if paired:
        prior_atlas, prior_day = paired
        baseline = json.loads((prior_day/"day.json").read_bytes())
        if (baseline["das"] != ids or baseline["areas"] != areas or baseline["templates"] != templates
                or json.loads((prior_day/"places.json").read_bytes()) != places):
            raise ValueError("The paired weekday needs the same census areas, templates and destination catalogue")
        by_da = defaultdict(list)
        for d,i,_,_,weight in baseline["sample"]:
            by_da[ids[d]].append((i,weight))
    # Accumulate interval changes then integrate once over the day. Each person
    # contributes to exactly one stationary-area, travelling or unresolved bucket.
    changes=np.zeros((1441,len(areas)+2),dtype=int)
    audit=MobilityAudit(manifest["templates"])
    sample=[]; population=0; moves=0
    for da in ids:
        d=index[da];r=json.loads((atlas_root/(da+".json")).read_text());ps=np.array([[p[0],p[7]] for p in r["people"]])
        if not len(ps):
            write_json(out/(da+".json"),{"home":[],"plans":[]});continue
        if not extra_shapes or da not in extra_shapes:
            audit.add(r["people"],manifest["das"][da]["private"])
        rng=np.random.default_rng([2021,int(da),17])
        if paired:
            before = json.loads((prior_atlas/(da+".json")).read_bytes())
            day_before = json.loads((prior_day/(da+".json")).read_bytes())
            home = np.asarray(day_before["home"], dtype=int)
            unchanged = np.empty(len(ps), dtype=bool)
            if before["homes"] != r["homes"] or len(home) != len(ps):
                raise ValueError(f"Households and homes differ in {da}")
            for i,(a,b) in enumerate(zip(before["people"],r["people"],strict=True)):
                if a[:7] != b[:7]:
                    raise ValueError(f"The paired weekday changed a resident in {da}")
                unchanged[i] = a[7] == b[7]
        else:
            home=rng.choice(homes[d],len(ps))
            for start,size,_ in r["homes"]:home[start:start+size]=home[start]
        plans=[None]*len(ps)
        for t in np.unique(ps[:,1]):
            ix=np.flatnonzero(ps[:,1]==t);tpl=templates[t]
            if paired:
                changed = ~unchanged[ix]
                assigned = np.empty((len(ix),len(tpl["slots"])), dtype=int)
                if changed.any():
                    use = ix[changed]
                    assigned[changed] = assign_plans(tpl,home[use],ps[use,0],coords,pools,trees,weights,rng)
                if not changed.all():
                    assigned[~changed] = [day_before["plans"][i] for i in ix[~changed]]
            else:
                assigned=assign_plans(tpl,home[ix],ps[ix,0],coords,pools,trees,weights,rng)
            for pos,row in zip(ix,assigned.tolist()):plans[pos]=row
            for start,dur,mode,i,j in tpl["parts"]:
                if mode=="stop":
                    loc=assigned[:,i];buckets=np.where(loc>=0,dest[loc],len(areas)+1)
                    counts=np.bincount(buckets,minlength=len(areas)+2)
                else:
                    counts=np.zeros(len(areas)+2,dtype=int);counts[len(areas)]=len(ix)
                    moves+=len(ix)
                changes[start-240]+=counts;changes[start+dur-240]-=counts
        if paired:
            sample.extend([d,i,int(ps[i,1]),plans[i],weight] for i,weight in by_da[da])
        else:
            for i in rng.choice(len(ps),max(1,round(len(ps)/100)),replace=False):
                sample.append([d,int(i),int(ps[i,1]),plans[i],len(ps)/max(1,round(len(ps)/100))])
        population+=len(ps)
        write_json(out/(da+".json"),{"home":home.tolist(),"plans":plans})
    occupancy=changes.cumsum(axis=0)[:-1]
    if (occupancy<0).any() or not (occupancy.sum(axis=1)==population).all():
        raise ValueError("City occupancy is not conserved")
    result=dict(areas=areas,das=ids,templates=templates,sample=sample,
        occupancy=occupancy.tolist(),population=population,travelBouts=moves,fallbackAreas=[ids[d] for d in fallback])
    if extra_shapes:result["buildingProxyAreas"]=[ids[d] for d in proxies]
    write_json(out/"day.json",result)
    write_json(out/"mobility.json",audit.report())
    return population,len(sample),moves


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path)
    parser.add_argument("--atlas",type=Path,default=Path("public/data/vancouver/atlas"))
    parser.add_argument("--output",type=Path,default=Path("public/data/vancouver/cityday"))
    args=parser.parse_args()
    version=json.loads((args.atlas/"current.json").read_text())["version"]
    args.output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output) as temp:
        folder=Path(temp)/"payload";folder.mkdir()
        totals=build(args.archive,args.atlas/version,folder)
        h=hashlib.sha256(version.encode())
        for f in sorted(folder.iterdir()):h.update(f.name.encode());h.update(f.read_bytes())
        key=h.hexdigest()[:20];dest=args.output/key
        if not dest.exists():folder.rename(dest)
        from scripts.vancouver_raster import publish as publish_raster
        publish_raster(args.output.parent,version,key,atlas_root=args.atlas,day_root=args.output)
        from scripts.vancouver_street_walks import publish as publish_walks
        publish_walks(args.output.parent,dict(atlas=version,day=key),census=True,atlas_root=args.atlas,day_root=args.output)
        pointer=Path(temp)/"pointer";write_json(pointer,dict(atlas=version,version=key));pointer.replace(args.output/"current.json")
        print("Residents, animation sample, travel bouts:",totals,flush=True)

if __name__=="__main__":main()
