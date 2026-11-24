"""Compare grocery openings across the full city-day roster on its walking network."""
import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from bisect import bisect_right
from pathlib import Path

import numpy as np
from scipy.sparse.csgraph import dijkstra

from scripts.vancouver_atlas import write_json
from scripts.vancouver_cityday import receipts, xy
from scripts.vancouver_streets import walk_graph
from scripts.vancouver_grocery import BUDGET, SHARE, SPEED, YEAR, read_inventory


def read(path):
    return json.loads(path.read_text())


def market_weekday(root, fitted_atlas=None):
    if fitted_atlas:
        fit = read(root / "diary-fit" / (fitted_atlas + ".json"))
        versions = fit["locations"]
        if versions["atlas"] != fitted_atlas:
            raise ValueError("The retail catalogue requires the matching fitted weekday")
        return versions
    day = read(root / "cityday/current.json")
    return dict(atlas=day["atlas"], day=day["version"], streets=read(root / "streets/current.json")["version"])


def windows(diary, template, travel_mode="walk"):
    """One goods-only stop bounded by two pure travel legs with fixed neighbouring stops."""
    parts = template["parts"]
    goods = {tuple(diary["episodes"][i][:2]) for i in diary.get("goods", [])}
    result = []
    for k in range(2, len(parts)-2):
        before, inbound, stop, outbound, after = parts[k-2:k+3]
        start, dwell, mode, slot, _ = stop
        if mode != "stop" or (start,dwell) not in goods or template["slots"][slot] != "store":
            continue
        if before[2] != "stop" or after[2] != "stop" or inbound[2] != travel_mode or outbound[2] != travel_mode:
            continue
        if "store" in (template["slots"][before[3]],template["slots"][after[3]]):
            continue
        # A dominant walking mode in a grouped multimodal bout is insufficient.
        if not all(loc==travel_mode for s,_,_,loc in diary["episodes"]
                   if inbound[0]<=s<start or outbound[0]<=s<after[0]):
            continue
        result.append((slot, start, dwell, before[3], after[3], inbound[1], outbound[1]))
    return result


def grocery_draw(da, person, slot, share=SHARE):
    key = f"grocery-2021/{da}/{person}/{slot}".encode()
    return int.from_bytes(hashlib.blake2b(key,digest_size=8).digest(),"big") < int(share*2**64)


def alternatives(raw, areas):
    files=receipts(raw/"vancouver-ods","storefronts-inventory",r':where "local_area=\\"([^"\\]+)\\""')
    sites={}
    for file in files:
        for row in read(file):
            if row["year_recorded"]!=YEAR or row["general_business_category"]!="Vacant" or not row["geo_point_2d"]:
                continue
            ref=str(row["store_id"])
            site=dict(id=ref,name=row["address"],point=xy(**row["geo_point_2d"]),area=areas.index(row["local_area"]))
            if ref in sites:
                existing=sites[ref]
                if (site["point"],site["area"])!=(existing["point"],existing["area"]):
                    raise ValueError(f"Conflicting storefront coordinates for {ref}")
                existing["name"]=" / ".join(sorted(set(existing["name"].split(" / ")+[site["name"]])))
            else:
                sites[ref]=site
    return sorted(sites.values(),key=lambda s:(s["area"],s["name"],s["id"]))


def feasible(inward, onward, inbound_limit, outbound_limit, speed=SPEED):
    return (inward<=inbound_limit*speed)&(onward<=outbound_limit*speed)&(inward+onward<=BUDGET*speed)


