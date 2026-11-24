"""Household food budgets, walking access and competition for Vancouver storefronts."""
import argparse
import csv
import hashlib
import io
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlopen

import numpy as np
from scipy.sparse.csgraph import dijkstra

from scripts.vancouver_atlas import write_json
from scripts.vancouver_streets import walk_graph

DOWNLOAD = "https://www150.statcan.gc.ca/n1/tbl/csv/11100223-eng.zip"
SOURCE = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1110022301"
GUIDE = "https://www150.statcan.gc.ca/n1/pub/62f0026m/62f0026m2023001-eng.htm"
SURVEY = Path("data/economics/11100223-eng.zip")
QUINTILES = ["Lowest quintile", "Second quintile", "Third quintile", "Fourth quintile", "Highest quintile"]
LIMITS = [400, 800, 1200]
GROUPS = len(QUINTILES) + 1
BATCH = 64


def read(path):
    return json.loads(path.read_bytes())


def spending(source):
    criteria = {
        "REF_DATE": "2021",
        "GEO": "British Columbia",
        "Statistic": "Average expenditure per household",
        "UOM": "Dollars",
        "Household expenditures, summary-level categories": "Food purchased from stores",
    }
    with zipfile.ZipFile(source) as archive, archive.open("11100223.csv") as handle:
        rows = csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig"))
        values = {
            row["Before-tax household income quintile"]: int(row["VALUE"])
            for row in rows if row["VALUE"] and all(row[k] == v for k, v in criteria.items())
        }
    return [values[q] for q in QUINTILES + ["All quintiles"]]


def income_cutoffs(raw):
    # Disjoint 100% private-household income groups. ID 276 is the subtotal of 277–280.
    edges = [0, 5000, 10000, 15000, 20000, 25000, 30000, 35000, 40000, 45000,
             50000, 60000, 70000, 80000, 90000, 100000, 125000, 150000, 200000]
    ids = [*range(261, 276), *range(277, 281)]
    counts = {}
    profile = next((raw / "statcan").glob("*_data_BritishColumbia.csv"))
    with profile.open(encoding="cp1252") as handle:
        for row in csv.DictReader(handle):
            if row["DGUID"] == "2021A000259":
                k = int(row["CHARACTERISTIC_ID"])
                if k in ids:
                    counts[k] = int(row["C1_COUNT_TOTAL"])
                if len(counts) == len(ids):
                    break
    mass = np.array([counts[k] for k in ids])
    ends = np.cumsum(mass)
    cutoffs = []
    for target in np.arange(1, 5) * ends[-1] / 5:
        i = int(np.searchsorted(ends, target))
        if i + 1 >= len(edges):
            raise ValueError("Census quintile lies in unbounded top income category")
        fraction = (target - (ends[i] - mass[i])) / mass[i]
        cutoffs.append(round(edges[i] + fraction * (edges[i + 1] - edges[i])))
    return cutoffs


def household_income(people):
    # Known children under 15 are outside the income universe. A missing income
    # for an adult or a member with masked age leaves household income unresolved.
    incomes = [p[3] for p in people if p[0] not in (1, 2)]
    if not incomes or None in incomes:
        return None
    return sum(incomes)


def household_band(people, cutoffs):
    income = household_income(people)
    return GROUPS - 1 if income is None else int(np.searchsorted(cutoffs, income, side="right"))


def household_counts(atlas_dir, day_dir, coords, cutoffs):
    counts = np.zeros((len(coords), GROUPS), dtype=np.int32)
    for da in read(day_dir / "day.json")["das"]:
        roster = read(atlas_dir / (da + ".json"))
        assigned = read(day_dir / (da + ".json"))["home"]
        for start, size, _ in roster["homes"]:
            band = household_band(roster["people"][start:start + size], cutoffs)
            counts[assigned[start], band] += 1
    occupied = counts.any(axis=1)
    return coords[occupied], counts[occupied]


def get_survey(path):
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
        staged = Path(tmp) / "shs.zip"
        with urlopen(DOWNLOAD, timeout=90) as response:
            staged.write_bytes(response.read())
        spending(staged)
        staged.replace(path)


def walking_access(network, points, stores):
    graph, snap = walk_graph(network)
    nodes, offsets = snap(points)
    unreachable = LIMITS[-1] + 1

    def distances(point):
        node, access = snap(point)
        routed = dijkstra(graph, indices=node, limit=LIMITS[-1])
        metres = access + routed[nodes] + offsets
        return np.ceil(np.minimum(metres, unreachable) * 1000).astype(np.int32)

    nearest = np.full(len(points), unreachable * 1000, dtype=np.int32)
    for store in stores:
        nearest = np.minimum(nearest, distances(store["point"]))
    return distances, nearest


