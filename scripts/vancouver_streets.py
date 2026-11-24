"""Build offline street topology and tiled building footprints for the Vancouver day explorer."""
import argparse
import hashlib
import json
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.spatial import cKDTree

from scripts.artifacts import write_json
from scripts.vancouver_cityday import xy
from scripts.vancouver_walks import WALKABLE

DRIVE = {"motorway","trunk","primary","secondary","tertiary","unclassified","residential",
         "living_street","service","motorway_link","trunk_link","primary_link","secondary_link","tertiary_link"}
TILE = 1000


def access_graph(net, forward, reverse, *, speeds=None, slowdowns=None):
    points = np.array(net["nodes"], dtype=float)
    edges = {}
    if speeds is not None and len(speeds) != len(net["ways"]):
        raise ValueError("The directed speeds and street graph have different coverage")
    for i, (bits, _, nodes) in enumerate(net["ways"]):
        outbound, inbound = speeds[i] if speeds is not None else (1, 1)
        if bits & forward and not outbound > 0 or bits & reverse and not inbound > 0:
            raise ValueError("An accessible edge has no speed")
        for a, b in zip(nodes, nodes[1:]):
            if a != b:
                if bits & forward:
                    edges[a, b] = max(edges.get((a, b), 0), outbound)
                if bits & reverse:
                    edges[b, a] = max(edges.get((b, a), 0), inbound)
    ids = sorted(edges)
    a, b = np.array(ids).T
    length = np.linalg.norm(points[a]-points[b], axis=1)
    keep = length > 0
    cost = length if speeds is None else length / (np.fromiter((edges[edge] for edge in ids), dtype=float) * 1000/60)
    if slowdowns:
        if not slowdowns.keys() <= edges.keys():
            raise ValueError("A measured corridor includes an inaccessible edge")
        cost *= np.fromiter((slowdowns.get(edge, 1) for edge in ids), dtype=float)
    graph = coo_matrix((cost[keep],(a[keep],b[keep])), shape=(len(points),len(points))).tocsr()
    active = np.union1d(a[keep], b[keep])
    tree = cKDTree(points[active])
    def snap(coords, *, lowest_id_on_ties=False):
        if not lowest_id_on_ties:
            off, index = tree.query(coords)
            return active[index], off
        # The replay resolves equally near walkable nodes by their network ID.
        # The historic release builders use the KD-tree's original tie order.
        coords = np.asarray(coords)
        batch = coords.reshape(-1, 2)
        distances, indices = tree.query(batch, k=2)
        ids = active[indices[:, 0]].copy()
        for i in np.flatnonzero(distances[:, 0] == distances[:, 1]):
            radius = np.nextafter(distances[i, 0], np.inf)
            near = active[tree.query_ball_point(batch[i], radius)]
            squared = np.sum((points[near] - batch[i])**2, axis=1)
            ids[i] = near[squared == squared.min()].min()
        if coords.shape == (2,):
            return ids[0], distances[0, 0]
        shape = coords.shape[:-1] if coords.ndim > 1 else (0,)
        return ids.reshape(shape), distances[:, 0].reshape(shape)
    return graph, snap


def walk_graph(net):
    return access_graph(net, 1, 1)


def permissions(tags):
    kind = tags.get("highway")
    restricted = {"private","no"}
    if tags.get("area") == "yes":
        return 0
    access = tags.get("access")
    foot = tags.get("foot", access) not in restricted and (kind in WALKABLE or tags.get("foot") in {"yes","designated"})
    car = kind in DRIVE and tags.get("motorcar",tags.get("motor_vehicle",tags.get("vehicle",access))) not in restricted
    implied = "yes" if kind == "motorway" or tags.get("junction") == "roundabout" else "no"
    oneway = tags.get("oneway", implied)
    return int(foot) | (2 if car and oneway != "-1" else 0) | (4 if car and oneway not in {"yes","true","1"} else 0)


def height(tags):
    for key, multiplier, basis in [("height",1,"height"),("building:levels",3,"levels")]:
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(m|ft)?", tags.get(key,"").strip())
        if m:
            value = float(m[1]) * (.3048 if m[2]=="ft" else multiplier)
            if 1 <= value <= 600:
                return round(value,1),basis
    return (6 if tags.get("building") in {"house","detached","residential","semidetached_house"} else 9),"assumed"


