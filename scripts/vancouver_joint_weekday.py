"""Publish one municipal weekday with fitted commutes, direct transit and shopping walks."""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_city_transit import assign, publish_walks
from scripts.vancouver_mobility import PRIORITY, REPORT
from scripts.vancouver_pedestrians import verify_routes
from scripts.vancouver_region import package, read
from scripts.vancouver_street_scenarios import CITY_TRANSIT, publish_index
from scripts.vancouver_transit import build as build_timetable
from scripts.vancouver_transit_commutes import BOARDING_MARGIN_SECONDS, pointer


def release(root, family, key):
    return read(root / family / f"{key}.json")["version"]


def compose(baseline, outbound, tract, extracted):
    base = np.asarray(baseline["counts"])
    change = np.asarray(outbound["delta"]) + np.asarray(tract["delta"])
    fitted = base + change
    fitted[..., baseline["modes"].index("Walking")] += np.asarray(extracted["flows"])
    if np.any(fitted < 0):
        raise ValueError("Joint weekday trips do not reconcile")
    return dict(baseline, counts=fitted.tolist(), joint=True)


def timetable_with_transfers(root, atlas, original, feed):
    base = root / "transit" / original
    manifest = read(base / "transit.json")
    area = read(root / "atlas" / atlas / "atlas.json")["areas"]
    geometry = {name: item["geometry"] for name, item in area.items()}

    def build(folder):
        build_timetable(feed, geometry, date.fromisoformat(manifest["date"]), folder,
                        passenger_rules=True, transfer_rules=True)
        updated_manifest = read(folder / "transit.json")
        updated_manifest.pop("feedDigest")
        if updated_manifest != manifest:
            raise ValueError("The transfer timetable differs from the direct timetable")
        for route in manifest["routes"]:
            file = route["id"] + ".json"
            updated = read(folder / file)
            updated.pop("stopIds")
            if updated != read(base / file):
                raise ValueError(f"Adding transfers altered route {route['id']}")

    return package(root, "transit", build)


