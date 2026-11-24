"""Measure how many of the existing mapped walks have endpoints within reach of each count."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from scipy.sparse import bmat, csr_matrix
from scipy.sparse.csgraph import dijkstra

from scripts.vancouver_atlas import write_json
from scripts.vancouver_region import package, read
from scripts.vancouver_streets import walk_graph
from scripts.vancouver_transit_commutes import pointer


def along_segment(origin, destination, centre, radius):
    """Distance from the origin to the first entry into a disk along a straight segment."""
    relative, segment = origin-centre, destination-origin
    squares = np.sum(segment*segment, axis=1)
    inner = np.sum(relative*segment, axis=1)
    offsets = np.sum(relative*relative, axis=1) - radius*radius
    discriminant = inner*inner - squares*offsets
    entry = np.full(len(origin), np.inf)
    start_inside = offsets <= 0
    entry[start_inside] = 0
    hits = ~start_inside & (squares > 0) & (discriminant >= 0)
    first = np.full(len(origin), np.inf)
    first[hits] = (-inner[hits] - np.sqrt(discriminant[hits])) / squares[hits]
    crossing = hits & (first >= 0) & (first <= 1)
    entry[crossing] = first[crossing] * np.sqrt(squares[crossing])
    return entry


def disk_distances(graph, nodes, places, snapped, offsets, endpoints, centre, radius):
    """Shortest distance from each address to any point in the count circle."""
    a,b = endpoints
    approach = along_segment(nodes[a],nodes[b],centre,radius)
    edges = np.full(len(nodes),np.inf)
    np.minimum.at(edges,a,approach)
    connected = np.flatnonzero(np.isfinite(edges))
    virtual = csr_matrix((edges[connected],(connected,np.zeros(len(connected),dtype=int))),shape=(len(nodes),1))
    streets = bmat([[graph,virtual],[virtual.T,csr_matrix((1,1))]],format="csr")
    to_circle = dijkstra(streets,indices=len(nodes))[:-1]
    connector_entry = along_segment(places,nodes[snapped],centre,radius)
    return np.minimum(offsets+to_circle[snapped],connector_entry)


def network_bounds(network, places, sites, legs, radius):
    graph, snap = walk_graph(network)
    coords, nodes = np.asarray([p[:2] for p in places]), np.asarray(network["nodes"])
    snapped, offsets = snap(coords,lowest_id_on_ties=True)
    endpoints = graph.nonzero()
    keys = [row[0] for row in legs]
    a,b,start,duration,limit,speed,direct = np.asarray([row[1:] for row in legs],dtype=float).reshape(-1,7).T
    a,b = a.astype(int),b.astype(int)
    output = []
    for site in sites:
        centre = np.asarray(site["point"])
        distance = disk_distances(graph,nodes,coords,snapped,offsets,endpoints,centre,radius)
        enters, leaves = distance[a], distance[b]
        dist = enters+leaves
        legal_endpoints = ((coords[a]-centre)**2).sum(axis=1)>radius*radius
        legal_endpoints &= ((coords[b]-centre)**2).sum(axis=1)>radius*radius
        earliest, latest = start+enters/speed, start+duration-leaves/speed
        fixed = list(map(sum,zip(*(site[k] for k in ("access","egress","transfer") if k in site),strict=True)))
        limits = []
        for percent in (10,25):
            possible = legal_endpoints & (dist <= np.minimum(limit,direct*(1+percent/100)) + 1e-7) & (earliest <= latest+1e-7)
            hourly = [possible & (earliest < hour+60+1e-7) & (hour <= latest+1e-7) for hour in site["hours"]]
            unique = np.logical_or.reduce(hourly)
            by_kind = {}
            for kind in sorted(set(keys)):
                belongs = np.fromiter((key==kind for key in keys),dtype=bool,count=len(keys))
                by_kind[kind] = int(np.count_nonzero(unique & belongs))
            limits.append(dict(detourPercent=percent,unique=int(unique.sum())+sum(fixed), fixed=sum(fixed),
                               hourly=[int(mask.sum())+pins for mask,pins in zip(hourly,fixed,strict=True)],
                               byPurpose=by_kind))
        output.append(limits)
    return output


def publish(root, joint_id, network=False):
    folder = root/"joint-weekday"/joint_id
    joint = read(folder/"report.json")
    actual = read(folder/"pedestrians.json")
    works = joint["workplaces"]
    inputs = dict(joint["versions"], outbound=works["outbound"], worksites=works["worksites"],
                  tracts=works["tract-workplaces"], riders=joint["riders"], transit=joint["transit"],
                  outings=joint["outings"], short=str(folder/"short-walks.json"))
    request = dict(joint=inputs, radius=actual["radius"], sites=actual["sites"], boundsOnly=True)
    with tempfile.TemporaryDirectory() as temp:
        spool = Path(temp)/"walks.json"
        command = ["node", "scripts/vancouver_pedestrians.mjs", root]
        if network:
            command.append(spool)
        result = subprocess.run(command,input=json.dumps(request),text=True,stdout=subprocess.PIPE,check=True)
        walks = read(spool) if network else None
    evidence = json.loads(result.stdout)
    if (any(evidence[k] != v for k,v in joint["versions"].items()) or evidence["tracts"] != works["tract-workplaces"]
            or evidence["riders"] != joint["riders"] or evidence["residents"] != joint["people"]):
        raise ValueError("The walking reach and sidewalk counts use different weekdays")
    limits = None
    if walks is not None:
        streets = read(root/"streets"/evidence["streets"]/"network.json")
        places = read(root/"cityday"/evidence["day"]/"places.json")+walks["stations"]
        print(f"Checking near-shortest street paths for {len(walks['legs']):,} walk candidates",flush=True)
        limits = network_bounds(streets,places,actual["sites"],walks["legs"],evidence["radius"])
    for i,(site, lower) in enumerate(zip(evidence["sites"], actual["sites"], strict=True)):
        if site["name"] != lower["name"] or site["hours"] != lower["hours"]:
            raise ValueError("The two pedestrian comparisons use different locations or hours")
        legs = site["walkReach"]
        ceiling = list(map(sum, zip(*(entry["hourly"] for entry in legs.values()), strict=True)))
        unique = sum(entry["legs"] for entry in legs.values())
        if any(cap < modeled for cap,modeled in zip(ceiling,lower["joint"],strict=True)) or unique < sum(lower["joint"]):
            raise ValueError("A walking reach ceiling fell below the number of routed passings")
        site.update(ceiling=ceiling, unique=unique, modeled=lower["joint"], observed=lower["observed"], source=lower["source"])
        if limits is not None:
            site["networkBounds"] = limits[i]
            if any(row["unique"] < sum(lower["joint"]) or any(a < b for a,b in zip(row["hourly"],lower["joint"],strict=True))
                   for row in limits[i]):
                raise ValueError("The network ceiling fell below a routed passing")
    evidence["joint"] = joint_id
    family = "walk-reach"
    version = package(root,family,lambda out:write_json(out/"report.json",evidence))
    pointer(root/family/(joint_id+".json"),{"version":version})
    print(version,[(s["name"],s["unique"],sum(s["modeled"]),sum(s["observed"])) for s in evidence["sites"]],flush=True)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("joint")
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--network", action="store_true", help="also check near-shortest routes on the pedestrian graph")
    args = parser.parse_args()
    publish(args.root,args.joint,args.network)
