"""Fit workday lunch walks without changing paid work or travel outside the break."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import tempfile

import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_cityday import compile_day, overture_venues, xy
from scripts.vancouver_discretionary_outings import WALK_SPEED, accessible_sites, raster_clock
from scripts.vancouver_flexible_transit import protected_intervals
from scripts.vancouver_pedestrians import passage_counts
from scripts.vancouver_region import package, read
from scripts.vancouver_streets import walk_graph
from scripts.vancouver_transit_commutes import pointer
from scripts.vancouver_walks import can_reach_site

LUNCH_HOURS = (660, 840)
MIN_MEAL = 10
MEAL = "Workplace lunch"
SOURCE = "https://www150.statcan.gc.ca/n1/en/catalogue/452500012025001"
SEED = 20221130


def lunch_profile(diary, spatial):
    """Identify on-site midday meals and single-mode restaurant tours between paid shifts."""
    episodes = diary["episodes"]
    parts, slots = spatial["parts"], spatial["slots"]
    paid = [(s, s+n) for s, n, activity, location in episodes
            if activity == "paid-work" and location == "work-or-school"]
    at_work, out = [], []

    def works(part, when, before):
        start, duration, mode, slot, _ = part
        if mode != "stop" or slots[slot] != "job":
            return False
        lo, hi = (start, when) if before else (when, start+duration)
        return lo < hi and any(a < hi and lo < b for a, b in paid)

    for start, duration, activity, location in episodes:
        if activity != "eating" or location != "work-or-school" or duration < MIN_MEAL:
            continue
        end = start + duration
        if not (LUNCH_HOURS[0] <= start and end <= LUNCH_HOURS[1]):
            continue
        for part in parts:
            if part[0] <= start and end <= part[0]+part[1] and works(part, start, True) and works(part, end, False):
                at_work.append((part[3], start, duration))
                break

    for job, leave, venue, back, resume in zip(parts, parts[1:], parts[2:], parts[3:], parts[4:]):
        start, outward, mode, origin, destination = leave
        end = back[0] + back[1]
        if (mode != "walk" or back[2] != "walk" or venue[2] != "stop" or slots[venue[3]] != "restaurant"
                or start < LUNCH_HOURS[0] or end > LUNCH_HOURS[1] or venue[1] < MIN_MEAL
                or not works(job, start, True) or not works(resume, end, False)):
            continue
        if not any(a == "eating" and l == "restaurant" and venue[0] <= s < back[0] for s, _, a, l in episodes):
            continue
        if any(location != "walk" for s, _, _, location in episodes if start <= s < start+outward or back[0] <= s < end):
            continue
        out.append((origin, destination, back[4], start, outward, venue[1], back[1]))
    return at_work, out


def timing_sample(diaries):
    groups = defaultdict(Counter)
    donors = []
    for diary in diaries:
        meals, visits = lunch_profile(diary, compile_day(diary["episodes"]))
        if not (meals or visits):
            continue
        group = groups[diary["pool"]]
        label = "restaurant" if visits else "atWork"
        group[label] += 1
        group[label+"Weight"] += diary["weight"]
        if visits:
            donors.append((*visits[0][3:], diary["weight"]))
    weight = sum(sum(row.get(k, 0) for k in ("atWorkWeight", "restaurantWeight")) for row in groups.values())
    if not donors or weight <= 0:
        raise ValueError("No weighted urban weekday lunch comparison is available")
    return donors, sum(row[-1] for row in donors) / weight, dict(groups)


def lunch_roster(root, joint):
    version = joint["versions"]
    atlas_dir, day_dir = root/"atlas"/version["atlas"], root/"cityday"/version["day"]
    atlas, day = read(atlas_dir/"atlas.json"), read(day_dir/"day.json")
    place = read(day_dir/"places.json")
    workplace = joint["workplaces"]
    tract = read(root/"tract-workplaces"/workplace["tract-workplaces"]/"worksites.json")
    if not tract.get("preserveDiaryModes") or any(tract[k] != v for k, v in version.items()):
        raise ValueError("The weekday must use the fitted diaries and their published workplace layout")
    changes = {(d,i,slot): dest for d,i,slot,_,dest in tract["changes"]}
    external = read(root/"outbound"/workplace["outbound"]/"assignments.json")
    profiles = [lunch_profile(d, s) for d,s in zip(atlas["templates"], day["templates"], strict=True)]
    used = protected_intervals(root, version, day, joint["outings"])
    # Include the combined day's surviving inferred walks. A conservative block may also keep a
    # candidate out when the same inferred walk was dropped on the combined release.
    population, recorded = [], 0
    for d,da in enumerate(day["das"]):
        people = read(atlas_dir/(da+".json"))["people"]
        plans = read(day_dir/(da+".json"))["plans"]
        outside = {i for i, *_ in external[d]}
        for i,(person, plan) in enumerate(zip(people, plans, strict=True)):
            if i >= atlas["das"][da]["private"] or not 3 <= person[0] <= 13 or i in outside:
                continue
            meals, visits = profiles[person[-1]]
            if not (meals or visits):
                continue

            def position(slot):
                return changes.get((d,i,slot), plan[slot])

            if any((work := position(a)) >= 0 and work == position(c) and position(b) >= 0
                   and min(place[work][2], place[position(b)][2]) >= 0 for a,b,c,*_ in visits):
                recorded += 1
                continue
            options = []
            for slot,start,duration in meals:
                job = position(slot)
                if job >= 0 and place[job][2] >= 0 and not any(a < start+duration and start < b for a,b in used[da,i]):
                    options.append((job,start,duration))
            if options:
                population.append((d,i,options))
    return day, place, population, recorded


def fit_lunch(population, routes, donors, target):
    rng = np.random.default_rng(SEED)
    result = []
    if target <= 0:
        return result
    for index in rng.permutation(len(population)):
        d,i,breaks = population[index]
        options, weights = [], []
        for job,start,length in breaks:
            for site, there, back in routes[job,MEAL]:
                for donor,(preferred, before, dwell, after, weight) in enumerate(donors):
                    slack = length - (there+dwell+back)
                    if slack < 0 or there > before or back > after:
                        continue
                    leave = min(start+slack, max(start, preferred))
                    options.append([d,i,job,site,MEAL,"walk",leave,there,dwell,back,donor])
                    weights.append(weight*np.exp(-(abs(preferred-leave)+(there+back))/30))
        if options:
            weight = np.asarray(weights)
            result.append(options[rng.choice(len(options), p=weight/weight.sum())])
        if len(result) == target:
            break
    return sorted(result)


def sidewalk_comparison(baseline, network, places, tours):
    sites = baseline["sites"]
    legs = []
    for _,_,job,site,_,_,start,there,dwell,back,*_ in tours:
        for a,b,minute,duration in ((job,site,start,there),(site,job,start+there+dwell,back)):
            limit = WALK_SPEED * duration
            if any(any(h < minute+duration and minute < h+60 for h in row["hours"])
                   and can_reach_site(places[a][:2], places[b][:2], row["point"], limit) for row in sites):
                legs.append(("lunch",a,b,minute,duration,limit))
    counts = passage_counts(network,places,sites,legs)
    return [dict(name=site["name"], source=site["source"], hours=site["hours"], baseline=site["joint"], observed=site["observed"],
                 added=[counts[i,"lunch",hour] for hour in site["hours"]]) for i,site in enumerate(sites)]


def publish(root, archive, joint_id, evidence, backend):
    joint_path = root/"joint-weekday"/joint_id
    joint = read(joint_path/"report.json")
    donors, rate, groups = timing_sample(read(evidence))
    day, places, population, recorded = lunch_roster(root, joint)
    target = max(0, round((len(population)+recorded)*rate)-recorded)
    print(f"{len(population):,} on-site meals in eligible breaks, {recorded:,} existing walks out, {target:,} additional trips to fit", flush=True)
    coords = [place[:2] for place in places]
    names = {(x,y,label): i for i,(x,y,area,label) in enumerate(places) if area >= 0 and label}
    restaurants = sorted({names[key] for lon,lat,kind,label in overture_venues(archive/"data/raw")
                          if kind == "restaurant" and (key := (*xy(lon,lat),label)) in names})
    network = read(root/"streets"/joint["versions"]["streets"]/"network.json")
    graph, snap = walk_graph(network)
    max_walk = max(max(a,b) for _,a,_,b,_ in donors)*WALK_SPEED
    routes = accessible_sites(sorted({job for _,_,breaks in population for job,*_ in breaks}), {MEAL: restaurants},
                              coords,graph,snap,max_walk,500,WALK_SPEED)
    tours = fit_lunch(population,routes,donors,target)
    baseline = read(joint_path/"occupancy.json")
    with tempfile.TemporaryDirectory() as tmp:
        clock = (raster_clock(tours, places, baseline, day["areas"], Path(tmp), backend) if tours else
                 dict(agents=0, groups=0, occupancyDelta=np.zeros_like(baseline).tolist()))
    crossings = sidewalk_comparison(read(joint_path/"pedestrians.json"), network, places, tours)
    family = "workplace-lunch"
    report = dict(versions=joint["versions"], joint=joint_id, workplaces=joint["workplaces"]["tract-workplaces"],
                  source=SOURCE, evidence=groups, donorCount=len(donors), referenceRate=rate,
                  eligibleMeals=len(population), existing=recorded, target=target, attendance=len(tours),
                  walkMetresPerMinute=WALK_SPEED, venues=len({row[3] for row in tours}), crossings=crossings, **clock)

    def build(out):
        write_json(out/"report.json",report)
        write_json(out/"tours.json",tours)

    version = package(root,family,build)
    pointer(root/family/(joint_id+".json"),{"version": version})
    print(version, len(tours), [(site["name"],sum(site["added"])) for site in crossings],flush=True)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path)
    parser.add_argument("joint")
    parser.add_argument("evidence",type=Path,help="city.vancouver.atlas-diaries --shopping-comparison export")
    parser.add_argument("--root",type=Path,default=Path("public/data/vancouver"))
    parser.add_argument("--backend",default="jvm")
    args=parser.parse_args()
    publish(args.root,args.archive,args.joint,args.evidence,args.backend)
