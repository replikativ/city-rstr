"""Test held-out household income and usual commute distributions against the 2021 Census Profile."""
import argparse
from bisect import bisect_right
import json
from pathlib import Path
import tempfile

import numpy as np

from scripts.vancouver_atlas import donors, write_json
from scripts.vancouver_census_geography import CITY, DA, profile_cells
from scripts.vancouver_household_market import household_income
from scripts.vancouver_region import NAMES

INCOME_CUTS = [50000, 100000, 150000]
# The income bands partition before-tax private household income (100% data).
# The commute bands partition the reported main commuting mode (25% sample).
BANDS = {"income": [range(261, 271), range(271, 276), (277, 278), (279, 280)],
         "commute": [(i,) for i in range(2605, 2611)]}
DENOMINATORS = {"income": 260, "commute": 2603}
LABELS = {"income": ["Below $50,000", "$50,000–99,999", "$100,000–149,999", "$150,000 or more"],
          "commute": ["Car driver", "Car passenger", "Public transit", "Walking", "Bicycle", "Other method"]}
MODE = {2: 0, 5: 1, 6: 2, 7: 3, 1: 4, 3: 5, 4: 5}


def read(path):
    return json.loads(path.read_bytes())


# Each mean or proportion uses its own published universe when aggregating DAs.
HOUSING = {"ownerValue": (1482, 1489), "mortgaged": (1482, 1483),
           "tenantCost": (1490, 1495), "rentBurden": (1490, 1492)}


def housing_stats(cells):
    result = {}
    for key, (universe, value) in HOUSING.items():
        n, x = cells[universe], cells[value]
        if n and x is not None:
            result[key] = [n, x]
    return result


def aggregate_housing(rows):
    result = {}
    for key in HOUSING:
        pairs = [r[key] for r in rows if key in r]
        if pairs:
            total = sum(n for n, x in pairs)
            result[key] = [total, round(sum(n * x for n, x in pairs) / total, 2)]
    return result


def profiles(raw, keys):
    required = set(DENOMINATORS.values()) | {i for bands in BANDS.values() for group in bands for i in group}
    required.update(i for pair in HOUSING.values() for i in pair)
    return {key: {**{k: benchmark(cells, k) for k in BANDS}, "housing": housing_stats(cells)}
            for key, cells in profile_cells(raw, keys, required).items()}


def benchmark(cells, measure):
    denominator = cells[DENOMINATORS[measure]]
    bands = BANDS[measure]
    if not denominator or any(cells[i] is None for group in bands for i in group):
        return None
    # Preserve the published denominator. Random rounding can leave a residual.
    return [int(denominator), *[int(sum(cells[i] for i in group)) for group in bands]]


def add_home(income, commute, members, weight):
    amount = household_income(members)
    income[4 if amount is None else bisect_right(INCOME_CUTS, amount)] += weight
    for person in members:
        mode = person[6]
        if mode in MODE:
            commute[MODE[mode]] += weight
        elif mode != 9:
            raise ValueError(f"Unexpected PUMF commuting mode {mode}")


def roster_counts(roster):
    income, commute = np.zeros(5, dtype=int), np.zeros(6, dtype=int)
    for start, size, _ in roster["homes"]:
        add_home(income, commute, roster["people"][start:start + size], 1)
    return {"income": income, "commute": commute}


def pooled_donors(raw):
    records, weights, _, _ = donors(raw / "pumf/data_donnees_2021_hier_v2.csv")
    income, commute = np.zeros(5), np.zeros(6)
    for (_, members), w in zip(records, weights, strict=True):
        add_home(income, commute, members, w)
    return {"income": (income[:-1] / income[:-1].sum()).tolist(), "commute": (commute / commute.sum()).tolist()}


def compare(ids, models, census, measure, direct=None):
    # With a municipal observation all model households are represented; a DA
    # aggregate compares only the common observable footprint on both sides.
    eligible = ids if direct is not None else [d for d in ids if census[DA + d][measure] is not None]
    if not eligible:
        return None
    modeled = np.sum([models[d][measure] for d in eligible], axis=0)
    observed = direct if direct is not None else np.sum([census[DA + d][measure] for d in eligible], axis=0).tolist()
    missing = int(modeled[-1]) if measure == "income" else 0
    return dict(model=modeled[:len(BANDS[measure])].tolist(), missing=missing, census=observed[1:],
                denominator=observed[0], covered=len(eligible), total=len(ids), direct=direct is not None)


def publish(archive, atlas_dir, regional=False):
    raw = archive / "data/raw/statcan"
    manifest = read(atlas_dir / "atlas.json")
    ids = sorted(manifest["das"])
    keys = {DA + d for d in ids}
    municipalities = {name: "2021A0005" + csd for csd, name in NAMES.items()} if regional else {"": CITY}
    census = profiles(raw, keys | set(municipalities.values()))
    models = {d: roster_counts(read(atlas_dir / (d + ".json"))) for d in ids}
    def scope(name, members):
        direct = census.get(municipalities.get(name), {})
        values = {k: compare(members, models, census, k, direct.get(k)) for k in BANDS}
        values["housing"] = direct["housing"] if direct else aggregate_housing([census[DA + d]["housing"] for d in members])
        return values
    result = dict(version=atlas_dir.name, labels=LABELS, pooled=pooled_donors(raw), all=scope("", ids),
                  areas={name: scope(name, group["das"]) for name, group in manifest["areas"].items()},
                  das={d: scope(d, [d]) for d in ids})
    dest = atlas_dir.parent / ("validation-" + atlas_dir.name + ".json")
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        staged = Path(tmp) / "validation.json"
        write_json(staged, result)
        staged.replace(dest)
    print(dest, result["all"], flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    args = parser.parse_args()
    for regional in (False, True):
        root = args.data / "region" if regional else args.data
        version = read(root / "current.json")["atlas"] if regional else read(root / "atlas/current.json")["version"]
        publish(args.archive, root / "atlas" / version, regional)
