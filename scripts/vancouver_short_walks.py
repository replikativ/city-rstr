"""Resolve adjacent diary stops where a short network walk fits between assigned places."""
import argparse
import json
import math
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.sparse.csgraph import dijkstra

from scripts.vancouver_atlas import write_json
from scripts.vancouver_streets import walk_graph

SPEED = 80  # walking metres per minute, also used by the grocery experiment
MAX_MINUTES = 10
SAME_PLACE_METRES = 25


def read(path):
    return json.loads(path.read_text())


def gaps(template, diary):
    """Keep half of each bordering activity in reserve for its other boundary."""
    episodes=diary["episodes"]
    starts={start:i for i,(start,*_) in enumerate(episodes)}
    for left,right in zip(template["parts"],template["parts"][1:]):
        if left[2]!="stop" or right[2]!="stop":
            continue
        boundary=right[0]
        i=starts[boundary]
        before=(episodes[i-1][1]-1)//2
        after=(episodes[i][1]-1)//2
        yield (boundary,left[3],right[3],before,after)


def interval(boundary, before, after, metres):
    if not math.isfinite(metres):
        return None
    minutes=math.ceil(metres/SPEED)
    if minutes<1 or minutes>min(MAX_MINUTES,before+after):
        return None
    # Split the walk around the recorded change, subject to both dwell budgets.
    early=min(before,max(minutes-after,minutes//2))
    return boundary-early,minutes


def build(atlas_dir,day_dir,street_dir):
    atlas=read(atlas_dir/"atlas.json");day=read(day_dir/"day.json")
    places=read(day_dir/"places.json");coords=np.array([p[:2] for p in places])
    graph,snap=walk_graph(read(street_dir/"network.json"))
    nodes,offset=snap(coords)
    templates=[list(gaps(t,d)) for t,d in zip(day["templates"],atlas["templates"],strict=True)]
    stats=Counter();candidates=defaultdict(list)
    for d,da in enumerate(day["das"]):
        roster=read(atlas_dir/(da+".json"));location=read(day_dir/(da+".json"))
        private=atlas["das"][da]["private"]
        for p,(person,plan) in enumerate(zip(roster["people"],location["plans"],strict=True)):
            for boundary,i,j,before,after in templates[person[-1]]:
                a,b=plan[i],plan[j]
                if min(a,b)<0:
                    stats["unlocated"]+=1;continue
                dist=math.dist(coords[a],coords[b])
                if dist<=SAME_PLACE_METRES:
                    stats["colocated"]+=1;continue
                if dist>MAX_MINUTES*SPEED:
                    stats["tooFar"]+=1;continue
                if dist>min(MAX_MINUTES,before+after)*SPEED:
                    stats["shortDwell"]+=1;continue
                candidates[nodes[a]].append((d,p,boundary,i,j,before,after,a,b,person[0] if p<private else 0))
    changes=np.zeros((1441,len(day["areas"])+2),dtype=int)
    walks=[];adults=0.;age45=0;adult20=0
    for node,requests in candidates.items():
        distances=dijkstra(graph,indices=node,limit=MAX_MINUTES*SPEED)
        for d,p,boundary,i,j,before,after,a,b,age in requests:
            metres=offset[a]+distances[nodes[b]]+offset[b]
            when=interval(boundary,before,after,metres)
            if when is None:
                stats["networkOrTime"]+=1;continue
            start,n=when;end=start+n
            # Remove from the two original areas across the boundary and add to travel.
            for lo,hi,area in ((start,boundary,places[a][2]),(boundary,end,places[b][2])):
                changes[lo-240,area]-=1;changes[hi-240,area]+=1
            changes[start-240,-2]+=1;changes[end-240,-2]-=1
            walks.append([d,p,start,n,i,j])
            adults+=1 if 4<=age<=13 else .4 if age==3 else 0
            adult20+=int(4<=age<=13);age45+=int(age==9)
    stats["resolved"]=len(walks)
    delta=changes.cumsum(axis=0)[:-1]
    occupancy=np.asarray(day["occupancy"])+delta
    if (occupancy<0).any() or not np.all(occupancy.sum(axis=1)==day["population"]):
        raise ValueError("Short-walk intervals violate population conservation")
    return dict(day=day_dir.name,atlas=atlas_dir.name,streets=street_dir.name,minutes=MAX_MINUTES,
                speed=SPEED,colocated=SAME_PLACE_METRES,gaps=dict(stats),walks=sorted(walks),
                occupancyDelta=delta.tolist(),adultWalks=adults,age20Walks=adult20,age45Walks=age45)


def publish(root, atlas, day, street):
    result=build(root/"atlas"/atlas,root/"cityday"/day,root/"streets"/street)
    out=root/"short-walks";out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        file=Path(tmp)/"walks";write_json(file,result);file.replace(out/(day+"_"+street+".json"))
    print(result["gaps"],result["adultWalks"],flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data",type=Path,default=Path("public/data/vancouver"))
    parser.add_argument("--region",action="store_true",help="Use the wider Vancouver and North Shore geography")
    parser.add_argument("--day",help="Use a named weekday under the current atlas")
    args=parser.parse_args()
    root=args.data
    if args.region:
        root=root/"region"
        version=read(root/"current.json")
        publish(root,version["atlas"],args.day or version["day"],version["streets"])
    else:
        version=read(root/"cityday/current.json")
        publish(root,version["atlas"],args.day or version["version"],read(root/"streets/current.json")["version"])


if __name__=="__main__":
    main()
