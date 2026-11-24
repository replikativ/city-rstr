"""Run paired weekday policies through city-rstr's Raster engine at resident and area-itinerary fidelity."""
import argparse
import collections
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from scripts.artifacts import read, write_json


def work_tours(tpl, diary):
    parts,slots=tpl["parts"],tpl["slots"]
    tours=[]
    for k in range(2,len(parts)-2):
        prev,depart,work,back,home=parts[k-2:k+3]
        if work[2]!="stop" or slots[work[3]]!="job" or depart[2]=="stop" or back[2]=="stop":
            continue
        if prev[2]!="stop" or home[2]!="stop" or slots[prev[3]]!="home" or slots[home[3]]!="home":
            continue
        if any(start>=work[0] and start<work[0]+work[1] and act=="paid-work" for start,_,act,_ in diary["episodes"]):
            tours.append(k)
    return tours


def half_ranks(da, indices):
    # Stable across study extents, independent of release ordering and parallel dispatch.
    x=np.asarray(indices,dtype=np.uint32)^np.uint32(int(da))
    x=(x^(x>>16))*np.uint32(0x85ebca6b)
    x=(x^(x>>13))*np.uint32(0xc2b2ae35)
    return np.where(((x^(x>>16)) & 1)==0,50,100)


def prepare(root,atlas_version,day_version,folder,*,atlas_root=None,day_root=None):
    ad=(atlas_root or root/"atlas")/atlas_version; dd=(day_root or root/"cityday")/day_version
    atlas=read(ad/"atlas.json"); day=read(dd/"day.json")
    areas=day["areas"]; cols=len(areas)+2
    places=np.asarray([p[2] for p in read(dd/"places.json")]+[cols-1])
    candidates=[work_tours(t,d) for t,d in zip(day["templates"],atlas["templates"],strict=True)]
    group_index={};offsets=[0];starts=[];ends=[];shifts=[];ranks=[];weights=[];micro=[]
    changes=np.zeros((2,1441,cols),dtype=np.int64);effects=np.zeros((2,3),dtype=np.int64)
    examples=[{} for _ in range(2)]
    for da in day["das"]:
        people=read(ad/(da+".json"))["people"]
        if not people:continue
        locs=read(dd/(da+".json")); group_by=collections.defaultdict(list)
        for i,p in enumerate(people): group_by[p[7]].append(i)
        home_index=np.asarray(locs["home"])
        by_resident=np.empty(len(people),dtype=np.int32)
        for t,ix in group_by.items():
            parts=day["templates"][t]["parts"]; n=len(ix)
            anchors=np.asarray([locs["plans"][i] for i in ix],dtype=np.int32)
            base=np.full((n,len(parts)),cols-2,dtype=np.int32)
            bounds=np.array([[s-240,s-240+duration] for s,duration,*_ in parts])
            for k,(_,_,mode,slot,_) in enumerate(parts):
                if mode=="stop":base[:,k]=places[anchors[:,slot]]
            if (base<0).any():raise ValueError("Unassigned place region")
            delta=np.zeros_like(base)
            rank=np.full(n,101,dtype=np.int32)
            if candidates[t]:
                home=home_index[ix]; hz=places[home]
                office=np.array([people[i][2]==1 and people[i][5]==2 for i in ix])
                draw=half_ranks(da,ix)
                for k in candidates[t]:
                    job=anchors[:,parts[k][3]]
                    eligible=office & (job>=0) & (job!=home) & (anchors[:,parts[k-2][3]]==home) & (anchors[:,parts[k+2][3]]==home)
                    if not eligible.any():continue
                    delta[eligible,k-1:k+2]=hz[eligible,None]-base[eligible,k-1:k+2]
                    rank[eligible]=draw[eligible]
                    # Independent direct changes to the microscopic reference count.
                    for case,level in enumerate((50,100)):
                        take=eligible & (draw<=level);num=int(take.sum())
                        if not num:continue
                        effects[case,1:]+=[2*num,num*(parts[k-1][1]+parts[k+1][1])]
                        for j in (k-1,k,k+1):
                            diff=np.bincount(hz[take],minlength=cols)-np.bincount(base[take,j],minlength=cols)
                            a,b=bounds[j];changes[case,a]+=diff;changes[case,b]-=diff
                        for h in np.unique(hz[take]):
                            if str(h) in examples[case]:continue
                            p=np.flatnonzero(take & (hz==h))[0]
                            examples[case][str(h)]=dict(da=da,person=ix[p],start=parts[k-1][0],end=parts[k+1][0]+parts[k+1][1],
                                                        workStart=parts[k][0],workEnd=parts[k][0]+parts[k][1],
                                                        job=int(job[p]),home=int(home[p]))
            for case,level in enumerate((50,100)):
                effects[case,0]+=np.count_nonzero(rank<=level)
            # Within a template, identical base zones, intervention shifts and offer rank commute with aggregation.
            records=np.column_stack((base,delta,rank)).astype(np.int16)
            order={}
            for pos,row in enumerate(records):
                packed=row.tobytes()
                g=order.get(packed)
                if g is None:
                    key=(t,packed);g=group_index.get(key)
                    if g is None:
                        g=len(weights);group_index[key]=g;weights.append(0);ranks.append(int(rank[pos]))
                        starts.extend((bounds[:,0]*cols+base[pos]).tolist())
                        ends.extend((bounds[:,1]*cols+base[pos]).tolist())
                        shifts.extend(delta[pos].tolist());offsets.append(len(starts))
                    order[packed]=g
                weights[g]+=1;by_resident[ix[pos]]=g
        micro.append(by_resident)
    tables={"starts":starts,"ends":ends,"offsets":offsets,"shifts":shifts,"ranks":ranks,
            "group-sizes":weights,"population":np.concatenate(micro)}
    for name,table in tables.items():np.asarray(table,dtype="<i4").tofile(folder/(name+".i32"))
    shape=dict(zones=cols,steps=max(map(len,(t["parts"] for t in day["templates"]))))
    write_json(folder/"shape.json",shape)
    base=np.asarray(day["occupancy"],dtype=np.int32)
    refs=np.concatenate([base[None],base[None]+changes.cumsum(axis=1)[:,:1440]],axis=0)
    np.save(folder/"expected.npy",refs)
    info=dict(day=day_version,atlas=atlas_version,areas=areas,population=day["population"],groups=len(weights),
              effects=effects.tolist(),examples=examples)
    write_json(folder/"policy.json",info)
    return info