def archived_buildings(raw):
    for file in sorted((raw/"osm-buildings").glob("vancouver_*_*.json")):
        yield from json.loads(file.read_text())["elements"]

def encode_way(way, bits, nodes, ids, names):
    indices = []
    for ref, p in zip(way["nodes"], way["geometry"], strict=True):
        if ref not in ids:
            ids[ref] = len(nodes)
            nodes.append(xy(p["lon"], p["lat"]))
        indices.append(ids[ref])
    name = way["tags"].get("name", "")
    return [bits, names.setdefault(name, len(names)), indices]


def build(raw,out,*,roads=None,buildings=None):
    nodes=[]; ids={}; ways=[]; names={}; local=defaultdict(lambda:{"buildings":[],"roads":[]})
    if roads is None:roads=json.loads((raw/"osm-overpass/vancouver_highways.json").read_text())["elements"]
    for way in roads:
        tags=way.get("tags",{}); bits=permissions(tags)
        if not bits or len(way.get("nodes",[]))<2:
            continue
        encoded=encode_way(way,bits,nodes,ids,names)
        ways.append(encoded)
        points=[nodes[i] for i in encoded[2]]
        # Assign the entire line to every tile its bounding box touches.
        # The renderer deduplicates ways where neighbouring tiles meet.
        xs,ys=zip(*points)
        for x in range(min(xs)//TILE,max(xs)//TILE+1):
            for y in range(min(ys)//TILE,max(ys)//TILE+1):
                local[x,y]["roads"].append([way["id"],int(tags["highway"] in DRIVE),points])
    write_json(out/"network.json",dict(nodes=nodes,ways=ways,names=list(names)))
    seen=set();bases=Counter()
    for way in (archived_buildings(raw) if buildings is None else buildings):
        tags=way.get("tags",{});ref=way["id"]
        if way["type"]!="way" or ref in seen or not tags.get("building") or tags["building"]=="no":
            continue
        ring=[xy(p["lon"],p["lat"]) for p in way.get("geometry",[])]
        if len(ring)<4 or ring[0]!=ring[-1]:
            continue
        seen.add(ref); h,basis=height(tags);bases[basis]+=1
        record=[ref,h,basis,ring]
        if buildings is not None:
            detail={}
            if tags.get("name"):detail["name"]=tags["name"]
            if way.get("holes"):detail["holes"]=[[xy(*p[:2]) for p in hole] for hole in way["holes"]]
            if detail:record.append(detail)
        xs,ys=zip(*ring)
        for x in range(min(xs)//TILE,max(xs)//TILE+1):
            for y in range(min(ys)//TILE,max(ys)//TILE+1):
                local[x,y]["buildings"].append(record)
    for (x,y),tile in local.items():
        write_json(out/f"{x}_{y}.json",tile)
    vendor=Path(__file__).resolve().parents[1]/"node_modules/maplibre-gl"
    for source in ["dist/maplibre-gl.js","dist/maplibre-gl.css","LICENSE.txt"]:
        shutil.copyfile(vendor/source,out/Path(source).name)
    meta=dict(tileSize=TILE,tiles=sorted(f"{x}_{y}" for x,y in local),nodes=len(nodes),ways=len(ways),
              buildings=len(seen),heightSources=dict(bases))
    write_json(out/"streets.json",meta)
    return meta


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path)
    parser.add_argument("--output",type=Path,default=Path("public/data/vancouver/streets"))
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output) as tmp:
        root=Path(tmp);folder=root/"payload";folder.mkdir()
        meta=build(args.archive/"data/raw",folder)
        digest=hashlib.sha256()
        for file in sorted(folder.iterdir()):
            digest.update(file.name.encode());digest.update(file.read_bytes())
        version=digest.hexdigest()[:20];dest=args.output/version
        if not dest.exists():folder.rename(dest)
        from scripts.vancouver_cycling import publish as publish_cycling
        publish_cycling(args.archive,args.output.parent,streets=version)
        pointer=root/"current.json";write_json(pointer,{"version":version});pointer.replace(args.output/"current.json")
        print({k:v for k,v in meta.items() if k!="tiles"})

if __name__=="__main__":main()
