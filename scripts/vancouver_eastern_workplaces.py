"""Fit North Shore jobs in Burnaby and New Westminster to dated commute constraints."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
from pathlib import Path
import subprocess
import tempfile

import duckdb
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from scripts.vancouver_atlas import largest_remainder, write_json
from scripts.vancouver_basemap import basemap
from scripts.vancouver_census_geography import area_membership
from scripts.vancouver_cityday import SPEED, xy
from scripts.vancouver_downtown_workplaces import CORE, SUPPORTED, TIMETABLE, Routes
from scripts.vancouver_region import FRAME, package, read, rows
from scripts.vancouver_regional_workplaces import CENSUS, SOURCE, publish_companions, variant_day
from scripts.vancouver_workplace_tracts import census_counts

DESTINATIONS = {"5915025": "Burnaby", "5915029": "New Westminster"}
CAMPUS_ROW = "Metro Vancouver A (RDA), B.C."
EASTERN_FRAME = (FRAME[0], 49.170, -122.860, FRAME[3])
SEED = 89221


def census_targets(csv_path):
    origins = {"2021A0005"+csd: j for j, (csd, _) in enumerate(CENSUS) if j}
    east = {name+" (CY), B.C.": name for name in DESTINATIONS.values()}
    local = {name for _, name in CENSUS} | {CAMPUS_ROW}
    flows = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        header = next(reader)
        geo, place, year = map(header.index, ("DGUID", "Place of work", "REF_DATE"))
        total = header.index("Gender (3):Total - Gender[1]")
        for row in reader:
            if len(row) <= geo:
                continue
            home = origins.get(row[geo])
            job = row[place]
            if home is None or job not in east and job not in local:
                continue
            key = home, job
            if row[year] != "2021" or row[total+1] or key in flows:
                raise ValueError("Missing or repeated Census workplace flow")
            flows[key] = int(row[total])
    if len(flows) != len(origins)*(len(east)+len(local)):
        raise ValueError("Incomplete regional Census workplace rows")
    return {i: (sum(flows[i,k] for k in local), *(flows[i,k] for k in east)) for i in origins.values()}


def inventory(raw, work, data, areas):
    # The archived OSM extract covers locations outside the resident roster.
    anchors = {}
    for lon, lat, kind, name, weight in rows(work/"places.jsonl"):
        if kind != "job" or not (EASTERN_FRAME[0] <= lon <= EASTERN_FRAME[2]
                                 and EASTERN_FRAME[1] <= lat <= EASTERN_FRAME[3]):
            continue
        key = tuple(xy(lon, lat))
        if key not in anchors or bool(name) and not anchors[key][2]:
            anchors[key] = (lon, lat, name, weight)
    positions = pd.DataFrame(list(anchors.values()), columns=["lon","lat","name","weight"])
    membership = area_membership(raw, set(DESTINATIONS))
    da_rows = pd.DataFrame(list(membership.items()), columns=["da","csd"])
    with duckdb.connect() as db:
        db.execute("load spatial")
        db.register("points", positions)
        db.register("members", da_rows)
        db.execute("""create temp table bounds as select csd,
            st_transform(st_union_agg(st_makevalid(s.geom)),'EPSG:3347','EPSG:4326',always_xy:=true) g
            from st_read(?) s join members m on s.DAUID=m.da group by csd""", [str(raw/"lda_000b21a_e.shp")])
        located = db.execute("""select csd,lon,lat,name,weight,min(t.DGUID) code
            from points p join bounds b on st_covers(b.g,st_point(lon,lat))
            join st_read(?) t on st_covers(st_makevalid(t.geom),st_point(lon,lat))
            group by all order by csd,lon,lat""", [str(data/"vancouver-tracts-2021.geojson")]).fetchall()
    observed = census_counts(data/"98100498-eng.zip")
    mass = Counter()
    for _,_,_,_,weight,ct in located:
        if observed.get(ct, 0):
            mass[ct] += weight
    by_city, records = defaultdict(list), []
    index = {name: len(areas)+i for i,name in enumerate(DESTINATIONS.values())}
    for csd,lon,lat,name,weight,ct in located:
        if not mass[ct]:
            continue
        city = DESTINATIONS[csd]
        by_city[city].append([len(records), observed[ct]*weight/mass[ct], ct])
        records.append([*xy(lon,lat), index[city], name or "Mapped workplace"])
    if set(by_city) != set(DESTINATIONS.values()):
        raise ValueError("No census-weighted workplaces were found in a requested destination")
    return records, by_city


def candidates_for(reference, options, rng):
    sites, mass, tree = options
    limit = min(10, len(sites))
    _, nearest = tree.query(reference, k=limit)
    drawn = rng.choice(len(sites), size=min(12, len(sites)), replace=False, p=mass)
    # Nearby sites give short diaries a feasible option. Sampled census
    # employment anchors spread the assignments over the employment geography.
    return sites[list(dict.fromkeys([*drawn, *np.atleast_1d(nearest)]))]


def assign(workers, municipalities, areas, places, by_city, controls, routes):
    local = set(municipalities[1:]) | {"UBC Vancouver campus"}

    def origin_group(p):
        area = areas[places[p][2]]
        if area in CORE:
            return "Downtown or West End"
        return area if area in local else "Rest of Vancouver"

    by_home = defaultdict(list)
    before = defaultdict(Counter)
    for w in workers:
        home = w[2]
        if home > 0:
            by_home[home].append(w)
            before[home][origin_group(w[4])] += 1
    options = {}
    for city, rows in by_city.items():
        sites, weights, _ = zip(*rows, strict=True)
        sites = np.array(sites)
        mass = np.array(weights)/sum(weights)
        options[city] = sites, mass, cKDTree(routes.points[sites])
    rng = np.random.default_rng(SEED)
    moves, examples, evidence = defaultdict(list), {}, []
    used = set()
    modes = Counter()
    for home, name in enumerate(municipalities[1:], 1):
        n = sum(before[home].values())
        stock = controls[home]
        targets = largest_remainder(np.asarray(stock)/sum(stock), n).tolist()
        groups = sorted(before[home])
        weights = np.array([before[home][g] for g in groups])/n
        quota = dict(zip(groups, largest_remainder(weights, sum(targets[1:])), strict=True))
        after = before[home].copy()
        order = rng.permutation(len(by_home[home]))
        for dest in sorted(zip(DESTINATIONS.values(), targets[1:], strict=True), key=lambda row: row[1]):
            city, target = dest
            achieved = 0
            for i in order:
                if achieved == target:
                    break
                w = by_home[home][i]
                d, person, _, _, old, slots, legs, _ = w
                group = origin_group(old)
                if (d,person) in used or not quota[group] or not legs or any(
                        a<0 or t<=0 or mode not in SUPPORTED for a,t,mode,*_ in legs):
                    continue
                anchor = min(legs, key=lambda leg: leg[1]*SPEED[leg[2]])[0]
                for m in candidates_for(routes.points[anchor], options[city], rng):
                    if not routes.feasible(w, int(m)):
                        continue
                    quota[group] -= 1
                    after[group] -= 1
                    achieved += 1
                    used.add((d,person))
                    moves[d].append([person,slots,old,int(m)])
                    a,t,mode,start,_ = next((leg for leg in legs if not leg[4]), legs[0])
                    modes[city,mode] += 1
                    score = (mode not in {"car-driver","car-passenger"}, abs(start-480))
                    if city not in examples or score < examples[city][0]:
                        examples[city] = score, [d,person,start,t,int(m)]
                    break
            after[city] = achieved
        if sum(after.values()) != n:
            raise ValueError("An eastern workplace move changed the resident total")
        evidence.append(dict(home=name, total=n, observed=dict(zip(["Covered destinations",*DESTINATIONS.values()],stock)),
                             target=dict(zip(DESTINATIONS.values(),targets[1:])), before=dict(before[home]), after=dict(after)))
        print(name, {c: after[c] for c in DESTINATIONS.values()}, flush=True)
    return moves, evidence, {city: value[1] for city,value in examples.items()}, [
        [city,mode,count] for (city,mode),count in sorted(modes.items())]


def publish(root, archive, inputs, data, parent_id, timetable):
    parent = read(root/"regional-workplaces"/parent_id/"report.json")
    versions = dict(parent["versions"], day=parent["day"])
    base = root/"cityday"/versions["day"]
    atlas = root/"atlas"/versions["atlas"]
    day, places = read(base/"day.json"), read(base/"places.json")
    raw, work = archive/"data/raw", inputs/"work"
    census_file = raw/"statcan/commuting/98100459.csv"
    controls = census_targets(census_file)
    sites, groups = inventory(raw/"statcan", work, data, day["areas"])
    count = len(places)
    for entries in groups.values():
        for entry in entries:
            entry[0] += count
    places.extend(sites)
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        extracted = Path(tmp)/"workers.json"
        subprocess.run(["clojure","-J-Xmx2g","-M","-m","city.vancouver.regional-workplaces",
                        atlas,base,extracted,"swaps"], check=True)
        workers = read(extracted)
    north = [w for w in workers["workers"] if w[2] > 0]
    eligible = [w for w in north if w[6] and all(0<=a and t>0 and m in SUPPORTED for a,t,m,*_ in w[6])]
    print(f"Checking {len(eligible):,} North Shore workers against {len(sites):,} mapped eastern workplaces.",flush=True)
    routes = Routes(root,versions,places,eligible,timetable,destination_sites=range(count,len(places)))
    moves, allocations, examples, modes = assign(north, workers["municipalities"], day["areas"], places, groups, controls, routes)
    moved = sum(map(len,moves.values()))
    if not moved:
        raise ValueError("No eastern commute fits the original diary")
    # The wider land and road background is separate from the resident atlas.
    background = basemap(raw, EASTERN_FRAME, rows(work/"roads.jsonl"))

    def build(out):
        variant_day(base,day,places,moves,atlas,out,destinations=tuple(DESTINATIONS.values()))
        write_json(out/"basemap.json",background)

    release_day = package(root,"cityday",build,versions["day"])
    def digest(file):
        with file.open("rb") as stream:
            return hashlib.file_digest(stream,"sha256").hexdigest()
    report = dict(versions=versions, day=release_day, extendedMap=True, incomingDay=parent["incomingDay"],
                  originWorkplaceRun=parent_id, basisLabels={"original":"Downtown workplace fit","census":"Eastern workplaces"},
                  easternAllocations=allocations, easternExamples={k:[day["das"][v[0]],*v[1:]] for k,v in examples.items()},
                  easternModes=modes, moved=moved, source=SOURCE, sourceDigest=digest(census_file),
                  venues={city:len(entries) for city,entries in groups.items()},
                  mappedTracts={city:len({entry[2] for entry in entries}) for city,entries in groups.items()},
                  timetable=timetable, serviceDate=routes.transit_date, speedDigest=routes.routing["profileDigest"])
    release = package(root,"regional-workplaces",lambda out: write_json(out/"report.json",report))
    print(release,release_day,moved,modes,flush=True)
    return report, release


def publish_replay(root, archive, inputs, report, release, *, survey_2025=None):
    from scripts.vancouver_commute_schedule import TABLE as COMMUTE_TABLE, publish as commute_schedule
    from scripts.vancouver_discretionary_outings import publish_outings, raster_clock
    from scripts.vancouver_north_shore_demand import SURVEY_ARCHIVE, publish as publish_demand
    from scripts.vancouver_short_walks import publish as publish_walks

    base = report["versions"]
    versions = dict(base, day=report["day"])
    atlas, day, streets = (versions[k] for k in ("atlas", "day", "streets"))
    publish_walks(root, atlas, day, streets)
    publish_demand(root, atlas, [day], SURVEY_ARCHIVE, streets, survey_2025)
    outing_root = root/"discretionary-outings"
    parent_pointer = outing_root/(atlas+"_"+base["day"]+".json")
    if parent_pointer.exists():
        parent_id = read(parent_pointer)["version"]
        parent = read(outing_root/parent_id/"report.json")
        tours = read(outing_root/parent_id/"tours.json")
        day_dir = root/"cityday"/day
        current = read(day_dir/"day.json")
        places = read(day_dir/"places.json")
        base_dir = root/"cityday"/base["day"]
        original = read(base_dir/"day.json")
        original_places = read(base_dir/"places.json")
        if places[:len(original_places)] != original_places or any(
                current[k] != original[k] for k in ("templates","das","population","travelBouts")):
            raise ValueError("The eastern replay cannot retain the original outing itineraries")
        path = root/"short-walks"/(day+"_"+streets+".json")
        walks = read(path)
        intervals = {(d,i):(start,start+there+dwell+back)
                     for d,i,_,_,_,_,start,there,dwell,back,*_ in tours}
        for d,i,start,n,*_ in walks["walks"]:
            bounds = intervals.get((d,i))
            if bounds and start < bounds[1] and start+n > bounds[0]:
                raise ValueError("A reconstructed street walk now overlaps an existing outing")
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            updated = raster_clock(tours, places, current["occupancy"], current["areas"], Path(tmp), "jvm")
        demand = read(root/"north-shore-demand"/(atlas+"_"+day+".json"))["version"]
        with path.open("rb") as stream:
            walk_digest = hashlib.file_digest(stream,"sha256").hexdigest()
        parent.update(updated, versions=versions, demand=demand, inheritedOutings=parent_id, reservedWalksDigest=walk_digest)
        publish_outings(root,parent,tours)
    commute_schedule(root, COMMUTE_TABLE, [day])
    publish_companions(root,archive,inputs,report,release,timed_roads=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region",type=Path,default=Path("public/data/vancouver/region"))
    parser.add_argument("--inputs",type=Path,default=Path("data/region"))
    parser.add_argument("--data",type=Path,default=Path("data/mobility"))
    parser.add_argument("--archive",type=Path,default=Path("../Simulations/city"))
    parser.add_argument("--parent",default="3c70c4228343c1492290")
    parser.add_argument("--timetable",default=TIMETABLE)
    parser.add_argument("--resume",help="Publish replay companions for an existing eastern report")
    parser.add_argument("--no-companions",action="store_true",help="Build only the paired weekday")
    args = parser.parse_args()
    if args.resume:
        release = args.resume
        result = read(args.region/"regional-workplaces"/release/"report.json")
    else:
        result, release = publish(args.region,args.archive,args.inputs,args.data,args.parent,args.timetable)
    if not args.no_companions:
        publish_replay(args.region,args.archive,args.inputs,result,release)
