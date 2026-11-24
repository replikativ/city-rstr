"""Paired walking grocery scenarios and independent movement checks for Mount Pleasant."""
import argparse
import json
import math
import random
import re
import subprocess
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from itertools import groupby
from pathlib import Path

import networkx as nx
from openpyxl import load_workbook
from scipy.spatial import cKDTree

from scripts import vancouver_walks as walks

YEAR = "2025"
CANDIDATES = [(37, "1731 Manitoba St"), (6070, "68 W Broadway")]
HOLDOUT = {"TMC_FraserSt&Broadway": "Fraser & Broadway",
           "TMC_PrinceEdward&EBroadway": "Prince Edward & Broadway"}
PROFILES = [
    dict(id="standard", name="Shortest feasible trip"),
    dict(id="jobs", name="Licensed workplace locations"),
    dict(id="appeal", name="New shop favoured by 3 min", advantage=3),
    dict(id="hours", name="New shop open 10–18", hours=[600, 1080]),
    dict(id="competition", name="Include other food retailers", broad=True),
]
SPEED = 80  # walking metres per minute
SHARE = 0.4  # assumed grocery share of in-person goods occasions
BUDGET = 45  # combined walking minutes, further limited by diary commitments


def read_inventory(raw, snap, project=walks.project):
    receipts = sorted((raw/"vancouver-ods").glob("*.json.receipt.edn"))
    shops, workplaces, candidates = {}, Counter(), {}
    areas = set()
    for receipt in receipts:
        note = receipt.read_text()
        if ':dataset "storefronts-inventory"' in note and ':where "local_area=\\"Mount Pleasant\\""' in note:
            for row in json.loads(Path(str(receipt).removesuffix(".receipt.edn")).read_text()):
                if row["year_recorded"] != YEAR or row["general_business_category"] != "Vacant":
                    continue
                for store_id, name in CANDIDATES:
                    if row["store_id"] == store_id:
                        point = project(**row["geo_point_2d"])
                        candidates[store_id] = dict(id=str(store_id), name=name, point=point, node=snap(point))
            continue
        area = re.search(r':where "localarea=\\"([^"\\]+)\\""', note)
        if ':dataset "business-licences"' not in note or not area or area[1].startswith("DA "):
            continue
        if area[1] in areas:
            raise ValueError("Duplicate local-area licence extract")
        areas.add(area[1])
        rows = json.loads(Path(str(receipt).removesuffix(".receipt.edn")).read_text())
        latest = {}
        for row in rows:
            if row["folderyear"] != YEAR[-2:]:
                continue
            key = row["licencenumber"]
            if key not in latest or row["licencerevisionnumber"] > latest[key]["licencerevisionnumber"]:
                latest[key] = row
        for row in latest.values():
            if row["status"] != "Issued" or not row["geo_point_2d"]:
                continue
            point = tuple(project(**row["geo_point_2d"]))
            if (row["numberofemployees"] or 0) > 0:
                workplaces[point] += row["numberofemployees"]
            kind = row["businesstype"]
            if kind not in {"Grocery Store", "Retail Dealer - Food"}:
                continue
            address = " ".join(str(row[k] or "") for k in ["house", "street"]).strip().upper()
            if not address or (address in shops and shops[address]["grocery"]):
                continue
            shops[address] = dict(id=address, name=row["businesstradename"] or row["businessname"] or address,
                                  point=point, node=snap(point), grocery=kind == "Grocery Store")
    if len(areas) != 22 or len(candidates) != 2 or not workplaces or not shops:
        raise ValueError("Incomplete 2025 local-area inventory")
    return [candidates[k] for k, _ in CANDIDATES], list(shops.values()), workplaces


