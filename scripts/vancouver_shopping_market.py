"""Pair grocery openings with the survey-based increase in Vancouver shopping trips."""
import argparse
from bisect import bisect_right
from collections import defaultdict
from functools import partial
import hashlib
from pathlib import Path
import tempfile

import numpy as np

from scripts.vancouver_market import archive_market, grocery_draw, market_weekday, publish_market, read, score, windows
from scripts.vancouver_shopping_outings import TIME_USE, donor_diaries, weighted_donors
from scripts.vancouver_streets import walk_graph
from scripts.vancouver_transit_commutes import pointer


def goods_classifier(diaries, compiled):
    donors = weighted_donors(diaries, compiled)
    goods = {}
    for hour, records in donors.items():
        for index, start, there, dwell, back, _ in records:
            purchase = any(arrive == start + there and duration == dwell
                           for _, arrive, duration, *_ in windows(diaries[index], compiled["templates"][index]))
            key = (index, hour, dwell)
            goods.setdefault(key, []).append((there, back, purchase))
    return goods


def added_occasions(tours, atlas_dir, day, places, goods, share):
    by_area = defaultdict(list)
    for row in tours:
        by_area[row[0]].append(row)
    qualifying = 0
    occasions, trips = [], []
    for d, entries in sorted(by_area.items()):
        da = day["das"][d]
        people = read(atlas_dir / f"{da}.json")["people"]
        for _, i, home, store, _, mode, start, there, dwell, back, donor in entries:
            if mode != "walk":
                raise ValueError("Added grocery errands use walking tours")
            support = {buy for a, b, buy in goods.get((donor, start // 60, dwell), ())
                       if there <= a and back <= b}
            if len(support) != 1:
                raise ValueError(f"Shopping tour differs from its time-use donor at {da}/{i}")
            if True not in support:
                continue
            qualifying += 1
            if not grocery_draw(da, i + 1, -1, share):
                continue
            income = people[i][3]
            origin_area, store_area = places[home][2], places[store][2]
            occasions.append([d, i, -1, start + there, dwell, -1, None,
                              4 if income is None else bisect_right((30000, 60000, 100000), income),
                              origin_area, store_area, origin_area, there, back, home, home, f"time-use/{donor}",
                              "walk", "added-shopping"])
            trips.append([home, home, there, back])
    return qualifying, occasions, trips


def add_market_choices(recorded, added, base_choices, fitted_choices):
    if {(row[0], row[1]) for row in added} & {(row[0], row[1]) for row in recorded}:
        raise ValueError("Added grocery errands duplicate a recorded purchaser")
    offset = len(recorded)
    for rows, extra in zip(base_choices, fitted_choices, strict=True):
        rows.extend([[i + offset, minutes] for i, minutes in extra])
    recorded.extend(added)


def publish(root, archive, fitted_atlas=None, joint_id=None):
    joint = read(root / "joint-weekday" / joint_id / "report.json") if joint_id else None
    versions = joint["versions"] if joint else market_weekday(root, fitted_atlas)
    streets = versions["streets"]
    day, atlas = versions["day"], versions["atlas"]
    market = root / "market"
    workplace = joint["workplaces"]["tract-workplaces"] if joint else None
    base_path = market / f"{workplace or day}_{streets}.json"
    result = read(base_path)
    if (any(result.get(k) != v for k, v in versions.items()) or "bicycle" in result
            or result.get("workplaces") != workplace
            or (joint and joint["commuteRule"] not in result.get("variants", {}))):
        raise ValueError("The walking-only market belongs to a different weekday")
    if not joint and "variants" in result:
        raise ValueError("A workplace-specific catalogue requires its combined weekday")
    base = archive_market(root, base_path, result)
    if joint and read(market / "archive" / base / "run.json")["workplaceRuns"] != joint["workplaces"]:
        raise ValueError("The base market and combined weekday use different workplace releases")
    outings_root = root / "discretionary-outings"
    outings = joint["outings"] if joint else read(outings_root / f"{atlas}_{day}.json")["version"]
    folder = outings_root / outings
    report, tours = read(folder / "report.json"), read(folder / "tours.json")
    if any(report["versions"].get(k) != v for k, v in versions.items()) or len(tours) != report["attendance"]:
        raise ValueError("Shopping outings and grocery catalogue have different parents")
    day_dir = root / "cityday" / day
    places = read(day_dir / "places.json")
    with tempfile.TemporaryDirectory(dir=market) as tmp:
        scratch = Path(tmp)
        diaries, compiled = donor_diaries(archive, scratch)
        digest = hashlib.sha256((scratch / "time-use.json").read_bytes()).hexdigest()
    goods = goods_classifier(diaries, compiled)
    qualifying, added, trips = added_occasions(
        tours, root / "atlas" / atlas, read(day_dir / "day.json"), places, goods, result["share"])
    if not added:
        raise ValueError("No added trips qualify as grocery errands")
    graph, snap = walk_graph(read(root / "streets" / streets / "network.json"))
    snap = partial(snap, lowest_id_on_ties=True)
    nodes, distances = snap(np.asarray([p[:2] for p in places]))
    changes, after_hours = score(added, trips, graph, snap, nodes, distances, result["stores"], result["sites"])
    if any(after_hours):
        raise ValueError("Added shopping visits must fit the original retail hours")
    for run in result["runs"] if joint else [result]:
        if joint:
            scored = run["changes"]
            has_extended_hours = "afterHours" in run
        else:
            scored = [site["changes"] for site in result["sites"]]
            has_extended_hours = all("afterHours" in site for site in result["sites"])
        if not has_extended_hours:
            raise ValueError("The paired source market must include extended shop hours")
        add_market_choices(run["occasions"], added, scored, changes)
        run["eligible"] += qualifying
        run["coverage"]["qualifying"] += qualifying
        run["coverage"]["drawn"] += len(added)
    result["shoppingDemand"] = dict(baseMarket=base, outings=outings, timingSource=TIME_USE, timingDigest=digest,
                                    fitted=len(tours), goods=qualifying, grocery=len(added),
                                    feasible=sum(row[5] >= 0 for row in added))
    if joint:
        result["jointRun"] = joint_id
    version = publish_market(root, result)
    key = joint_id or f"{atlas}_{day}_{streets}"
    pair = {**versions, "baseMarket": base, "market": version, "outings": outings}
    if joint:
        pair["jointRun"] = joint_id
    pointer(market / f"demand_{key}.json", pair)
    print(version, result["shoppingDemand"], flush=True)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--fitted-atlas", help="Use the published weekday and street network for a fitted atlas")
    selection.add_argument("--joint", help="Use the market and outings pinned by a combined weekday")
    args = parser.parse_args()
    publish(args.root, args.archive, args.fitted_atlas, args.joint)