def workplace_inputs(root, atlas, day, street, preserve_modes=False, tract_release=None):
    if tract_release is not None and not re.fullmatch(r"[a-f0-9]{20}", tract_release):
        raise ValueError("Choose a published tract workplace release")
    pointer = root / "outbound" / (atlas + "_" + day + ".json")
    if not pointer.exists():
        return None
    version = read(pointer)["version"]
    directory = root / "outbound" / version
    report = read(directory / "report.json")
    if (report["atlas"], report["day"]) != (atlas, day):
        raise ValueError("Grocery and external workplace days differ")
    rules = {"diary": {}, "usual": {}, "local": {}}
    parent = version
    for family, rule in [("worksites", "sites"), ("tract-workplaces", "tracts")]:
        suffix = "_diary_modes.json" if family == "tract-workplaces" and preserve_modes else ".json"
        ptr = root / family / (parent + suffix)
        if family == "tract-workplaces" and tract_release:
            release = tract_release
        else:
            if not ptr.exists():
                if preserve_modes:
                    raise ValueError("Publish the diary-mode workplace assignment before its retail comparison")
                break
            release = read(ptr)["version"]
        data = read(root / family / release / "worksites.json")
        if (data["atlas"], data["day"], data["outbound"]) != (atlas, day, version):
            raise ValueError("Grocery and matched workplace days differ")
        if family == "worksites" and data["streets"] != street:
            raise ValueError("Walking workplace and grocery graphs differ")
        if family == "tract-workplaces" and data["worksites"] != parent:
            raise ValueError("Census tract and walking workplace releases differ")
        if family == "tract-workplaces" and bool(data.get("preserveDiaryModes")) != preserve_modes:
            raise ValueError("The retail catalogue and workplaces use different commute policies")
        if family == "tract-workplaces" and preserve_modes and data["streets"] != street:
            raise ValueError("The retail and commute replay use different street networks")
        rules[rule] = {(d, i, slot): site for d, i, slot, _, site in data["changes"]}
        parent = release
    return dict(parent=parent, rules=rules, paid=list(map(set, report["slots"])),
                outside=[{row[0] for row in shard} for shard in read(directory / "assignments.json")])


def gather(atlas, day, atlas_dir, day_dir, clock=None, share=SHARE, continuous=False):
    options = [windows(d, t) for d, t in zip(atlas["templates"], day["templates"], strict=True)]
    offset = 0
    for d, da in enumerate(day["das"]):
        roster = read(atlas_dir / (da + ".json"))
        assignment = read(day_dir / (da + ".json"))
        if clock is not None:
            for i, old, new in clock["changes"][da]:
                if roster["people"][i][-1] != old:
                    raise ValueError("Household clock differs from market roster")
                roster["people"][i][-1] = new
        for i, (person, plan) in enumerate(zip(roster["people"], assignment["plans"], strict=True)):
            template = person[-1]
            for slot, start, dwell, a, b, first, second in options[template]:
                if continuous:
                    # Roster order and within-bin phase match city.vancouver.diary-clock.
                    start += 5 * (((offset + i + 1) * 7919 % 10007) + 0.5) / 10007 - 2.5
                chosen = grocery_draw(da, i + 1, slot, share)
                income = 4 if person[3] is None else bisect_right((30000, 60000, 100000), person[3])
                yield (d, i, slot, start, dwell, income, template, a, b, plan[a], plan[b],
                       plan[slot], first, second, chosen)
        offset += len(roster["people"])


def locate(windows_, places, changes, workplaces=None):
    coverage = dict(qualifying=0, drawn=0, external=0, missing=0, externalDrawn=0, missingDrawn=0)
    occasions, trips = [], []
    for d, i, slot, start, dwell, band, tpl, a, b, original_a, original_b, shop, first, second, chosen in windows_:
        coverage["qualifying"] += 1
        coverage["drawn"] += int(chosen)
        u = changes.get((d, i, a), original_a)
        v = changes.get((d, i, b), original_b)
        external = (workplaces is not None and i in workplaces["outside"][d]
                    and (a in workplaces["paid"][tpl] or b in workplaces["paid"][tpl]))
        if external or min(u, v) < 0:
            reason = "external" if external else "missing"
            coverage[reason] += 1
            coverage[reason + "Drawn"] += int(chosen)
        elif chosen:
            shop_area = places[shop][2] if shop >= 0 else -1
            occasions.append([d, i, slot, start, dwell, -1, None, band,
                              places[u][2], shop_area, places[v][2], first, second, u, v, tpl])
            trips.append([u, v, first, second])
    return coverage, occasions, trips


