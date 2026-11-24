"""Place city residents' usual workplaces in census destination municipalities."""
import argparse
import csv
import json
import math
import subprocess
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.sparse.csgraph import dijkstra

from scripts.vancouver_atlas import donor_person, write_json
from scripts.vancouver_cityday import SPEED
from scripts.vancouver_downtown import MODE_INDEX, MODES
from scripts.vancouver_inbound import CITY, MODE, WORK, read
from scripts.vancouver_census_geography import DA, profile_cells
from scripts.vancouver_population_check import BANDS, LABELS
from scripts.vancouver_region import package
from scripts.vancouver_streets import access_graph
from scripts.vancouver_cycling import FORWARD, REVERSE, publish as publish_cycling

SEED = 20261123
AGE_ROWS = {"Total - Age": "All ages", "15 to 24 years": "15–24", "25 to 34 years": "25–34",
            "35 to 44 years": "35–44", "45 to 54 years": "45–54", "55 to 64 years": "55–64",
            "65 years and over": "65+"}


def observed_modes(path):
    # Preserve published categories. This table combines walking and cycling.
    names = {"Driver (only worker in vehicle)": "Car driver", "Driver with 1 or more workers": "Car driver",
             "Passenger (only worker in vehicle)": "Car passenger", "Passenger with 2 or more workers": "Car passenger",
             "Public transit": "Public transit", "Active transportation": "Walking or bicycle", "Other method": "Other"}
    result, seen = defaultdict(Counter), set()
    with zipfile.ZipFile(path) as z, z.open("98100462.csv") as f:
        header = next(csv.reader([next(f).decode("utf-8-sig")]))
        columns = [i for i, name in enumerate(header) if name.startswith("Commuting destination (5):Commute to a different")]
        if len(columns) != 3:
            raise ValueError("Unexpected Census commuting destination columns")
        for line in f:
            if b",2021A00055915022," not in line or b",Total - Gender,Count," not in line:
                continue
            row = next(csv.reader([line.decode()]))
            name = row[header.index("Main mode of commuting (11A)")]
            age = AGE_ROWS.get(row[header.index("Age (15A)")])
            if age and name in names:
                if (age, name) in seen or any(row[i+1].strip() for i in columns):
                    raise ValueError("Suppressed or repeated Census mode control")
                result[age][names[name]] += sum(int(row[i]) for i in columns)
                seen.add((age, name))
            if len(seen) == len(AGE_ROWS)*len(names):
                break
    if len(seen) != len(AGE_ROWS)*len(names):
        raise ValueError("Missing Vancouver mode observations")
    return result


def donor_index(path, field="POWST"):
    homes = defaultdict(list)
    fields = (field,) if isinstance(field, str) else tuple(field)
    with path.open() as f:
        for row in csv.DictReader(f):
            if row["CMA"] == "933":
                profile = tuple(int(row[name]) for name in fields)
                homes[row["HH_ID"]].append((int(row["PP_ID"]), int(row["TENUR"]), float(row["WEIGHT"]),
                                            tuple(donor_person(row)), profile[0] if isinstance(field, str) else profile))
    index = defaultdict(Counter)
    for home in homes.values():
        home.sort()
        key = home[0][1], tuple(row[3] for row in home)
        index[key][tuple(row[4] for row in home)] += home[0][2]
    return index


def household_profiles(roster, index, rng):
    """Draw the additional census field jointly for every member of an intact donor household."""
    for start, size, tenure in roster["homes"]:
        people = roster["people"][start:start+size]
        key = tenure, tuple(tuple(person[:7]) for person in people)
        if key not in index:
            raise ValueError("Atlas household has no matching PUMF roster")
        profiles = index[key]
        if len(profiles) == 1:
            statuses = next(iter(profiles))
        else:
            weights = np.array(list(profiles.values()))
            statuses = list(profiles)[rng.choice(len(weights), p=weights/weights.sum())]
        yield start, people, statuses, len(profiles) > 1


def eligible(roster, index, rng):
    candidates, ambiguous = [], 0
    for start, people, statuses, multiple in household_profiles(roster, index, rng):
        ambiguous += multiple
        for i, (person, status) in enumerate(zip(people, statuses, strict=True)):
            if person[2] == 1 and person[1] in (1, 2) and 4 <= status <= 7:
                candidates.append((start+i, person[1], status))
    return candidates, ambiguous


def controls(archive, das):
    derived = archive / "data/derived"
    with (derived / "vancouver_commuting_flows.jsonl").open() as f:
        rows = [r for r in map(json.loads, f) if r["DGUID"][-7:] == CITY and r["total"] > 0]
    inside, = [r["total"] for r in rows if r["work"] == WORK]
    outside = sorted((r for r in rows if r["work"] != WORK), key=lambda r: (-r["total"], r["work"]))
    if len({r["work"] for r in outside}) != len(outside):
        raise ValueError("Repeated workplace destination")
    codes = {2600, 2601, 2602} | {k for (k,) in BANDS["commute"]}
    margins = profile_cells(archive / "data/raw/statcan", {DA + d for d in das}, codes, columns=(11, 13, 15))
    return inside, outside, margins