def prepare(archive, root, market, work, survey):
    atlas_dir = root / "atlas" / market["atlas"]
    day_dir = root / "cityday" / market["day"]
    street_dir = root / "streets" / market["streets"]
    get_survey(survey)
    budgets = spending(survey)
    cutoffs = income_cutoffs(archive / "data/raw")
    coords = np.array([p[:2] for p in read(day_dir / "places.json")])
    points, counts = household_counts(atlas_dir, day_dir, coords, cutoffs)
    if counts.sum() != read(atlas_dir / "atlas.json")["city"]["homes"]:
        raise ValueError("Household count mismatch")

    distances, nearest = walking_access(read(street_dir / "network.json"), points, market["stores"])

    sites = market["sites"]
    reference = np.zeros((len(LIMITS), len(sites), 3, GROUPS), dtype=np.int32)
    rows_total = 0
    house_pairs = 0
    for start in range(0, len(sites), BATCH):
        columns = []
        for i, site in enumerate(sites[start:start + BATCH]):
            candidate = distances(site["point"])
            idx = np.flatnonzero(candidate <= LIMITS[-1] * 1000)
            costs, existing, bins = candidate[idx], nearest[idx], counts[idx]
            for j, metres in enumerate(LIMITS):
                limit = metres * 1000
                near = costs <= limit
                wins = near & (costs < existing)
                for k, mask in enumerate((near, wins & (existing <= limit), wins & (existing > limit))):
                    reference[j, start + i, k] = bins[mask].sum(axis=0)
            anchors, bands = np.nonzero(bins)
            columns.append(np.column_stack((i * 3 * GROUPS + bands, costs[anchors],
                                            existing[anchors], bins[anchors, bands])))
        packed = np.concatenate(columns).astype("<i4")
        folder = work / str(start)
        folder.mkdir()
        for col, name in enumerate(("bins", "distance", "existing", "multiplicity")):
            packed[:, col].tofile(folder / (name + ".i32"))
        rows_total += len(packed)
        house_pairs += int(packed[:, 3].sum())

    np.save(work / "reference.npy", reference)
    result = dict(atlas=market["atlas"], day=market["day"], streets=market["streets"], radii=LIMITS,
                  sites=[s["id"] for s in sites], budgets=budgets, thresholds=cutoffs,
                  households=counts.sum(axis=0).tolist(), year=2021, groups=rows_total, pairs=house_pairs,
                  source=SOURCE, guide=GUIDE, sourceHash=hashlib.sha256(survey.read_bytes()).hexdigest())
    write_json(work / "model.json", result)
    return result


def collect(root, work, verify, backend):
    result = read(work / "model.json")
    reference = np.load(work / "reference.npy")
    for j, radius in enumerate(LIMITS):
        for size in (["groups", "agents"] if verify else ["groups"]):
            for i in range(0, len(result["sites"]), BATCH):
                target = reference[j, i:i + BATCH]
                output = work / str(i) / f"{size}-{radius}.i32"
                actual = np.fromfile(output, dtype="<i4").reshape(target.shape)
                if not np.array_equal(actual, target):
                    raise ValueError(f"Raster disagrees with the network reference at {i}, {radius} m, {size}")

    result.update(counts=reference.tolist(), backend=backend, verifiedHouseholds=verify)
    dest = root / "household-market"
    dest.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest) as tmp:
        staged = Path(tmp) / "report.json"
        write_json(staged, result)
        staged.replace(dest / "{atlas}_{day}_{streets}.json".format(**result))
    return result


def publish(archive, root, market, backend="jvm", verify=False, survey=SURVEY):
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        prepare(archive, root, market, work, survey)
        command = ["clojure", "-J--enable-native-access=ALL-UNNAMED", "-J--add-modules=jdk.incubator.vector",
                   "-M", "-m", "city.vancouver.household-market", str(work), backend]
        if verify:
            command.append("agents")
        subprocess.run(command, check=True)
        return collect(root, work, verify, backend)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--backend", default="jvm")
    parser.add_argument("--verify-households", action="store_true")
    args = parser.parse_args()
    day = read(args.data / "cityday/current.json")
    street = read(args.data / "streets/current.json")["version"]
    market = read(args.data / "market" / (day["version"] + "_" + street + ".json"))
    if market["atlas"] != day["atlas"]:
        raise ValueError("Mismatched retail and census releases")
    result = publish(args.archive, args.data, market, args.backend, args.verify_households)
    print(f"{sum(result['households']):,} households, {result['groups']:,} weighted rows, "
          f"{result['pairs']:,} household–site pairs")