def reserved_studies(raw, records):
    """Preselected one-hour morning and afternoon rows, positive on all-approach survey sheets."""
    result = []
    receipts = {f: f.read_text() for f in (raw/"vancouver-arcgis").glob("*.receipt.edn")}
    for record in records:
        if record["site"] not in HOLDOUT:
            continue
        receipt, = [f for f, text in receipts.items() if record["attachment"] in text]
        book = load_workbook(str(receipt).removesuffix(".receipt.edn"), read_only=True, data_only=True)
        try:
            rows = list(book["Ped and Passenger Vehicle"].values)
        finally:
            book.close()
        if rows[3][2] != record["site"] or datetime.strptime(rows[1][2], "%m/%d/%Y").date().isoformat() != record["date"]:
            raise ValueError("Holdout workbook identity mismatch")
        times = [walks.clock_minute(r[0]) for r in rows[10:]]
        cols = [i for i,v in enumerate(rows[9]) if v == "Peds"]
        if len(cols) != 4 or times != list(range(420, 1140, 60)):
            raise ValueError("Expected four pedestrian approaches per hourly row")
        obs = []
        for t in (480, 960):
            counts = [rows[10+times.index(t)][c] for c in cols]
            if not all(type(n) is int and n >= 0 for n in counts):
                raise ValueError("Invalid pedestrian observation")
            total = sum(counts)
            if total <= 0 or total != record["hours"][str(t//60)]:
                raise ValueError("Survey coverage or count mismatch")
            obs.append(total)
        result.append(dict(name=HOLDOUT[record["site"]], point=walks.project(record["lon"],record["lat"]),
                           date=record["date"], hours=[480,960], observed=obs,
                           source=re.search(r':url "([^"]+)"', receipts[receipt])[1]))
    if len(result) != len(HOLDOUT):
        raise ValueError("Missing reserved study")
    return result


def diagnose(person, anchored, graph, legs, studies, totals):
    chain, weight = person["chain"], person["weight"]
    at = next((i for i in anchored if chain[i][0] <= 690 < sum(chain[i][:2])), None)
    for j, study in enumerate(studies):
        center = study["point"]
        if j < 2 and at is not None and math.dist(graph.nodes[anchored[at]]["xy"],center) <= 400:
            totals[j]["present"] += weight
            if chain[at][2:4] == ["paid-work","work-or-school"]:
                totals[j]["working"] += weight
            for k in range(at+1, len(chain)-1):
                if chain[k][0] >= 780 or chain[k][3] != chain[at][3]:
                    if (chain[k][0] < 780 and chain[k][3] == "walk" and k+1 in anchored):
                        totals[j]["departed"] += weight
                        if chain[k+1][3] in {"store","restaurant"}:
                            totals[j]["foodOrStore"] += weight
                    break
        for leg in legs:
            if not any(leg["start"] < t+60 and leg["start"]+leg["dur"] > t for t in study["hours"]):
                continue
            minute = walks.passing_minute(leg["points"], center, leg["start"], leg["dur"])
            if minute is not None:
                hour = str(int(minute//60)*60)
                if int(hour) in study["hours"]:
                    totals[j][hour] += weight


def itinerary(a, b, store, depart, dwell, deadline, distances, hours):
    first = distances[a].get(store["node"], math.inf)/SPEED
    second = distances[b].get(store["node"], math.inf)/SPEED
    if first + second > BUDGET:
        return None
    arrival = depart + first
    service = max(arrival, hours[0])
    leave = service + dwell
    end = leave + second
    if leave > hours[1] or end > deadline + 1e-8:
        return None
    return dict(store=store["id"], name=store["name"], node=store["node"], start=depart,
                arrival=arrival, leave=leave, end=end, minutes=first+second, cost=end-depart)


def opening_choice(baseline, opening, advantage):
    return opening if opening and (baseline is None or opening["cost"]-advantage < baseline["cost"]-1e-8) else baseline


def trip_paths(graph, a, b, trip):
    if trip is None:
        return None
    def segment(u,v):
        path = nx.astar_path(graph,u,v,heuristic=lambda i,j: math.dist(graph.nodes[i]["xy"],graph.nodes[j]["xy"]))
        return [[round(z) for z in graph.nodes[n]["xy"]] for n in path]
    return {k:v for k,v in trip.items() if k not in {"node","cost"}} | {
        "to": segment(a,trip["node"]), "onward": segment(trip["node"],b)}


def scenario_counts():
    return dict(eligible=0., baseline=0., deferred=0., sites=[dict(reachable=0., visits=0., gained=0., diverted=0.,
                minutesSaved=0., origins=Counter(), ages=Counter(), hourly=Counter(), displaced=Counter()) for _ in CANDIDATES])


def shop_day(person, seed, anchors, graph, shops, sites, day, examples):
    chain = person["chain"]
    weight = person["weight"]*SHARE
    for i in person["goods"]:
        if (i < 2 or i+2 >= len(chain) or chain[i-1][3] != "walk" or chain[i+1][3] != "walk"
                or i-2 not in anchors[0] or i+2 not in anchors[0]):
            continue
        pairs = [(m[i-2],m[i+2]) for m in anchors]
        if all(math.dist(graph.nodes[n]["xy"],s["point"]) > 1200 for pair in pairs for n in pair for s in sites):
            continue
        depart, dwell, deadline = chain[i-1][0], chain[i][1], chain[i+2][0]
        cutoff = min(BUDGET, deadline-depart-dwell)*SPEED
        distances = {n:nx.single_source_dijkstra_path_length(graph,n,cutoff=cutoff+1e-7)
                     for n in set(n for pair in pairs for n in pair)}
        for profile in PROFILES:
            a,b = pairs[int(profile["id"]=="jobs")]
            scores = day[profile["id"]]
            scores["eligible"] += weight
            options = (itinerary(a,b,s,depart,dwell,deadline,distances,[480,1200]) for s in shops
                       if s["grocery"] or profile.get("broad"))
            base = min((t for t in options if t),key=lambda t:(t["cost"],t["store"]),default=None)
            scores["baseline" if base else "deferred"] += weight
            for site,score in zip(sites,scores["sites"]):
                new = itinerary(a,b,site,depart,dwell,deadline,distances,profile.get("hours",[480,1200]))
                if new is None:
                    continue
                score["reachable"] += weight
                if opening_choice(base,new,profile.get("advantage",0)) is not new:
                    continue
                score["visits"] += weight
                score["diverted" if base else "gained"] += weight
                score["origins"][person["area"]] += weight
                score["ages"][person["age"]] += weight
                score["hourly"][int(new["arrival"]//60)] += weight
                if base:
                    score["displaced"][base["store"]] += weight
                    score["minutesSaved"] += (base["minutes"]-new["minutes"])*weight
                key = f"{seed}/{person['id']}/{i}/{site['id']}"
                versions = examples.setdefault(key,{})
                model = "jobs" if profile["id"] == "jobs" else "standard"
                # Several assumptions can give the same pair of paths.
                version = f"{model}/{base['store'] if base else '-'}/{new['leave']}"
                if version not in versions:
                    versions[version] = dict(seed=seed,person=person["id"],occasion=i,age=person["age"],
                        area=person["area"],site=site["id"],profiles=[],origin=chain[i-2][3],
                        next=chain[i+2][3],deadline=deadline, weight=weight,
                        before=trip_paths(graph,a,b,base),after=trip_paths(graph,a,b,new))
                versions[version]["profiles"].append(profile["id"])


def build(archive, samples, seeds):
    raw, derived = archive/"data/raw", archive/"data/derived"
    records = json.loads((derived/"vancouver_ped_counts_mp.json").read_text())["counts"]
    studies = []
    for key in list(walks.SURVEYS)[:2]:
        record, = [r for r in records if (r["site"],r["date"]) == key]
        s = walks.verified_study(raw,record,walks.SURVEYS[key])
        first = (720-s["start"])//s["bin"]
        studies.append(dict(name=s["name"],point=s["point"],hours=[720],date=s["date"],
                            observed=[sum(s["observed"][first:first+60//s["bin"]])],source=s["source"]))
    studies.extend(reserved_studies(raw,records))
    graph, _, snap = walks.street_network(raw,walks.Polygon(walks.boundary(raw)))
    venues = walks.destinations(raw)
    sites, shops, jobs = read_inventory(raw,snap)
    points, weights = zip(*jobs.items())
    tree = cKDTree(points)
    centers = [s["point"] for s in studies]
    windows = [(h,h+60) for h in {h for s in studies for h in s["hours"]}]
    runs, examples = [], {}
    for expected,(seed,people) in zip(seeds,groupby(map(json.loads,samples), key=lambda p:p["seed"]),strict=True):
        if seed != expected:
            raise ValueError("Unexpected sample order")
        day = {p["id"]:scenario_counts() for p in PROFILES}
        diagnostic = [[Counter() for _ in studies] for _ in range(2)]
        for person in people:
            key = person["id"] if seed == 2023 else f"{seed}/{person['id']}"
            job_rng = random.Random(f"employment/{seed}/{person['id']}")
            def workplace(target):
                indices = sorted(tree.query_ball_point(target,500))
                if not indices:
                    business = venues["business"]
                    return business.data[business.query(target)[1]]
                n, = job_rng.choices(indices,weights=[weights[i] for i in indices])
                return points[n]
            anchors = [walks.anchor_day(person,graph,snap,venues,random.Random(key),rule) for rule in (None,workplace)]
            for m,anchored in enumerate(anchors):
                if m == 0 or anchored != anchors[0]:
                    legs = list(walks.make_walks(person,graph,snap,venues,None,Counter(),centers,anchored,windows))
                diagnose(person,anchored,graph,legs,studies,diagnostic[m])
            shop_day(person,seed,anchors,graph,shops,sites,day,examples)
        runs.append(dict(seed=seed,profiles=day,diagnostic=diagnostic))
        print(f"Completed seed {seed}, {len(examples)} changed occasion/site pairs so far",flush=True)
    return dict(sites=[{k:v for k,v in s.items() if k!="node"} for s in sites],profiles=PROFILES,studies=studies,
                runs=runs,examples=[v for group in examples.values() for v in group.values()],
                inventory=dict(year=YEAR,grocery=sum(s["grocery"] for s in shops),food=len(shops),
                               jobLocations=len(jobs),reportedEmployees=sum(jobs.values())),
                share=SHARE, speed=SPEED, budget=BUDGET)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--sample",type=Path,help="Reuse enriched walk-sample NDJSON for the selected seeds")
    parser.add_argument("--seed",type=int,default=2023)
    parser.add_argument("--replicates",type=int,default=12)
    parser.add_argument("--output",type=Path,default=Path("public/data/vancouver/grocery.json"))
    args = parser.parse_args()
    if args.replicates < 1:
        parser.error("--replicates must be positive")
    seeds = range(args.seed,args.seed+args.replicates)
    with (args.sample.open() if args.sample else tempfile.TemporaryFile(mode="w+")) as f:
        if not args.sample:
            subprocess.run(["clojure","-M","-m","city.vancouver.walk-sample",str(args.archive),*map(str,seeds)],
                           stdout=f,check=True)
            f.seek(0)
        result = build(args.archive,f,seeds)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w",dir=args.output.parent,delete=False) as f:
        json.dump(result,f,separators=(",",":"),allow_nan=False)
    Path(f.name).chmod(0o644)
    Path(f.name).replace(args.output)


if __name__ == "__main__":
    main()
