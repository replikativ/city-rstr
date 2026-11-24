"""Place intact Vancouver households using 2021 census dissemination block totals."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import shutil
from zipfile import ZipFile

import duckdb
import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp

from scripts.vancouver_atlas import write_json
from scripts.vancouver_census_geography import records
from scripts.vancouver_cityday import ORIGIN, SCALE
from scripts.vancouver_region import package, read, rows


RESIDENTIAL = {"apartments", "bungalow", "cabin", "detached", "ger", "house", "houseboat", "residential",
               "semidetached_house", "static_caravan", "terrace"}


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def controls(file, areas):
    census = defaultdict(dict)
    for row in records(file, "2021_92-151_X.csv", "latin-1"):
        da = row["DAUID_ADIDU"]
        if da in areas:
            block = row["DBUID_IDIDU"]
            if block in census[da]:
                raise ValueError(f"Repeated census block {block}")
            census[da][block] = (int(row["DBURDWELL2021_IDRHLOG2021"]), int(row["DBPOP2021_IDPOP2021"]))
    if set(census) != areas:
        raise ValueError("Block counts do not cover the weekday census areas")
    return census


def plan_blocks(stock, housing, residents):
    """Exact occupied-dwelling counts and the smallest attainable resident error."""
    housing = np.asarray(housing)
    residents = np.asarray(residents)
    sizes, counts = np.array(list(sorted(stock.items()))).T
    private = sizes > 0
    occupants = np.maximum(sizes, 1)
    if housing.sum() != counts[private].sum() or residents.sum() != counts @ occupants:
        raise ValueError("Block totals do not reconcile to the synthetic census area")
    if len(housing) == 1:
        return sizes, counts.reshape(1, -1)

    blocks, groups = len(housing), len(sizes)
    n = blocks * groups
    # x[block, group] is an integer. Excess and missing people are nonnegative.
    stock_matrix = np.tile(np.eye(groups), (1, blocks))
    home_matrix = np.kron(np.eye(blocks), private)
    pop_matrix = np.column_stack((np.kron(np.eye(blocks), occupants), np.eye(blocks), -np.eye(blocks)))
    totals = np.concatenate((counts, housing, residents))
    held = np.column_stack((np.vstack((stock_matrix, home_matrix)), np.zeros((groups + blocks, 2*blocks))))
    marginal_rows = np.vstack((held, pop_matrix))

    # Among equally exact matches prefer household-size mixes close to the DA's mix.
    private_share = housing / max(1, housing.sum())
    other_share = residents / residents.sum()
    expected = (np.where(private, private_share[:, None], other_share[:, None]) * counts).ravel()
    balance = np.column_stack((np.eye(n), np.zeros((n, 2*blocks)), -np.eye(n)))
    balance_negative = balance.copy()
    balance_negative[:, :n] *= -1
    exact = LinearConstraint(np.column_stack((marginal_rows, np.zeros((len(totals), n)))), totals, totals)
    deviations = LinearConstraint(np.vstack((balance, balance_negative)), -np.inf, np.r_[expected, -expected])
    cost = np.r_[np.zeros(n), np.full(2*blocks, 2*counts.sum()+1), np.ones(n)]
    may_place = (residents > 0) | (housing > 0)
    upper = np.r_[np.where(may_place[:, None], counts, 0).ravel(), np.full(2*blocks+n, np.inf)]
    solved = milp(cost, integrality=np.r_[np.ones(n), np.zeros(2*blocks+n)], bounds=Bounds(0, upper),
                  constraints=[exact, deviations], options={"mip_rel_gap": 0})
    if not solved.success:
        raise ValueError(f"Could not reconcile block households: {solved.message}")
    allocation = np.rint(solved.x[:n]).astype(int).reshape(blocks, groups)
    if not (allocation.sum(axis=0) == counts).all() or not (allocation[:, private].sum(axis=1) == housing).all():
        raise ValueError("Household allocation violates the census controls")
    return sizes, allocation


def residential_footprints(path):
    for way in rows(path):
        tags = way.get("tags", {})
        if tags.get("building") not in RESIDENTIAL and tags.get("building:use") != "residential":
            continue
        ring = [(p["lon"], p["lat"]) for p in way["geometry"]]
        if len(ring) < 4 or ring[0] != ring[-1]:
            continue
        try:
            levels = max(1, float(tags.get("building:levels", "1")))
        except ValueError:
            levels = 1
        yield way["id"], min(90, levels), json.dumps({"type": "Polygon", "coordinates": [ring]})


def prepare_geometry(db, archive, census, buildings):
    keys = [(b, da) for da, blocks in census.items() for b in blocks]
    db.register("block_keys", pd.DataFrame(keys, columns=["block", "da"]))
    with ZipFile(archive) as zipped:
        member, = (name for name in zipped.namelist() if name.lower().endswith(".shp"))
    shp = f"/vsizip/{archive.resolve()}/{member}"
    db.execute("""create table block_shapes as
                 select block, da, ST_Transform(ST_MakeValid(geom), 'EPSG:3347', 'EPSG:4326', true) g
                 from ST_Read(?) join block_keys on DBUID=block order by block""", [shp])
    shapes = {b: (json.loads(geo), (x, y)) for b, geo, x, y in db.execute("""
        select block, ST_AsGeoJSON(g), ST_X(ST_PointOnSurface(g)), ST_Y(ST_PointOnSurface(g))
        from block_shapes where not ST_IsEmpty(g)""").fetchall()}
    missing = [b for blocks in census.values() for b, (h, p) in blocks.items() if (h or p) and b not in shapes]
    if missing:
        raise ValueError(f"Occupied census blocks lack boundaries: {missing[:12]}")
    footprints = pd.DataFrame(residential_footprints(buildings), columns=["id", "levels", "wkt_json"])
    db.register("footprints", footprints)
    prepared = db.execute("""with polygons as (
        select id, levels, ST_MakeValid(ST_GeomFromGeoJSON(wkt_json)) g from footprints
      ), points as (
        select id, ST_PointOnSurface(g) p,
               ST_Area(g) * 72600 * 111195 * levels as weight from polygons
        where not ST_IsEmpty(g)
      ), rounded as (
        select id, round((ST_X(p)+123.1)*72600)::integer x,
               round((49.26-ST_Y(p))*111195)::integer y, weight from points where weight>0
      )
      select block, x, y, weight from rounded join block_shapes
        on ST_Covers(g, ST_Point(x/72600.0-123.1,49.26-y/111195.0))
      qualify row_number() over (partition by id order by block)=1
      order by block, x, y, id""").fetchall()
    candidates = defaultdict(Counter)
    for b, x, y, weight in prepared:
        candidates[b][x, y] = max(candidates[b][x, y], weight)
    return shapes, candidates


def household_groups(people, households):
    occupied = np.zeros(people, dtype=bool)
    groups = defaultdict(list)
    for start, size, _ in households:
        if start < 0 or size <= 0 or start + size > people or occupied[start:start+size].any():
            raise ValueError("Overlapping or incomplete synthetic household roster")
        groups[size].append(start)
        occupied[start:start+size] = True
    groups[0] = np.flatnonzero(~occupied).tolist()
    return {size: members for size, members in groups.items() if members}


def point_to_block(db, places, home_areas):
    points = [(da, i, places[i][0], places[i][1]) for da, ids in home_areas.items() for i in sorted(ids)]
    db.register("home_points", pd.DataFrame(points, columns=["da", "id", "x", "y"]))
    return {(da, i): block for da, i, block in db.execute("""select p.da, id, block from home_points p
       join block_shapes b on p.da=b.da and ST_Covers(g,ST_Point(x/72600.0-123.1,49.26-y/111195.0))
       qualify row_number() over (partition by p.da,id order by block)=1""").fetchall()}


def local_point(lonlat):
    return tuple(round((value - offset) * scale) for value, offset, scale in zip(lonlat, ORIGIN, SCALE, strict=True))


def place_area(da, baseline, groups, blocks, shapes, buildings, old_by_block, places, area, home_ids):
    rng = np.random.default_rng([2021, int(da), 61])
    active = sorted(b for b, pair in blocks.items() if any(pair))
    housing, population = zip(*(blocks[b] for b in active), strict=True)
    try:
        sizes, allocation = plan_blocks({size: len(members) for size, members in groups.items()}, housing, population)
    except ValueError as error:
        raise ValueError(f"{da}: {error}") from error
    for members in groups.values():
        rng.shuffle(members)
    locations = [None] * len(baseline)
    placed = Counter()
    totals = {}
    for block, census, allocation_row in zip(active, population, allocation, strict=True):
        _, centre = shapes[block]
        reference = local_point(centre)
        candidates = buildings.get(block)
        prior_points = sorted(old_by_block[block])
        if candidates:
            points, weights = zip(*sorted(candidates.items()), strict=True)
            weights = np.array(weights) / sum(weights)
            basis = "Residential footprint"
        else:
            points = prior_points or [reference]
            weights = None
            basis = "Address point" if prior_points else "Census-block reference point"
        home_total = 0
        residents = 0
        for size, n in zip(sizes.tolist(), allocation_row.tolist(), strict=True):
            if not n:
                continue
            length = max(1, size)
            starts = [groups[size].pop() for _ in range(n)]
            name = basis if size else "Census-block reference point"
            choices = rng.choice(len(points), n, p=weights) if size else [0] * n
            for start, j in zip(starts, choices, strict=True):
                x, y = points[j] if size else reference
                coord = (x, y, area, name)
                if coord not in home_ids:
                    home_ids[coord] = len(places)
                    places.append(list(coord))
                locations[start:start+length] = [home_ids[coord]] * length
            home_total += n if size else 0
            residents += n * length
            placed[name] += n if size else 0
        totals[block] = [home_total, residents]
    if any(loc is None for loc in locations) or any(groups.values()):
        raise ValueError(f"Incomplete home placement in {da}")
    return locations, totals, placed


def sample_by_area(day):
    indexes = defaultdict(dict)
    for row, (area, person, *_) in enumerate(day["sample"]):
        da = day["das"][area]
        if person in indexes[da]:
            raise ValueError("A resident appears twice in the animation sample")
        indexes[da][person] = row
    return indexes


def build(root, atlas_id, baseline_id, census, sources, db, shapes, buildings, output):
    baseline_dir = root/"cityday"/baseline_id
    atlas_dir = root/"atlas"/atlas_id
    baseline = read(baseline_dir/"day.json")
    atlas = read(atlas_dir/"atlas.json")
    places = read(baseline_dir/"places.json")
    copy = baseline.copy()
    home_ids = {}
    areas = {da: baseline["areas"].index(area) for area, details in atlas["areas"].items() for da in details["das"]}
    old_by_area = {da: set(read(baseline_dir/(da+".json"))["home"]) for da in baseline["das"]}
    old_points = point_to_block(db, places, old_by_area)
    sample_by_da = sample_by_area(baseline)
    home_slots = [[i for i, name in enumerate(tpl["slots"]) if name == "home"] for tpl in baseline["templates"]]
    sample = baseline["sample"].copy()
    summary = Counter()
    placement = Counter()
    examples = []
    sampled = 0
    for da in baseline["das"]:
        previous = read(baseline_dir/(da+".json"))
        roster = read(atlas_dir/(da+".json"))
        households = roster["homes"]
        people = roster["people"]
        homes = previous["home"]
        groups = household_groups(len(people), households)
        blocks = census[da]
        if sum(h for h, _ in blocks.values()) != len(households) or sum(p for _, p in blocks.values()) != len(people):
            raise ValueError(f"Census controls and the existing roster disagree in {da}")
        prior = defaultdict(list)
        for i in sorted(old_by_area[da]):
            block = old_points.get((da, i))
            if block:
                prior[block].append(tuple(places[i][:2]))
        old_households = Counter(old_points.get((da, homes[start])) for start, *_ in households)
        old_residents = Counter(old_points.get((da, i)) for i in homes)
        if people:
            assigned, counts, basis = place_area(da, homes, groups, blocks, shapes, buildings, prior, places, areas[da], home_ids)
        else:
            assigned, counts, basis = [], {}, Counter()
        placement.update(basis)
        plans = previous["plans"]
        for i, person in enumerate(people):
            for slot in home_slots[person[7]]:
                if plans[i][slot] != homes[i] or places[homes[i]][2] != areas[da]:
                    raise ValueError(f"Existing home and diary disagree in {da}")
                plans[i][slot] = assigned[i]
            if i in sample_by_da[da]:
                j = sample_by_da[da][i]
                if sample[j][2] != person[7]:
                    raise ValueError(f"Animation sample and resident diary disagree in {da}")
                sample[j] = [*sample[j][:3], plans[i], sample[j][4]]
                sampled += 1
        write_json(output/(da+".json"), {**previous, "home": assigned})
        area_error = sum(abs(h - old_households[b]) for b, (h, _) in blocks.items()) + old_households[None]
        if area_error:
            examples.append((area_error, da))
        features = []
        for b, (h, p) in sorted(blocks.items()):
            new_h, new_p = counts.get(b, [0, 0])
            before_h, before_p = old_households[b], old_residents[b]
            if b in shapes:
                features.append({"type": "Feature", "geometry": shapes[b][0], "properties": dict(
                    block=b, dwellings=h, population=p, beforeHomes=before_h, beforePeople=before_p,
                    homes=new_h, people=new_p)})
            summary.update(blocks=1, occupiedBlocks=int(h>0), population=p, households=h,
                           priorHomeError=abs(h-before_h), homeError=abs(h-new_h),
                           priorPopulationError=abs(p-before_p), populationError=abs(p-new_p),
                           exactPopulationBlocks=int(p == new_p), homesOnZeroDwellingBlocks=before_h if not h else 0)
        summary.update(priorUnmatchedHomes=old_households[None], priorUnmatchedResidents=old_residents[None])
        write_json(output/("homes-"+da+".json"), {"type": "FeatureCollection", "features": features})
    if (summary["population"] != baseline["population"] or summary["homeError"] or
        sum(placement.values()) != summary["households"] or sampled != len(sample)):
        raise ValueError("Household placement breaks a citywide conservation invariant")
    summary["animationSample"] = sampled
    copy.update(sample=sample, homePlacement={"baselineDay": baseline_id, "kind": "census-blocks"})
    write_json(output/"day.json", copy)
    write_json(output/"places.json", places)
    write_json(output/"home-placement.json", dict(atlas=atlas_id, baselineDay=baseline_id, sources=sources,
               summary=dict(summary), placement=dict(placement), example=max(examples, default=(0, baseline["das"][0]))[1]))
    shutil.copyfile(baseline_dir/"mobility.json", output/"mobility.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--geography", type=Path, default=Path("data/mobility/2021_92-151_X.zip"))
    parser.add_argument("--boundaries", type=Path, default=Path("data/mobility/ldb_000b21a_e.zip"))
    parser.add_argument("--buildings", type=Path, default=Path("data/region/work/buildings.jsonl"))
    parser.add_argument("--scope", choices=("city", "region", "both"), default="both")
    parser.add_argument("--joint", help="Build the home comparison for a published municipal combined weekday")
    args = parser.parse_args()
    if args.joint and args.scope == "region":
        parser.error("--joint selects a municipal weekday")
    parents = []
    selected = set()
    for regional in (False, True):
        if args.joint and regional:
            continue
        if args.scope != "both" and regional != (args.scope == "region"):
            continue
        root = args.data/"region" if regional else args.data
        pointer = (read(root/"joint-weekday"/args.joint/"report.json")["versions"] if args.joint else
                   read(root/("current.json" if regional else "cityday/current.json")))
        atlas_id, day = pointer["atlas"], pointer.get("day", pointer.get("version"))
        areas = set(read(root/"atlas"/atlas_id/"atlas.json")["das"])
        parents.append((root, atlas_id, day, areas))
        selected.update(areas)
    census = controls(args.geography, selected)
    sources = {"geographicAttributes": sha256(args.geography), "blockBoundaries": sha256(args.boundaries),
               "buildingFootprints": sha256(args.buildings)}
    with duckdb.connect() as db:
        db.execute("load spatial")
        shapes, buildings = prepare_geometry(db, args.boundaries, census, args.buildings)
        for root, atlas_id, day, areas in parents:
            subset = {da: census[da] for da in sorted(areas)}
            release = package(root, "cityday", lambda output: build(root, atlas_id, day, subset, sources,
                              db, shapes, buildings, output), atlas_id)
            print(root, release, read(root/"cityday"/release/"home-placement.json")["summary"], flush=True)


if __name__ == "__main__":
    main()
