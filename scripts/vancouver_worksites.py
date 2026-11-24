"""Route municipal walking commuters to existing job addresses and publish matched workplaces."""
import argparse
from collections import defaultdict
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.sparse import bmat, csr_matrix
from scipy.sparse.csgraph import dijkstra

from scripts.vancouver_atlas import write_json
from scripts.vancouver_inbound import read
from scripts.vancouver_region import package
from scripts.vancouver_streets import walk_graph


def nearest_sites(graph, nodes, offsets, sites, homes):
    """Shortest walk to any site, including both address connectors and co-location."""
    seeds = {}
    for site in sites:
        node = nodes[site]
        seeds[node] = min(offsets[site], seeds.get(node, np.inf))
    n = graph.shape[0]
    costs = csr_matrix((list(seeds.values()), ([0]*len(seeds),list(seeds))), shape=(1,n))
    augmented = bmat([[graph, csr_matrix((n,1))],[costs,csr_matrix((1,1))]], format="csr")
    distance = dijkstra(augmented, indices=n)
    return np.where(np.isin(homes,sites), 0, offsets[homes]+distance[nodes[homes]])


def route_options(roster, places, network):
    graph, snap = walk_graph(network)
    nodes, offsets = snap([p[:2] for p in places])
    sites = dict(roster["workplaces"])
    groups, by_area = defaultdict(set), defaultdict(list)
    for j,a in sites.items():
        by_area[a].append(j)
    for w in roster["workers"]:
        if w["eligible"]:
            job = w["legs"][0][1]
            groups[sites[job],w["occupation"]].add(job)
    requests, budgets = defaultdict(dict), defaultdict(set)
    for w in roster["workers"]:
        for h,j,minutes,_ in w["legs"]:
            area = sites[j]
            budgets[area].add(h)
            options = groups[area,w["occupation"]] if w["eligible"] else (j,)
            metres = minutes*roster["speed"]
            for dest in options:
                requests[dest][h] = max(requests[dest].get(h,0),metres)
    # The cutoff includes the longest requested walk. Missing pairs cannot fit any requested window.
    distances = []
    coords = np.array([p[:2] for p in places])
    for dest, req in sorted(requests.items()):
        homes = np.array(list(req))
        limits = np.array(list(req.values()))
        possible = np.linalg.norm(coords[homes]-coords[dest],axis=1) <= limits
        homes, limits = homes[possible], limits[possible]
        if not len(homes):
            continue
        dist = dijkstra(graph,indices=nodes[dest],limit=limits.max())
        metres = np.where(homes==dest,0,offsets[homes]+dist[nodes[homes]]+offsets[dest])
        distances.extend([int(h),dest,float(m)] for h,m in zip(homes[metres<=limits],metres[metres<=limits]))
    nearest = []
    for area, origin_ids in sorted(budgets.items()):
        homes = np.array(sorted(origin_ids))
        values = nearest_sites(graph,nodes,offsets,by_area[area],homes)
        nearest.extend([int(h),area,float(m)] for h,m in zip(homes,values) if np.isfinite(m))
    origins = np.array(sorted(set().union(*budgets.values())),dtype=int)
    values = nearest_sites(graph,nodes,offsets,list(sites),origins)
    city = [[int(h),float(m)] for h,m in zip(origins,values) if np.isfinite(m)]
    return dict(distances=distances, nearest=nearest, city=city)


def solve(groups):
    """Minimize the supplied costs using each column slot exactly once."""
    solutions = []
    for group in groups:
        costs = np.array(group["costs"],dtype=float)[:,group["siteSlots"]]
        costs[np.isnan(costs)] = np.inf
        _, columns = linear_sum_assignment(costs)
        solutions.append(columns.tolist())
    return solutions


def publish(root, day=None):
    day = day or read(root/"cityday/current.json")
    release = read(root/"outbound"/(day["atlas"]+"_"+day["version"]+".json"))["version"]
    atlas_dir = root/"atlas"/day["atlas"]
    day_dir = root/"cityday"/day["version"]
    cmd = ["clojure","-J-Xmx2g","-M","-m","city.vancouver.worksites"]
    with tempfile.TemporaryDirectory() as tmp:
        roster, routes = [Path(tmp)/name for name in ("workers.json","routes.json")]
        subprocess.run([*cmd,"extract",atlas_dir,day_dir,root/"outbound"/release,roster],check=True)
        workers = read(roster)
        network = read(root/"streets"/workers["streets"]/"network.json")
        write_json(routes,route_options(workers,read(day_dir/"places.json"),network))
        costs, solution = Path(tmp)/"costs.json", Path(tmp)/"solution.json"
        subprocess.run([*cmd,"costs",roster,routes,costs],check=True)
        write_json(solution,solve(read(costs)))
        def build(folder):
            subprocess.run([*cmd,"match",roster,routes,solution,folder/"worksites.json"],check=True)
        version = package(root,"worksites",build)
    target = root/"worksites"/(release+".json")
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        pointer = Path(tmp)/"pointer"
        write_json(pointer,dict(version=version))
        pointer.replace(target)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data",type=Path,default=Path("public/data/vancouver"))
    print(publish(parser.parse_args().data))