def score(occasions, trips, graph, snap, venue_nodes, offsets, stores, sites, *, speed=SPEED, directed=False, coords=None):
    origin, dest, first, second = np.array(trips, dtype=int).reshape(-1, 4).T
    start = np.array([o[3] for o in occasions])
    end = start + np.array([o[4] for o in occasions])
    incumbent_hours = (start >= 480) & (end <= 1200)
    reverse = graph.transpose().tocsr() if directed else graph

    def costs(store):
        node, connector = snap(store["point"])
        dist = dijkstra(graph, indices=node, limit=BUDGET * speed)
        incoming = dijkstra(reverse, indices=node, limit=BUDGET * speed) if directed else dist
        inward = offsets[origin] + incoming[venue_nodes[origin]] + connector
        onward = connector + dist[venue_nodes[dest]] + offsets[dest]
        possible = feasible(inward, onward, first, second, speed)
        if directed:
            possible &= (inward > 0) & (onward > 0)
            possible &= (coords[origin] != store["point"]).any(axis=1) & (coords[dest] != store["point"]).any(axis=1)
        return np.where(possible, (inward + onward) / speed, np.inf)

    winner = np.full(len(trips), -1, dtype=int)
    best = np.full(len(trips), np.inf)
    for j, store in enumerate(stores):
        candidate = costs(store)
        improves = incumbent_hours & (candidate < best - 1e-8)
        winner[improves], best[improves] = j, candidate[improves]
    for k, row in enumerate(occasions):
        row[5] = int(winner[k])
        if winner[k] >= 0:
            row[6] = round(best[k], 3)
    changes, after_hours = [], []
    for site in sites:
        candidate = costs(site)
        improves = candidate < best - 1e-8
        for mask, rows in ((incumbent_hours, changes), (~incumbent_hours, after_hours)):
            rows.append([[int(k), round(candidate[k], 3)] for k in np.flatnonzero(improves & mask)])
    return changes, after_hours


