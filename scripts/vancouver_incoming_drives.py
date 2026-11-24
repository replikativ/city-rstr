"""Check original and Census-calibrated incoming driving commutes on the metro roads."""
import argparse
from collections import Counter
import hashlib
from pathlib import Path

import numpy as np

from scripts.artifacts import package, pointer, read, write_json
from scripts.vancouver_commuter_coverage import road_sections
from scripts.vancouver_drive_profile import DEFAULTS, direction_speeds
from scripts.vancouver_streets import encode_way, permissions
from scripts.vancouver_workplace_drives import score, summarize


def build_roads(directory, pbf, bounds, digest):
    nodes, ids, names, ways, speeds = [], {}, {}, [], []
    coverage = Counter()
    for tags, refs, lons, lats in road_sections(pbf, bounds):
        bits = permissions(tags) & 6
        if bits:
            way = dict(tags=tags, nodes=refs, geometry=[dict(lon=x, lat=y) for x, y in zip(lons, lats, strict=True)])
            ways.append(encode_way(way, bits, nodes, ids, names))
            speeds.append(direction_speeds(tags, bits, coverage))
    if not ways:
        raise ValueError("The OSM archive does not cover any incoming motor routes")
    write_json(directory / "network.json", dict(nodes=nodes, ways=ways, names=list(names)))
    write_json(directory / "profile.json", dict(kmh=speeds, connectorKmh=22.8, connectorMetres=500,
                                                  coverage=dict(coverage), defaults=DEFAULTS))
    write_json(directory / "report.json", dict(bounds=bounds, sourceDigest=digest, nodes=len(nodes), ways=len(ways)))
    print(f"Extracted {len(ways):,} directed road sections", flush=True)


def driving_legs(cohorts, home_index, fit_dir, mode):
    rows = []
    for group_index, (group, cohort) in enumerate(cohorts.items()):
        changed = {i: (old, new) for i, old, new in read(fit_dir / f"{group}.json")}
        for i, (home, job, _, _, usual, start, duration, shift, attends, _) in enumerate(cohort["people"]):
            if attends and usual == mode:
                old, new = changed.get(i, (home, home))
                if old != home or not 0 <= new < len(cohort["homes"]):
                    raise ValueError("The driver’s fitted home belongs to a different roster")
                a, b = home_index+old, home_index+new
                rows.extend([(group_index, i, start, duration, a, job, b, job, 1),
                             (group_index, i, start+duration+shift, duration, job, a, job, b, 0)])
        home_index += len(cohort["homes"])
    return rows, home_index


def publish(root, pbf, joint_id, fit_id):
    fit_dir = root / "incoming-home-fit" / fit_id
    fit = read(fit_dir / "report.json")
    joint = read(root / "joint-weekday" / joint_id / "report.json")
    if (fit["joint"], fit["workerRelease"]) != (joint_id, joint["commuters"]):
        raise ValueError("Incoming driver homes and jobs belong to different weekdays")
    original = root / "incoming-transit" / fit["baseline"]
    incoming = read(original / "report.json")
    home_points = read(original / "homes.json")
    worker_dir = root / "commuters" / joint["commuters"]
    workers = read(worker_dir / "commuters.json")
    cohorts = {group: read(worker_dir / f"{group}.json") for group in sorted(workers["groups"])}
    if [p[3] for p in home_points] != [f"Home census area {da}" for c in cohorts.values() for da in c["homes"]]:
        raise ValueError("The published home catalogue and driver roster do not align")
    places = read(root / "cityday" / joint["versions"]["day"] / "places.json")
    if len(places) != incoming["homeIndex"]:
        raise ValueError("Incoming drivers use a different workplace catalogue")
    rows, total = driving_legs(cohorts, len(places), fit_dir, workers["modes"].index("Car driver"))
    places += home_points
    if total != len(places):
        raise ValueError("Incoming driving legs did not include the complete home roster")
    walking = read(root / "commuter-walk" / incoming["walking"] / "report.json")
    with pbf.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != walking["sourceDigest"]:
        raise ValueError("Use the same OpenStreetMap archive as the commuter street walks")
    family = "commuter-drive"
    version = package(root, family, lambda directory: build_roads(directory, pbf, walking["bounds"], digest))
    directory = root / family / version
    network, profile = (read(directory / name) for name in ("network.json", "profile.json"))
    print(f"Checking {len(rows):,} original and fitted driver windows", flush=True)
    legs, times, failures, slowed = score(rows, places, network, profile, dict(corridors=[]))
    stats = summarize(legs, times, failures, slowed, list(cohorts))
    active = np.isfinite(times[:, :2]).reshape(-1, 2, 2).all(axis=1).sum(axis=0)
    report = dict(joint=joint_id, homeFit=fit_id, network=version, workerRelease=joint["commuters"],
                  versions=joint["versions"], basis="free-flow", bothDirections=active.tolist(), **stats)
    pointer(root / "incoming-drives" / f"{fit_id}.json", report)
    print(version, stats["day"], report["bothDirections"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("joint")
    parser.add_argument("fit")
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--pbf", type=Path, default=Path("data/region/vancouver.osm.pbf"))
    args = parser.parse_args()
    publish(args.root, args.pbf, args.joint, args.fit)
