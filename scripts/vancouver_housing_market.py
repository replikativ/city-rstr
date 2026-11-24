"""Project household shelter-cost sensitivity onto existing grocery walking catchments."""
import argparse
from pathlib import Path

import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_household_market import LIMITS, household_band, walking_access
from scripts.vancouver_region import package, read
from scripts.vancouver_transit_commutes import pointer

SHOCKS = (0, 5, 10, 20)
FIELDS = ["households", "tenants", "tenantCostsKnown", "tenantMonthlyShelter", "tenantCashflowKnown",
          "ownerValuesKnown", "ownerDwellingValue", "food", *["foodLoss" + str(s) for s in SHOCKS]]


def food_loss(budget, monthly, after_tax, shock):
    """A sensitivity case that holds the baseline grocery share of available cash fixed."""
    remainder = max(budget, after_tax - 12 * monthly)
    return round(min(budget, budget * (12 * monthly * shock / 100) / remainder))


def by_anchor(atlas, day, folder, day_manifest, places, bands, budgets):
    sums = np.zeros((len(places), len(FIELDS)), dtype=np.int64)
    for da in day_manifest["das"]:
        descriptor = read(atlas / (da + ".json"))
        homes = read(day / (da + ".json"))["home"]
        profiles = read(folder / (da + ".json"))
        for (first, length, tenure), record in zip(descriptor["homes"], profiles, strict=True):
            t, monthly, after_tax, value, _ = record
            anchor = homes[first]
            if t != tenure or anchor < 0 or any(a != anchor for a in homes[first:first+length]):
                raise ValueError(f"Housing and the weekday roster differ for {da}")
            budget = budgets[household_band(descriptor["people"][first:first+length], bands)]
            tenant = tenure == 2
            cost_known = tenant and monthly is not None
            cash_known = cost_known and after_tax is not None and after_tax > 0
            losses = [food_loss(budget, monthly, after_tax, shock) for shock in SHOCKS] if cash_known else [0]*len(SHOCKS)
            sums[anchor] += [1, tenant, cost_known, monthly if cost_known else 0, cash_known,
                             value is not None, value or 0, budget, *losses]
    return sums


def publish(root, day=None, atlas=None, streets=None):
    current = read(root / "cityday/current.json")
    versions = dict(atlas=atlas or current["atlas"], day=day or current["version"],
                    streets=streets or read(root / "streets/current.json")["version"])
    day = root / "cityday" / versions["day"]
    atlas = root / "atlas" / versions["atlas"]
    street = root / "streets" / versions["streets"]
    baseline = read(root / "market" / (versions["day"] + "_" + versions["streets"] + ".json"))
    if any(baseline[key] != value for key, value in versions.items()):
        raise ValueError("The market uses another weekday geography")
    key = "{atlas}_{day}_{streets}".format(**versions)
    result_root = root / "household-market"
    existing = read(result_root / (key + ".json"))
    housing_root = root / "atlas" / "housing"
    release = read(housing_root / (versions["atlas"] + ".json"))["version"]
    housing = housing_root / release
    manifest = read(housing / "report.json")
    if any(existing[key] != value for key, value in versions.items()) or manifest["atlas"] != versions["atlas"]:
        raise ValueError("The housing and food budgets require the same atlas")
    places = read(day / "places.json")
    totals = by_anchor(atlas, day, housing, read(day/"day.json"), places, existing["thresholds"], existing["budgets"])
    if totals[:, 0].sum() != manifest["households"]:
        raise ValueError("Housing budgets omit part of the household roster")
    used = totals[:, 0] > 0
    points = np.array([p[:2] for p in places])[used]
    totals = totals[used]
    distance, incumbent = walking_access(read(street / "network.json"), points, baseline["stores"])
    sites = baseline["sites"]
    if [site["id"] for site in sites] != existing["sites"] or LIMITS != existing["radii"]:
        raise ValueError("Baseline catchment and housing storefronts differ")
    counts = np.zeros((len(LIMITS), len(sites), 3, len(FIELDS)), dtype=np.int64)
    for i, site in enumerate(sites):
        to_shop = distance(site["point"])
        for j, radius in enumerate(LIMITS):
            limit = radius * 1000
            near = to_shop <= limit
            closer = near & (to_shop < incumbent)
            for k, group in enumerate((near, closer & (incumbent <= limit), closer & (incumbent > limit))):
                counts[j, i, k] = totals[group].sum(axis=0)

    previous = np.array(existing["counts"], dtype=np.int64)
    if not np.array_equal(counts[..., 0], previous.sum(axis=-1)) or not np.array_equal(
        counts[..., FIELDS.index("food")], previous @ existing["budgets"]
    ):
        raise ValueError("Housing changed baseline supermarket coverage or household budgets")
    losses = counts[..., FIELDS.index("foodLoss0"):]
    if losses[..., 0].any() or (np.diff(losses, axis=-1) < 0).any() or (
        losses[..., -1] > counts[..., FIELDS.index("food")]
    ).any():
        raise ValueError("Unbounded grocery response to a shelter cost increase")

    report = dict(versions=versions, housing=release, shocks=SHOCKS, sites=existing["sites"], radii=LIMITS,
                  fields=FIELDS, counts=counts.tolist(), census=manifest["censusSource"],
                  spending=existing["source"], spendingDigest=existing["sourceHash"])
    version = package(result_root, "housing", lambda out: write_json(out/"report.json", report))
    pointer(result_root / "housing" / (key + ".json"), {"version": version})
    print("Housing market", version, len(sites), "storefronts verified against baseline budgets", flush=True)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--day")
    parser.add_argument("--atlas")
    parser.add_argument("--streets")
    args = parser.parse_args()
    publish(args.data, args.day, args.atlas, args.streets)
