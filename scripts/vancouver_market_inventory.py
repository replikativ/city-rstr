"""Test an audited set of missing East Vancouver grocers on the existing market."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
from functools import partial
from pathlib import Path
import re
import tempfile

import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_cityday import receipts, xy
from scripts.vancouver_local_groceries import observations, venue_distances
from scripts.vancouver_market import archive_market, read, score
from scripts.vancouver_streets import walk_graph
from scripts.vancouver_transit_commutes import pointer


# The 2025 licences supply the locations and the businesses confirm take-home food retail.
RETAILERS = {
    "25-119258": ("2342 E HASTINGS ST", "Donald's Market", "https://donaldsmarkethastings.com/contact"),
    "25-119607": ("2828 E HASTINGS ST", "Tama Organic Life Foods", "https://tamaorganic.com/contact-us/"),
    "25-147835": ("1370 NANAIMO ST", "Renzullo Food Market", "https://renzullofoodmarket.com/"),
    "25-146984": ("1465 KOOTENAY ST", "Bosa Foods", "https://bosafoods.com/contact/"),
    "25-146374": ("2705 E 22ND AV", "Banana Grove Market & Deli", "https://www.bananagrovemarket.com/"),
}
SOURCE = "https://opendata.vancouver.ca/explore/dataset/business-licences/"


def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def verified_stores(raw, areas, existing):
    latest = {}
    field = r':where "localarea=\\"([^"\\]+)\\""'
    for file in receipts(raw / "vancouver-ods", "business-licences", field):
        for row in read(file):
            licence = row["licencenumber"]
            if licence not in RETAILERS or row["folderyear"] != "25":
                continue
            old = latest.get(licence)
            if old is None or int(row["licencerevisionnumber"]) > int(old[0]["licencerevisionnumber"]):
                latest[licence] = row, file
    if latest.keys() != RETAILERS.keys():
        raise ValueError("The archived licence extract lacks a verified retailer")
    listings = []
    for licence, (address, name, source) in RETAILERS.items():
        row, file = latest[licence]
        if (row["status"] != "Issued" or not row["geo_point_2d"] or address in existing
                or f"{row['house']} {row['street']}".upper() != address):
            raise ValueError(f"Unexpected licence location, status or duplicate address for {licence}")
        store = dict(id=address, name=name, point=xy(**row["geo_point_2d"]), area=areas.index(row["localarea"]))
        listings.append(dict(store=store, licence=licence, category=row["businesstype"], source=source,
                             archiveFile=file.name, archiveDigest=digest(file)))
    return listings


def rescore(occasions, graph, routing, stores, site, speed):
    rows = deepcopy(occasions)
    split = next((i for i, row in enumerate(rows) if len(row) > 17 and row[17] == "added-shopping"), len(rows))
    changes, after_hours = [], []
    # Preserve the snapping rules of the two published demand builders.
    for offset, batch, (snap, ends) in zip((0, split), (rows[:split], rows[split:]), routing, strict=True):
        if not batch:
            continue
        trips = [[row[13], row[14], row[11], row[12]] for row in batch]
        (visits,), (late,) = score(batch, trips, graph, snap, *ends, stores, [site], speed=speed)
        changes.extend([offset + i, cost] for i, cost in visits)
        after_hours.extend([offset + i, cost] for i, cost in late)
    return rows, [changes], [after_hours]


def compare_access(day, atlas, stores, added, site, graph, snap, canfed, geography, access_catalogue):
    reference = access_catalogue["localWalk"]
    das, points, observed, _ = observations(day["das"], canfed, geography)
    if (das != reference["das"] or observed[1000] != reference["observed"]["1000"]
            or digest(canfed) != reference["canfed"] or digest(geography) != reference["geography"]):
        raise ValueError("The food-access benchmark uses different reference observations")
    centres = [xy(*point) for point in points]
    ends = snap(centres, lowest_id_on_ties=True)
    counts_by_store = lambda rows: list(venue_distances(graph, snap, [s["point"] for s in rows], ends, 1000))
    before = np.sum(np.asarray(counts_by_store(stores)) <= 1000, axis=0)
    if before.tolist() != reference["counts"][0]:
        raise ValueError("The access query does not reproduce the archived 1 km counts")
    added_distances = counts_by_store(added)
    after = before + np.sum(np.asarray(added_distances) <= 1000, axis=0)
    candidate, = counts_by_store([site])
    own = set(atlas["areas"][day["areas"][site["area"]]]["das"])
    local = np.asarray([da in own and row is not None for da, row in zip(das, observed[1000], strict=True)])
    observed_has_store = np.asarray([bool(row and any(row)) for row in observed[1000]])
    gained_before, gained_after = (candidate <= 1000) & (before == 0), (candidate <= 1000) & (after == 0)
    gained_by_store = {row["id"]: int(((d <= 1000) & local & (before == 0)).sum())
                       for row, d in zip(added, added_distances, strict=True)}
    return dict(radius=1000, neighbourhood=day["areas"][site["area"]], comparable=int(local.sum()),
                observed=int((local & observed_has_store).sum()),
                original=int((local & (before > 0)).sum()), expanded=int((local & (after > 0)).sum()),
                firstAccessOriginal=int(gained_before.sum()), firstAccessExpanded=int(gained_after.sum()),
                firstAccessExpandedAlreadyObserved=int((gained_after & observed_has_store).sum()),
                coveredByExpansion=[da for da, gained in zip(das, (before == 0) & (after > 0), strict=True) if gained],
                addedShopReach=gained_by_store, canfed=reference["canfed"], geography=reference["geography"])


def publish(data, release, archive, site_id, canfed, geography):
    root = data / "vancouver"
    run = read(data / "runs" / f"{release}.json")
    if (run["release"], run["city"], run["coverage"]) != (release, "vancouver", "city"):
        raise ValueError("Choose a combined Vancouver municipal weekday")
    pair = read(root / "market" / f"demand_{run['jointRun']}.json")
    report_path = root / "market" / "sensitivity" / f"{site_id}-{release}.json"
    audit = read(report_path)
    original_file = root / "market" / "archive" / pair["market"] / "market.json"
    access_file = root / "market" / "archive" / audit["accessMarket"] / "market.json"
    original, access_catalogue = read(original_file), read(access_file)
    if (digest(original_file) != pair["market"] or digest(access_file) != audit["accessMarket"]
            or audit["site"]["id"] != site_id or audit["release"] != release
            or original["shoppingDemand"]["outings"] != pair["outings"]
            or access_catalogue["stores"] != original["stores"]
            or access_catalogue["streets"] != original["streets"]
            or any(run[key] != original[key] for key in ("atlas", "day", "streets"))):
        raise ValueError("The market or access archive belongs to a different weekday")
    site_index = next(i for i,s in enumerate(original["sites"]) if s["id"] == site_id)
    site = original["sites"][site_index]
    day_dir = root / "cityday" / run["day"]
    day = read(day_dir / "day.json")
    atlas = read(root / "atlas" / run["atlas"] / "atlas.json")
    listings = verified_stores(archive / "data/raw", day["areas"], {s["id"] for s in original["stores"]})
    added = [row["store"] for row in listings]
    graph, snap = walk_graph(read(root / "streets" / run["streets"] / "network.json"))
    coordinates = np.asarray([p[:2] for p in read(day_dir / "places.json")])
    fitted_snap = partial(snap, lowest_id_on_ties=True)
    routing = [(lookup, lookup(coordinates)) for lookup in (snap, fitted_snap)]
    existing = original["stores"]
    expanded = [*existing, *added]
    access = compare_access(day, atlas, existing, added, site, graph, snap, canfed, geography, access_catalogue)
    tests, rescores = [], []
    for prior in original["runs"]:
        rows, changes, extra = rescore(prior["occasions"], graph, routing, existing, site, original["speed"])
        if (rows != prior["occasions"] or changes != [prior["changes"][site_index]]
                or extra != [prior["afterHours"][site_index]]):
            raise ValueError("The single-site scorer does not reproduce the published opening")
        rows, changes, extra = rescore(prior["occasions"], graph, routing, expanded, site, original["speed"])
        tests.append(Counter(expanded[row[5]]["id"] for row in rows if row[5] >= len(existing)))
        rescores.append(dict(prior, occasions=rows, changes=changes, afterHours=extra))

    corrected = dict(original, sites=[site], stores=expanded, runs=rescores,
                     incumbentInventory=dict(original=pair["market"], added=listings))
    selected = original["variants"]["tracts"]
    out_dir = root / "market" / "sensitivity"
    with tempfile.TemporaryDirectory(dir=out_dir) as temp:
        staged = Path(temp) / "market.json"
        write_json(staged, corrected)
        variant = archive_market(root, staged, corrected)
    report = dict(schema=1, release=release, site=site_id, original=pair["market"], market=variant,
                  added=listings, inventorySource=SOURCE, access=access, groceryOccasions=len(rescores[selected]["occasions"]),
                  assignedToAddedStores=tests[selected])
    path = out_dir / f"{site_id}-{release}-inventory.json"
    pointer(path, report)
    print(path, variant, access, tests[selected], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data", type=Path, default=Path("public/data"))
    parser.add_argument("--site", default="3738")
    parser.add_argument("--canfed", type=Path, default=Path("data/mobility/canfed_2024.zip"))
    parser.add_argument("--geography", type=Path, default=Path("data/mobility/2021_92-151_X.zip"))
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{64}", args.release) or not args.site.isdigit():
        parser.error("Choose a 64-character weekday ID and a storefront ID")
    publish(args.data, args.release, args.archive, args.site, args.canfed, args.geography)