def build(raw, atlas_dir, day_dir, street_dir, workplaces=None, clock=None, continuous=False):
    atlas=read(atlas_dir/"atlas.json");day=read(day_dir/"day.json")
    places=read(day_dir/"places.json");coords=np.array([p[:2] for p in places])
    graph,snap=walk_graph(read(street_dir/"network.json"))
    venue_nodes,offset=snap(coords)
    if any("goods" not in t for t in atlas["templates"] if t["source"]=="Urban BC weekday diary (15+)"):
        raise ValueError("Rebuild the atlas and city day to include the in-person goods diary detail.")
    _,inventory,_=read_inventory(raw,lambda _:None,project=xy)
    stores=sorted([s for s in inventory if s["grocery"]],key=lambda s:s["id"])
    # Assign the retailer's neighbourhood by polygon containment, including edge cases.
    import duckdb
    with duckdb.connect() as db:
        db.execute("LOAD spatial")
        polys=[(area,json.dumps(atlas["areas"][area]["geometry"])) for area in day["areas"]]
        db.execute("create table area (name varchar, geom geometry)")
        db.executemany("insert into area values (?, ST_GeomFromGeoJSON(?))",polys)
        for store in stores:
            x,y=store["point"]
            row=db.execute("select name from area where st_covers(geom,st_point(?,?)) order by name limit 1",
                           (x/72600-123.1,49.26-y/111195)).fetchone()
            store["area"]=day["areas"].index(row[0]) if row else -1
    stores=[s for s in stores if s["area"]>=0]
    sites = alternatives(raw, day["areas"])
    catalog = dict(day=day_dir.name, atlas=atlas_dir.name, streets=street_dir.name, share=SHARE,
                   speed=SPEED, budget=BUDGET, stores=[{k:s[k] for k in ("id","name","area","point")} for s in stores],
                   sites=sites)
    if clock:
        if (clock["atlas"], clock["day"]) != (atlas_dir.name, day_dir.name) or workplaces:
            raise ValueError("Incompatible market and household clock releases")
        catalog["clock"] = clock["version"]
    candidates = list(gather(atlas, day, atlas_dir, day_dir, clock, continuous=continuous))
    variants, runs, seen = {}, [], {}
    for rule, changes in (workplaces["rules"] if workplaces else {"diary": {}}).items():
        coverage, occasions, trips = locate(candidates, places, changes, workplaces)
        # Identical inputs give identical store choices, including the resident ordering.
        signature = json.dumps([coverage, occasions, trips], separators=(",", ":"))
        if signature not in seen:
            site_changes, after_hours = score(occasions, trips, graph, snap, venue_nodes, offset, stores, sites)
            eligible = coverage["qualifying"] - coverage["external"] - coverage["missing"]
            seen[signature] = len(runs)
            runs.append(dict(coverage=coverage, eligible=eligible, occasions=occasions,
                             changes=site_changes, afterHours=after_hours))
        variants[rule] = seen[signature]
    if workplaces:
        return dict(**catalog, workplaces=workplaces["parent"], variants=variants, runs=runs)
    run, = runs
    for site, changes, extra in zip(sites, run.pop("changes"), run.pop("afterHours"), strict=True):
        site["changes"] = changes
        site["afterHours"] = extra
    return dict(**catalog, **run)


def archive_market(root, file, payload):
    """Retain the scored catalogue and resolve every workplace parent for later replay."""
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    archive = root / "market" / "archive"
    archive.mkdir(exist_ok=True)
    release = archive / digest
    if release.is_dir():
        return digest
    parents = {k: payload[k] for k in ("atlas", "day", "streets")}
    if "bicycle" in payload:
        parents.update(tours=payload["bicycle"]["tours"], cycling=payload["bicycle"]["cycling"])
    if "localWalk" in payload:
        parents["localWalk"] = True
    if "clock" in payload:
        parents["clock"] = payload["clock"]
    if "clockKind" in payload:
        parents["clockKind"] = payload["clockKind"]
    if "parentMarket" in payload:
        parents["parentMarket"] = payload["parentMarket"]
    if "shoppingDemand" in payload:
        parents["shoppingOutings"] = payload["shoppingDemand"]["outings"]
    if "jointRun" in payload:
        parents["jointRun"] = payload["jointRun"]
    if "workplaces" in payload:
        parent = payload["workplaces"]
        lineage = {}
        for family, filename in (("tract-workplaces", "worksites.json"), ("worksites", "worksites.json"),
                                 ("outbound", "report.json")):
            path = root / family / parent / filename
            if path.exists():
                model = read(path)
                if any(model[k] != parents[k] for k in ("atlas", "day")):
                    raise ValueError("Workplace model and shop catalogue have different parents")
                lineage[family] = parent
                parent = model.get("worksites") if family == "tract-workplaces" else model.get("outbound")
        if not lineage.get("outbound"):
            raise ValueError("Missing workplace parent for archived market")
        parents["workplaceRuns"] = lineage
    with tempfile.TemporaryDirectory(dir=archive) as tmp:
        directory = Path(tmp) / "release"
        directory.mkdir()
        try:
            os.link(file, directory / "market.json")
        except OSError:
            shutil.copyfile(file, directory / "market.json")
        write_json(directory / "run.json", {**parents, "city": "vancouver", "market": digest})
        try:
            directory.rename(release)
        except OSError:
            if not release.is_dir():
                raise
    return digest