def prepare(archive, atlas_dir, day_dir, mode_table):
    """Translate census source formats and join donor workplace status to existing household IDs."""
    das = read(day_dir/"day.json")["das"]
    inside, destinations, margins = controls(archive, das)
    index = donor_index(archive/"data/raw/statcan/pumf/data_donnees_2021_hier_v2.csv")
    candidates, local, mode_profile, ambiguous = [], [], [], 0
    for da in das:
        people, n = eligible(read(atlas_dir/(da+".json")), index, np.random.default_rng([SEED, int(da)]))
        candidates.append(people)
        ambiguous += n
        observed = []
        for column in (2, 1):  # Profile columns are total, men+, women+. PUMF code 1 is women+.
            cells = [margins[DA + da][k][column] for k in (2600, 2601, 2602)]
            observed.append(sum(cells) if all(c is not None for c in cells) else None)
        local.append(observed)
        cells = [margins[DA + da][k][0] for (k,) in BANDS["commute"]]
        mode_profile.append(cells if all(c is not None for c in cells) else None)
    observations = observed_modes(mode_table)
    return dict(seed=SEED, inside=inside, destinations=destinations, candidates=candidates, local=local,
                ambiguous=ambiguous, modes=MODES, modeIndex={**MODE_INDEX, "other": len(MODES)-1},
                censusMode={str(k): MODES[v] for k,v in MODE.items()}, observed=observations["All ages"],
                observedByAge=observations, modeProfile=mode_profile, activeSpeeds={"Walking": SPEED["walk"], "Bicycle": SPEED["bike"]},
                profileModes=["Other" if name == "Other method" else name for name in LABELS["commute"]])


def commute_pairs(atlas_dir, day_dir):
    """Largest available time window for each directed job/home pair across resident diaries."""
    day = read(day_dir/"day.json")
    legs = []
    for template in day["templates"]:
        slots = template["slots"]
        legs.append([(a, b, n, slots[a] == "job")
                     for _, n, mode, a, b in template["parts"]
                     if mode != "stop" and min(a,b) >= 0 and {slots[a], slots[b]} == {"home", "job"}])
    pairs = {}
    for da in day["das"]:
        plans = read(day_dir/(da+".json"))["plans"]
        for person, plan in zip(read(atlas_dir/(da+".json"))["people"], plans, strict=True):
            if person[6] not in MODE:
                continue
            for a, b, minutes, from_job in legs[person[-1]]:
                u, v = plan[a], plan[b]
                if min(u,v) >= 0 and u != v:
                    key = u, v, from_job
                    pairs[key] = max(minutes, pairs.get(key,0))
    return pairs


def route_distances(pairs, coords, network, speed, forward, reverse):
    """Search out from the job node. For journeys to work traverse the transposed directed graph."""
    graph, snap = access_graph(network, forward, reverse)
    directed = forward != reverse
    graphs = [graph, graph.transpose().tocsr() if directed else graph]
    nodes, offsets = snap(coords)
    by_node = defaultdict(list)
    for (u,v,from_job), minutes in pairs.items():
        budget = speed * minutes
        if math.dist(coords[u], coords[v]) <= budget:
            job, home = (u,v) if from_job else (v,u)
            by_node[nodes[job], directed and not from_job].append((u,v,nodes[home],budget))
    reached = {}
    for (node, transpose), group in by_node.items():
        dist = dijkstra(graphs[transpose], indices=node, limit=max(row[3] for row in group))
        for u,v,end,budget in group:
            metres = offsets[u] + dist[end] + offsets[v]
            if metres <= budget:
                reached[(u,v) if directed else tuple(sorted((u,v)))] = float(metres)
    return [[a, b, metres] for (a, b), metres in sorted(reached.items())]


def publish(archive, root, mode_table, backend, day=None):
    day = day or read(root/"cityday/current.json")
    atlas_dir, day_dir = root/"atlas"/day["atlas"], root/"cityday"/day["version"]
    with tempfile.TemporaryDirectory() as tmp:
        inputs = Path(tmp)/"controls.json"
        controls = prepare(archive, atlas_dir, day_dir, mode_table)
        street = read(root/"streets/current.json")["version"]
        cycling = publish_cycling(archive, root)
        pairs = commute_pairs(atlas_dir, day_dir)
        coords = [p[:2] for p in read(day_dir/"places.json")]
        controls.update(streets=street, cycling=cycling,
                        walkDistances=route_distances(pairs, coords, read(root/"streets"/street/"network.json"), SPEED["walk"], 1, 1),
                        bikeDistances=route_distances(pairs, coords, read(root/"cycling"/cycling/"network.json"), SPEED["bike"], FORWARD, REVERSE))
        write_json(inputs, controls)
        def run(out):
            subprocess.run(["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.outbound", str(inputs),
                            str(atlas_dir), str(day_dir), str(out), backend], check=True)
        version = package(root, "outbound", run)
    pointer = root/"outbound"/(day["atlas"]+"_"+day["version"]+".json")
    with tempfile.TemporaryDirectory(dir=pointer.parent) as tmp:
        staged = Path(tmp)/"pointer"
        write_json(staged, {"version": version})
        staged.replace(pointer)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--mode-table", type=Path, default=Path("data/mobility/98100462-eng.zip"))
    parser.add_argument("--backend", default="jvm")
    args = parser.parse_args()
    print(publish(args.archive, args.data, args.mode_table, args.backend))
