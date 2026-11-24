"""Score bicycle shopping stops in the published day against the same storefronts as walking."""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from functools import partial
import hashlib
import tempfile
from pathlib import Path

import numpy as np

from scripts.vancouver_cycle_tours import SPEED
from scripts.vancouver_cycling import FORWARD, REVERSE
from scripts.vancouver_atlas import write_json
from scripts.vancouver_grocery import SHARE
from scripts.vancouver_grocery_survey import read_survey
from scripts.vancouver_market import gather as walking_windows
from scripts.vancouver_market import grocery_draw, locate, publish_market, read, score, windows
from scripts.vancouver_streets import access_graph, walk_graph


def gather(atlas_dir, day_dir, tours, active_share=SHARE, driver_share=SHARE):
    atlas = read(atlas_dir/"atlas.json")
    day = read(day_dir/"day.json")
    options = {m: [windows(d, t, m) for d, t in zip(atlas["templates"], day["templates"], strict=True)]
               for m in ("bike", "car-driver")}
    assigned = defaultdict(dict)
    for d, i, tpl, _, _, legs, access in tours:
        person = assigned[d].setdefault(i, (tpl, access, set()))
        if person[:2] != (tpl, access):
            raise ValueError("Outings disagree on the resident's diary or access")
        person[2].update(s for s, n, a, b in legs)
    for d, da in enumerate(day["das"]):
        people = read(atlas_dir/(da+".json"))["people"]
        plans = read(day_dir/(da+".json"))["plans"]
        for i, (person, plan) in enumerate(zip(people, plans, strict=True)):
            tpl = person[-1]
            tour = assigned[d].get(i)
            if tour and tour[0] != tpl:
                raise ValueError("Bicycle outings use another resident diary")
            for mode in (("bike", "car-driver") if tour else ("bike",)):
                for slot, start, dwell, a, b, first, second in options[mode][tpl]:
                    if mode == "car-driver" and not {start-first, start+dwell} <= tour[2]:
                        continue
                    cohort = "diary" if mode == "bike" else "access" if tour[1] else "universalOnly"
                    income = 4 if person[3] is None else bisect_right((30000, 60000, 100000), person[3])
                    yield cohort, (d, i, slot, start, dwell, income, tpl, a, b, plan[a], plan[b],
                                   plan[slot], first, second, grocery_draw(da, i+1, slot, active_share if mode == "bike" else driver_share))


def publish(root, survey_file=None):
    ptr = read(root/"cityday/current.json")
    atlas, day = ptr["atlas"], ptr["version"]
    streets = read(root/"streets/current.json")["version"]
    cycling = read(root/"cycling"/(streets+".json"))["version"]
    tours = read(root/"cycle-tours"/("_".join([atlas, day, streets, cycling])+".json"))["version"]
    folder = root/"cycle-tours"/tours
    versions = read(folder/"report.json")["versions"]
    catalog = read(root/"market"/(day+"_"+streets+".json"))
    if (any(versions[k] != v for k, v in dict(atlas=atlas, day=day, streets=streets, cycling=cycling).items())
        or any(catalog[k] != versions[k] for k in ("atlas", "day", "streets")) or "runs" in catalog):
        raise ValueError("Walking market, cycling outings and spatial releases differ")
    day_dir = root/"cityday"/day
    places = read(day_dir/"places.json")
    coords = np.array([p[:2] for p in places])
    active_share = driver_share = SHARE
    if survey_file:
        base = root/"market"/(tours+"_"+streets+".json")
        if not base.is_file():
            raise ValueError("Publish the fixed-share bicycle market before pairing the survey scenario")
        original = hashlib.sha256(base.read_bytes()).hexdigest()
        if not (base.parent/"archive"/original/"run.json").is_file():
            raise ValueError("The fixed-share bicycle market has no archived release")
        # Reuse exactly the same retail alternatives, resident identities and random quantiles.
        survey = read_survey(survey_file)
        bc = survey["pools"]["bc"]
        active_share, driver_share = bc["active"]["share"], bc["car-driver"]["share"]
        if any(p is None for p in (active_share, driver_share)):
            raise ValueError("Insufficient survey support for a grocery purchase rule")
        adir = root/"atlas"/atlas
        candidates = walking_windows(read(adir/"atlas.json"), read(day_dir/"day.json"), adir, day_dir, share=active_share)
        coverage, walking, paths = locate(candidates, places, {})
        graph, snap = walk_graph(read(root/"streets"/streets/"network.json"))
        nodes, offsets = snap(coords)
        changed, later = score(walking, paths, graph, snap, nodes, offsets, catalog["stores"], catalog["sites"])
        for site, regular, late in zip(catalog["sites"], changed, later, strict=True):
            site.update(changes=regular, afterHours=late)
        catalog.update(share=active_share, occasions=walking, coverage=coverage,
                       eligible=coverage["qualifying"]-coverage["external"]-coverage["missing"],
                       purchase=dict(key="bc2010", driverShare=driver_share, survey=survey))
    sets = defaultdict(list)
    for cohort, row in gather(root/"atlas"/atlas, day_dir, read(folder/"tours.json"), active_share, driver_share):
        sets[cohort].append(row)
    cohorts, occasions, trips = {}, [], []
    for cohort in ("diary", "access", "universalOnly"):
        coverage, chosen, paths = locate(sets[cohort], places, {})
        cohorts[cohort] = coverage
        occasions.extend([*row, "bike", cohort] for row in chosen)
        trips.extend(paths)
    identities = Counter(tuple(r[:3]) for r in catalog["occasions"] + occasions)
    if any(n != 1 for n in identities.values()):
        raise ValueError("Duplicate shopping stop across travel cohorts")
    graph, snap = access_graph(read(root/"cycling"/cycling/"network.json"), FORWARD, REVERSE)
    snap = partial(snap, lowest_id_on_ties=True)
    nodes, offsets = snap(coords)
    changes, after = score(occasions, trips, graph, snap, nodes, offsets, catalog["stores"],
                           catalog["sites"], speed=SPEED, directed=True, coords=coords)
    catalog["bicycle"] = dict(tours=tours, cycling=cycling, speed=SPEED, cohorts=cohorts,
                              occasions=occasions, changes=changes, afterHours=after)
    digest = publish_market(root, catalog)
    if survey_file:
        with tempfile.TemporaryDirectory(dir=base.parent) as tmp:
            file = Path(tmp)/"choices.json"
            write_json(file, dict(tours=tours, streets=streets, fixed=original, bc2010=digest))
            file.replace(base.with_name("choices-"+base.name))
    print(tours, cohorts, len(occasions), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--grocery-survey", type=Path, help="2010 Statistics Canada GSS ZIP for the paired historical purchase rule")
    args = parser.parse_args()
    publish(args.root, args.grocery_survey)