def publish_market(root, payload):
    parent = payload.get("bicycle", {}).get("tours") or payload.get("clock") or payload.get("workplaces", payload["day"])
    output = root / "market"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output) as tmp:
        file = Path(tmp) / "scenario"
        write_json(file, payload)
        digest = archive_market(root, file, payload)
        suffix = "_" + payload["purchase"]["key"] if "purchase" in payload else ""
        if "localWalk" in payload:
            suffix += "_walk"
        if "shoppingDemand" not in payload:
            file.replace(output / (parent + "_" + payload["streets"] + suffix + ".json"))
    return digest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path)
    parser.add_argument("--data",type=Path,default=Path("public/data/vancouver"))
    parser.add_argument("--backend", default="jvm")
    parser.add_argument("--continuous", action="store_true", help="Score the regional market on the within-bin diary clock")
    weekday = parser.add_mutually_exclusive_group()
    weekday.add_argument("--day", help="Use a published weekday under the current atlas")
    weekday.add_argument("--fitted-atlas", help="Use the published weekday and street network for a fitted atlas")
    parser.add_argument("--verify-households", action="store_true")
    parser.add_argument("--workplaces-only", action="store_true")
    parser.add_argument("--preserve-modes", action="store_true", help="Use the workplace assignment with fixed diary modes")
    parser.add_argument("--tract-release", help="Pin a published tract workplace layout")
    parser.add_argument("--household-clock", action="store_true")
    args=parser.parse_args();root=args.data
    if root.name == "region" and (root / "current.json").is_file():
        if args.day or args.fitted_atlas or args.household_clock or args.workplaces_only:
            parser.error("Regional groceries use the regional weekday manifest")
        versions = read(root / "current.json")
        payload = build(args.archive / "data/raw", root / "atlas" / versions["atlas"],
                        root / "cityday" / versions["day"], root / "streets" / versions["streets"], continuous=args.continuous)
        payload["inventoryCoverage"] = "City of Vancouver storefront inventory"
        if args.continuous:
            target = root / "market" / (versions["day"] + "_" + versions["streets"] + "-continuous.json")
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as tmp:
                json.dump(payload, tmp, separators=(",", ":"))
            Path(tmp.name).replace(target)
        else:
            publish_market(root, payload)
        return
    if args.continuous:
        parser.error("--continuous requires the regional weekday manifest")
    versions = market_weekday(root, args.fitted_atlas)
    if args.day:
        versions["day"] = args.day
    atlas, day, street = (versions[k] for k in ("atlas", "day", "streets"))
    inputs = (args.archive / "data/raw", root / "atlas" / atlas, root / "cityday" / day, root / "streets" / street)
    if args.household_clock:
        clocks = root / "household-clock"
        version = read(clocks / (atlas + "_" + day + ".json"))["version"]
        clock = read(clocks / version / "clock.json")
        payload = build(*inputs, clock={**clock, "version": version})
        publish_market(root, payload)
        print("Household-clock grocery occasions", len(payload["occasions"]), flush=True)
        return
    workplaces = workplace_inputs(root, atlas, day, street, args.preserve_modes, args.tract_release)
    if workplaces:
        combined = build(*inputs, workplaces=workplaces)
        publish_market(root, combined)
        print("Census-workplace shopping occasions:", [len(r["occasions"]) for r in combined["runs"]], flush=True)
    if args.workplaces_only:
        if not workplaces:
            parser.error("Build the census-workplace day before its retail comparison")
        return
    payload = build(*inputs)
    publish_market(root, payload)
    from scripts.vancouver_household_market import publish
    publish(args.archive, root, payload, args.backend, args.verify_households)
    print(f"{payload['eligible']} qualifying walking occasions, {len(payload['occasions'])} grocery occasions, "
          f"{len(payload['stores'])} existing grocers, {len(payload['sites'])} alternative sites.")


if __name__=="__main__":
    main()