def collect(root,work,backend,verify):
    result=read(work/"policy.json");cols=len(result["areas"])+2
    reference=np.load(work/"expected.npy")
    output=[]
    for case,level in enumerate((0,50,100)):
        for fidelity in (["groups","agents"] if verify else ["groups"]):
            path=work/(fidelity+"-"+str(level)+".i32")
            changes=np.fromfile(path,dtype="<i4").reshape(1441,cols)
            counts=changes.cumsum(axis=0)
            if counts[-1].any() or (counts<0).any() or not np.all(counts[:-1].sum(axis=1)==result["population"]):
                raise ValueError(f"Invalid population accounting for {fidelity} at {level}%")
            if not np.array_equal(counts[:-1],reference[case]):
                raise ValueError(f"Raster disagrees with individual plans at {level}% on {fidelity}")
        if level:output.append((counts[:-1]-reference[0]).tolist())
    result.update(delta=output,backend=backend,verifiedAgents=verify)
    dest=root/"raster";dest.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest) as tmp:
        f=Path(tmp)/"case.json";write_json(f,result);f.replace(dest/(result["atlas"]+"_"+result["day"]+".json"))
    return result


def publish(root,atlas,day,backend="jvm",verify=False,*,atlas_root=None,day_root=None):
    with tempfile.TemporaryDirectory() as tmp:
        work=Path(tmp);prepare(root,atlas,day,work,atlas_root=atlas_root,day_root=day_root)
        subprocess.run(["clojure","-J--add-modules=jdk.incubator.vector","-J--enable-native-access=ALL-UNNAMED",
                        "-M","-m","city.vancouver.occupancy-run",str(work),backend,"groups"]+(["agents"] if verify else []),check=True)
        return collect(root,work,backend,verify)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data",type=Path,default=Path("public/data/vancouver"));p.add_argument("--region",action="store_true")
    p.add_argument("--day",help="Use a published weekday under the current atlas")
    p.add_argument("--backend",default="jvm");p.add_argument("--verify-agents",action="store_true")
    args=p.parse_args();root=args.data
    if args.region:
        root=root/"region";ptr=read(root/"current.json");day=ptr["day"]
    else:
        ptr=read(root/"cityday/current.json");day=ptr["version"]
    r=publish(root,ptr["atlas"],args.day or day,args.backend,args.verify_agents)
    print(r["population"],"residents,",r["groups"],"area itineraries,",r["effects"])
