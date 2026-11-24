"""Assign complete road commutes to mapped external jobs in the resident's Census municipality."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import duckdb
import numpy as np
from scipy.sparse.csgraph import dijkstra

from scripts.vancouver_atlas import largest_remainder, write_json
from scripts.vancouver_census_geography import area_membership
from scripts.vancouver_cityday import xy
from scripts.vancouver_region import package, place_kinds, read
from scripts.vancouver_streets import access_graph
from scripts.vancouver_transit_commutes import pointer
from scripts.vancouver_workplace_tracts import census_counts


DESTINATIONS = {
    "5915015": "Richmond (CY), B.C.", "5915025": "Burnaby (CY), B.C.",
    "5915020": "Metro Vancouver A (RDA), B.C.", "5915004": "Surrey (CY), B.C.",
    "5915046": "North Vancouver (CY), B.C.", "5915011": "Delta (CY), B.C.",
    "5915051": "North Vancouver (DM), B.C.", "5915029": "New Westminster (CY), B.C.",
    "5915034": "Coquitlam (CY), B.C.", "5915055": "West Vancouver (DM), B.C.",
    "5915001": "Langley (DM), B.C.", "5915039": "Port Coquitlam (CY), B.C.",
    "5915043": "Port Moody (CY), B.C.", "5915002": "Langley (CY), B.C.",
}
SEED = 10354


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def osm_jobs(db, pbf, bounds):
    west, south, east, north = bounds
    relevant = " or ".join(f"tags['{k}'] is not null" for k in ("building", "shop", "office", "amenity", "aeroway"))
    db.execute("""create temp table osm_nodes as select id,lon,lat,tags from st_readosm(?)
                  where kind='node' and lon between ? and ? and lat between ? and ?""",
               [str(pbf), west, east, south, north])
    db.execute(f"create temp table jobs as select id,tags,refs from st_readosm(?) where kind='way' and ({relevant})", [str(pbf)])
    query = f"""select id, lon, lat, tags from osm_nodes where {relevant}
                union all
                select jobs.id, avg(n.lon), avg(n.lat), any_value(jobs.tags)
                from jobs cross join unnest(jobs.refs) p(ref) join osm_nodes n on n.id=p.ref
                group by jobs.id having count(*)=max(len(jobs.refs))
                order by 2,3,1"""
    cursor = db.execute(query)
    points = {}
    while records := cursor.fetchmany(4000):
        for _,lon,lat,tags in records:
            if "job" in place_kinds(tags) or tags.get("amenity")=="school" or tags.get("aeroway")=="terminal":
                pos = tuple(xy(lon, lat))
                label = tags.get("name", "")
                if pos not in points or label and not points[pos][2]:
                    points[pos] = lon, lat, label
    return list(points.values())


def inventory(archive, pbf, geography, bounds):
    import pandas as pd

    raw = archive/"data/raw/statcan"
    shape = raw/"lda_000b21a_e.shp"
    tracts = geography/"vancouver-tracts-2021.geojson"
    census = geography/"98100498-eng.zip"
    membership = area_membership(raw, set(DESTINATIONS))
    counts = census_counts(census)
    with duckdb.connect() as db:
        db.execute("load spatial")
        db.execute("set threads=3")
        points = osm_jobs(db, pbf, bounds)
        db.register("points",pd.DataFrame(points,columns=["lon","lat","label"]))
        db.register("members",pd.DataFrame(membership.items(),columns=["da","municipality"]))
        db.execute("""create temp table municipalities as select municipality,
            st_transform(st_union_agg(st_makevalid(s.geom)),'EPSG:3347','EPSG:4326',always_xy:=true) g
            from st_read(?) s join members m on s.DAUID=m.da group by municipality""", [str(shape)])
        located = db.execute("""select municipality,lon,lat,label,min(t.DGUID) as tract
            from points p join municipalities m on st_covers(m.g,st_point(lon,lat))
            join st_read(?) t on st_covers(st_makevalid(t.geom),st_point(lon,lat))
            group by all order by municipality,lon,lat,label""", [str(tracts)]).fetchall()
    jobs = defaultdict(list)
    for csd,lon,lat,label,tract in located:
        if counts.get(tract,0) not in (None,0):
            jobs[DESTINATIONS[csd]].append([*xy(lon,lat),label or "Mapped workplace",tract])
    sources = {path.name:digest(path) for path in (pbf,shape,tracts,census)}
    print("Mapped candidate jobs", {city:len(rows) for city,rows in jobs.items()}, flush=True)
    return jobs, counts, sources


def workers(root, joint_id, destinations):
    groups = defaultdict(list)
    coverage = defaultdict(Counter)
    with tempfile.TemporaryFile(mode="w+") as out:
        subprocess.run(["node","scripts/vancouver_outbound_road_legs.mjs",root,joint_id],stdout=out,check=True)
        out.seek(0)
        for line in out:
            da,person,city,slots,legs,absent = json.loads(line)
            c = coverage[city]
            c["attending"] += 1
            c["driverLegs"] += sum(leg[4] for leg in legs)
            if not any(leg[4] for leg in legs):
                continue
            c["workersWithDriving"] += 1
            if city not in destinations:
                c["outsideInventory"] += 1
            elif not all(leg[5] for leg in legs):
                c["unsupportedMode"] += 1
            elif absent or any(leg[2]<0 for leg in legs):
                c["missingTravelOrEndpoint"] += 1
            else:
                groups[city].append((da,person,slots,legs))
                c["checked"] += 1
    return groups, coverage


def route_times(graph, nodes, offsets, cond, options, workers):
    access = offsets / (cond["connectorKmh"] * 1000 / 60)
    reach = offsets <= cond["connectorMetres"]
    candidates = nodes[options]
    reverse = graph.T.tocsr()
    limits = {}
    for _,_,_,legs in workers:
        for _,duration,anchor,from_work,*_ in legs:
            if reach[anchor]:
                key = int(nodes[anchor]), from_work
                limits[key] = max(limits.get(key,0),duration-access[anchor])
    times = {}
    for (node,from_work),limit in sorted(limits.items()):
        cost = dijkstra(reverse if from_work else graph, indices=node, limit=limit)
        times[node,from_work] = cost[candidates] + access[options]
    missing = np.full(len(options),np.inf)

    def costs(legs):
        result = np.asarray([times.get((int(nodes[a]),direction),missing)+access[a] if reach[a] else missing
                             for _,_,a,direction,*_ in legs])
        result[:,~reach[options]] = np.inf
        return result

    return costs


def allocate(rows, options, tract_ids, employment, costs, rng):
    feasible = []
    for worker in rows:
        legs = worker[3]
        times = costs(legs)
        limits = np.asarray([leg[1] for leg in legs])[:,None]
        good = np.flatnonzero(np.all(times <= limits+1e-7,axis=0))
        if not len(good):
            continue
        # Prefer travel times close to the recorded windows within a tract.
        penalties = (limits-times[:,good]).mean(axis=0) + rng.gumbel(0,2,len(good))
        choices = {}
        for index in good[np.argsort(penalties,kind="stable")]:
            choices.setdefault(tract_ids[index],int(index))
        feasible.append((worker,choices,times[:,list(choices.values())].T.tolist()))
    tracts = sorted(employment)
    mass = np.asarray([employment[t] for t in tracts], dtype=float)
    target = dict(zip(tracts,map(int,largest_remainder(mass/mass.sum(),len(feasible))),strict=True))
    used = Counter()
    assignments = []
    for index in sorted(rng.permutation(len(feasible)),key=lambda i:len(feasible[i][1])):
        worker,choices,minutes = feasible[index]
        available = list(choices)
        weights = np.asarray([max(0,target[t]-used[t]) for t in available],dtype=float)
        if not weights.any():
            weights = np.asarray([employment[t] for t in available],dtype=float)
        selected = int(rng.choice(len(available),p=weights/weights.sum()))
        tract = available[selected]
        used[tract] += 1
        assignments.append((worker,int(options[choices[tract]]),minutes[selected]))
    return assignments, {t:[employment[t],target[t],used[t]] for t in tracts}


def publish(root, archive, pbf, geography, joint_id, fit_id):
    joint = read(root/"joint-weekday"/joint_id/"report.json")
    drive = read(root/"incoming-drives"/f"{fit_id}.json")
    if drive["joint"]!=joint_id or drive["basis"]!="free-flow":
        raise ValueError("The outbound workplaces require the combined weekday's metro road graph")
    road = root/"commuter-drive"/drive["network"]
    road_report = read(road/"report.json")
    if digest(pbf)!=road_report["sourceDigest"]:
        raise ValueError("The workplace and road extracts must use the same OpenStreetMap source")
    jobs, employment, sources = inventory(archive,pbf,geography,road_report["bounds"])
    groups, coverage = workers(root,joint_id,jobs)
    day_dir = root/"cityday"/joint["versions"]["day"]
    original = read(day_dir/"places.json")
    day = read(day_dir/"day.json")
    network, profile = (read(road/f"{file}.json") for file in ("network","profile"))
    graph, snap = access_graph(network,2,4,speeds=profile["kmh"])
    patches, places, tract_counts = defaultdict(list), [], {}
    initial = len(original)
    rng = np.random.default_rng(SEED)
    for city, entries in sorted(groups.items()):
        pool = jobs[city]
        coords = [p[:2] for p in original] + [p[:2] for p in pool]
        nodes, offsets = snap(coords,lowest_id_on_ties=True)
        options = np.arange(initial,len(coords))
        tracts = [p[3] for p in pool]
        costs = route_times(graph,nodes,offsets,profile,options,entries)
        assigned, tract_counts[city] = allocate(entries,options,tracts,{t:employment[t] for t in set(tracts)},costs,rng)
        del costs
        used = {}
        for (d,person,slots,legs),site,times in assigned:
            if site not in used:
                used[site] = len(places)
                x,y,label,tract = pool[site-initial]
                places.append([x,y,-1,label,city,tract])
            patched = [[*leg[:5],minute] for leg,minute in zip(legs,times,strict=True)]
            if any(leg[-1]>leg[1]+1e-7 for leg in patched):
                raise ValueError("An assigned address exceeds a diary window")
            patches[day["das"][d]].append([person,used[site],slots,patched])
            coverage[city]["locatedDriverLegs"] += sum(leg[4] for leg in legs)
        coverage[city]["locatedWorkers"] = len(assigned)
        coverage[city]["noFeasibleAddress"] = len(entries)-len(assigned)
        print(city,len(entries),len(assigned),coverage[city]["locatedDriverLegs"],flush=True)
    if not places:
        raise ValueError("No complete commutes fit any external workplace")
    summary = dict(joint=joint_id,versions=joint["versions"],workplaces=joint["workplaces"],network=drive["network"],
                   clock=drive["basis"],seed=SEED,basePlaces=initial,areas=sorted(patches),coverage=coverage,
                   censusTracts=tract_counts,sources=sources)

    def build(out):
        write_json(out/"places.json",places)
        write_json(out/"report.json",summary)
        for da, rows in patches.items():
            write_json(out/f"{da}.json",sorted(rows))

    version = package(root,"outbound-road-jobs",build)
    pointer(root/"outbound-road-jobs"/f"{joint_id}.json",dict(version=version))
    print(version, sum(c["locatedWorkers"] for c in coverage.values()),
          sum(c["locatedDriverLegs"] for c in coverage.values()), "of",sum(c["driverLegs"] for c in coverage.values()),flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path)
    parser.add_argument("joint")
    parser.add_argument("fit")
    parser.add_argument("--root",type=Path,default=Path("public/data/vancouver"))
    parser.add_argument("--pbf",type=Path,default=Path("data/region/vancouver.osm.pbf"))
    parser.add_argument("--geography",type=Path,default=Path("data/mobility"))
    args = parser.parse_args()
    publish(args.root,args.archive,args.pbf,args.geography,args.joint,args.fit)