def publish(root, archive, transfers=False, versions=None, *, preserve_modes=False, capacity=False, tract_release=None,
            reuse_riders_from=None):
    if tract_release is not None and not re.fullmatch(r"[a-f0-9]{20}", tract_release):
        raise ValueError("Choose a published tract workplace release")
    if versions is None:
        current = read(root / "cityday/current.json")
        versions = dict(atlas=current["atlas"], day=current["version"], streets=read(root / "streets/current.json")["version"])
    version = versions
    atlas, day, streets = (version[k] for k in ("atlas", "day", "streets"))
    roster_key = f"{atlas}_{day}"
    outbound = release(root, "outbound", roster_key)
    worksites = release(root, "worksites", outbound)
    tract_key = worksites + "_diary_modes" if preserve_modes else worksites
    tracts = tract_release or release(root, "tract-workplaces", tract_key)
    outings = release(root, "discretionary-outings", roster_key)
    commuters = release(root, "commuters", roster_key)
    shopping = read(root / "discretionary-outings" / outings / "report.json")
    if any(shopping["versions"].get(k) != v for k, v in version.items()):
        raise ValueError("The shopping scenario belongs to a different weekday")
    transit_parent = read(root / "transit-riders" / f"{roster_key}_{streets}.json")
    raw = archive / "data/raw/probes"
    transit = (timetable_with_transfers(root, atlas, transit_parent["transit"], raw / "transit_translink_gtfs_static.zip")
               if transfers else transit_parent["transit"])
    rider_base = root / "transit-riders" / transit_parent["riders"]
    transit_baseline = read(rider_base / "downtown.json")
    ped_parent = release(root, "pedestrians", f"{day}_{streets}")
    pedestrian_baseline = read(root / "pedestrians" / ped_parent / "counts.json")
    work = read(root / "outbound" / outbound / "report.json")
    tract = read(root / "tract-workplaces" / tracts / "worksites.json")
    if (tract["atlas"], tract["day"], tract["outbound"], tract["worksites"]) != (atlas, day, outbound, worksites):
        raise ValueError("The tract workplace assignment uses a different roster or census workplace parent")
    if bool(tract.get("preserveDiaryModes")) != preserve_modes or (preserve_modes and tract["streets"] != streets):
        raise ValueError("The workplace assignment uses a different commute policy or street network")
    roster = read(root / "cityday" / day / "day.json")
    source = raw / "transit_translink_tspr2025_bus_yearline.csv"
    inputs = dict(version, outbound=outbound, worksites=worksites, tracts=tracts, outings=outings)
    family = root / "joint-weekday"
    family.mkdir(exist_ok=True)
    previous_riders = None
    if reuse_riders_from is not None:
        if not re.fullmatch(r"[a-f0-9]{20}", reuse_riders_from):
            raise ValueError("Reuse requires a published combined weekday")
        reference = read(family/reuse_riders_from/"report.json")
        previous_tract = reference["workplaces"]["tract-workplaces"]
        if (tract.get("roadRepairs", {}).get("source") != previous_tract or reference["versions"] != version
                or reference["transit"] != transit or reference["outings"] != outings
                or bool(reference.get("capacityChecked")) != capacity or bool(reference.get("transfers")) != transfers):
            raise ValueError("The repair and reference weekday do not share the same timetable and booking policy")
        previous_riders = root/"transit-riders"/reference["riders"]
    key = f"{roster_key}_{streets}"
    workplace_key = f"_tracts_{tract_release}" if tract_release else "_diary_modes" if preserve_modes else ""
    run_key = key + workplace_key + ("_capacity" if capacity else "")
    direct_index = family / f"{run_key}_direct.json"
    direct_joint = None
    if transfers:
        current_joint = direct_index if direct_index.is_file() else family / f"{key}.json"
        if current_joint.is_file():
            direct_joint = read(current_joint)["version"]
            prior = read(family / direct_joint / "report.json")
            if (prior.get("transfers") or prior["outings"] != outings or bool(prior.get("capacityChecked")) != capacity
                    or prior["workplaces"].get("tract-workplaces") != tracts):
                direct_joint = None
    with tempfile.TemporaryDirectory(dir=family) as tmp:
        folder = Path(tmp)
        request, result = folder / "input.json", folder / "legs.json"
        write_json(request, dict(inputs, priority=PRIORITY, surveyModes=REPORT))
        subprocess.run(["node", "scripts/vancouver_joint_trips.mjs", root, request, result], check=True)
        extracted = read(result)
        if previous_riders:
            write_json(request, dict(inputs, tracts=previous_tract, priority=PRIORITY, surveyModes=REPORT))
            subprocess.run(["node", "scripts/vancouver_joint_trips.mjs", root, request, result], check=True)
            previous = read(result)
            if any(extracted[field] != previous[field] for field in ("transit", "excluded")):
                raise ValueError("A workplace repair changed the eligible transit windows or their endpoints")
        short = extracted["short"]
        assembled = compose(transit_baseline, work, tract, extracted)
        modes = {mode: fifths / 5 for mode, fifths in extracted["adultModeDelta"].items()}
        if preserve_modes and any(extracted["adultModeDelta"].values()):
            raise ValueError("The workplace scenario changed a fitted diary mode")
        if sum(extracted["adultModeDelta"].values()):
            raise ValueError("A workplace fit changed the total number of adult trips")
        occ = np.array(roster["occupancy"])
        count = len(roster["areas"])
        relocated = np.asarray(work["relocated"])
        occ[:, :count] -= relocated[:, :count]
        occ[:, -1] += relocated[:, :count].sum(axis=1)
        occ[:, :count] += np.asarray(tract["occupancyDelta"])
        occ += np.asarray(short["occupancyDelta"]) + np.asarray(shopping["occupancyDelta"])
        if np.any(occ < 0) or not np.all(occ.sum(axis=1) == roster["population"]):
            raise ValueError("The combined occupancy does not conserve the roster")
        short_path = folder / "short.json"
        write_json(short_path, short)
        rider_versions = dict(version, transit=transit, workplaces=tracts)

        def build_riders(out):
            if previous_riders:
                saved = read(previous_riders/"riders.json")
                if saved["versions"] != dict(rider_versions, workplaces=previous_tract):
                    raise ValueError("The saved riders use a different workplace release or timetable")
                for area in saved["das"]:
                    shutil.copyfile(previous_riders/(area+".json"), out/(area+".json"))
                saved["versions"] = rider_versions
                old_downtown = read(previous_riders/"downtown.json")
                downtown = dict(assembled, rail=old_downtown["rail"])
                if capacity:
                    downtown["capacityChecked"] = True
                write_json(out/"riders.json", saved)
                write_json(out/"downtown.json", downtown)
            else:
                assign(root, rider_versions, source, out, legs=(extracted["transit"], extracted["excluded"]),
                       downtown=assembled, transfer_margin=BOARDING_MARGIN_SECONDS if transfers else None,
                       book_capacity=capacity)
            report = read(out / "riders.json")
            sample = {(roster["das"][d], i) for d, i, *_ in roster["sample"]}
            indexes = {da: i for i, da in enumerate(roster["das"])}
            starts, examples = [], []
            before = None
            if direct_joint:
                before = root / "transit-riders" / read(family / direct_joint / "report.json")["riders"]
                if not set(read(before / "riders.json")["das"]) <= set(report["das"]):
                    raise ValueError("Transfers removed an area of direct rides")
            for da in report["das"]:
                area_file = f"{da}.json"
                rows = read(out / area_file)
                if before and (before / area_file).is_file() and read(before / area_file) != [row for row in rows if len(row) == 12]:
                    raise ValueError("Transfers altered a direct ride")
                for row in rows:
                    starts.append([indexes[da], row[1], row[2]])
                    if tuple(row[:2]) in sample:
                        examples.append(row)
            if len(starts) != len({tuple(x) for x in starts}):
                raise ValueError("A resident's diary leg was matched twice")
            write_json(out / "sample.json", examples)
            write_json(out / "departures.json", starts)

        riders = package(root, "transit-riders", build_riders)
        publish_walks(root, riders)
        publish_index(root, CITY_TRANSIT, riders)
        request = dict(radius=pedestrian_baseline["radius"], sites=pedestrian_baseline["sites"],
                       joint=dict(inputs, transit=transit, riders=riders, short=str(short_path)))
        spool = folder / "pedestrians.json"
        result = subprocess.run(["node", "scripts/vancouver_pedestrians.mjs", root, spool],
                                input=json.dumps(request), text=True, stdout=subprocess.PIPE, check=True)
        crossings = json.loads(result.stdout)
        verify_routes(root, crossings, read(spool))
        for baseline, site in zip(pedestrian_baseline["sites"], crossings["sites"], strict=True):
            if site["name"] != baseline["name"] or site["city"] != baseline["city"]:
                raise ValueError("The paired pedestrian counts have different source support")
            site["baseline"] = [a + b for a, b in zip(baseline["city"], baseline["inferred"], strict=True)]
            components = ["tracts", "inferred", "access", "egress", "shopping"]
            if transfers:
                components.append("transfer")
            site["joint"] = list(map(sum, zip(*(site[k] for k in components), strict=True)))
        report = dict(versions=version, workplaces={"outbound": outbound, "worksites": worksites, "tract-workplaces": tracts},
                      transit=transit, riders=riders, originalRiders=transit_parent["riders"], commuters=commuters, outings=outings,
                      pedestrianBaseline=ped_parent, commuteRule="tracts", activeModeDelta=modes, people=roster["population"],
                      departures=extracted["stats"], shortWalks=len(short["walks"]), shoppingOutings=shopping["attendance"],
                      originalShortWalksDigest=hashlib.sha256(
                          (root / "short-walks" / f"{day}_{streets}.json").read_bytes()).hexdigest())
        if preserve_modes:
            report.update(preserveDiaryModes=True, activeWorkRoutes=tract["activeRoutes"])
        if capacity:
            report["capacityChecked"] = True
        if previous_riders:
            report["identicalRiderWindows"] = reference["riders"]
        if transfers:
            report["transfers"] = read(root / "transit-riders" / riders / "riders.json")["transfers"]
            if direct_joint:
                report["directJoint"] = direct_joint

        def combined(out):
            write_json(out / "report.json", report)
            write_json(out / "short-walks.json", short)
            write_json(out / "pedestrians.json", crossings)
            write_json(out / "occupancy.json", occ.tolist())

        joint = package(root, "joint-weekday", combined)
    if not transfers:
        pointer(direct_index, {"version": joint})
    elif direct_joint:
        pointer(direct_index, {"version": direct_joint})
    if run_key != key:
        pointer(family / f"{run_key}.json", {"version": joint})
    if tract_release is None:
        pointer(family / f"{key}.json", {"version": joint})
    if (tract_release and tract.get("roadRepairs") and preserve_modes and capacity and transfers
            and previous_riders and direct_joint):
        pointer(family / f"{key}_repaired_capacity.json", {"version": joint})
    print(joint, report, flush=True)
    return joint


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--transfers", action="store_true", help="Fit one connection for trips without a direct ride")
    parser.add_argument("--capacity", action="store_true", help="Book direct and connecting rides within modeled bus capacities")
    args = parser.parse_args()
    publish(args.root, args.archive, args.transfers, capacity=args.capacity)
