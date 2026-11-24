"""Prepare Census transit margins for a controlled reassignment of incoming workers' homes."""
import argparse
from bisect import bisect_right
from collections import Counter
import csv
from math import dist
import mmap
from pathlib import Path
import subprocess
from statistics import median
import tempfile

from scripts.artifacts import package, pointer, read, write_json
from scripts.vancouver_inbound import profile_das


SOURCE = "https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/index.cfm?Lang=E"


def census_transit(raw, cities):
    controls = {}
    profile = next(raw.glob("*_data_BritishColumbia.csv"))
    with profile.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        for _, dguid in profile_das(raw, cities):
            start = data.find(f'2021,"{dguid}",'.encode(), data.tell())
            if start < 0:
                raise ValueError(f"Missing Census area {dguid}")
            offset = data.find(b',2603,"Total - Main mode of commuting', start)
            if offset < 0:
                raise ValueError(f"Missing commute margin for {dguid}")
            data.seek(data.rfind(b'\n', start, offset) + 1)
            rows = list(csv.reader(data.readline().decode("cp1252") for _ in range(5)))
            if [r[8] for r in rows] != [str(k) for k in range(2603, 2608)] or any(r[1] != dguid for r in rows):
                raise ValueError(f"Misaligned commute margin for {dguid}")
            total, transit = (int(row[11]) if row[11] and not row[12] else None for row in (rows[0], rows[-1]))
            if total and transit is not None:
                # These cells are rounded independently to multiples of five.
                controls[dguid[-8:]] = [total, min(total, transit)]
            else:
                controls[dguid[-8:]] = None
    return controls


def verify_fit(payload, fitted):
    """Check home, demographic and trip invariants independently of the fitting algorithm."""
    moves = []
    for group, cohort in payload["groups"].items():
        people, points = cohort["people"], cohort["points"]
        result = fitted["groups"][group]
        changed = {}
        for i, old, new in result["changes"]:
            if i in changed or old != people[i][0] or old == new or not 0 <= new < len(points):
                raise ValueError(f"Invalid or repeated home move at {group}/{i}")
            changed[i] = new
            work = payload["jobs"][people[i][1]]
            bounds = fitted["distanceLowerMeters"]
            if bisect_right(bounds, dist(points[old], work)) != bisect_right(bounds, dist(points[new], work)):
                raise ValueError("A home move changed a Census commute distance band")
            moves.append(dist(points[old], points[new]))
        before = Counter((row[0], row[2], row[3], row[8]) for row in people)
        after = Counter((changed.get(i, row[0]), row[2], row[3], row[8]) for i, row in enumerate(people))
        if before != after or len(changed) != result["moved"]:
            raise ValueError("The home fit changed address, age, gender or attendance margins")
        transit = Counter(changed.get(i, row[0]) for i, row in enumerate(people) if row[4] == payload["mode"])
        if any(row[-1] != transit[i] for i, row in enumerate(result["areas"])):
            raise ValueError("The fitted home margin differs from the roster")
    return dict(medianMoveMetres=round(median(moves), 1) if moves else 0)


def publish(root, archive, joint_id, baseline):
    joint = read(root / "joint-weekday" / joint_id / "report.json")
    folder = root / "incoming-transit" / baseline
    report = read(folder / "report.json")
    if report["joint"] != joint_id or report["workerRelease"] != joint["commuters"] or any(
        k in report for k in ("timing", "transferComparison", "homeFit")
    ):
        raise ValueError("Use the one-transfer incoming commute replay with the original home locations")
    worker_dir = root / "commuters" / joint["commuters"]
    workers = read(worker_dir / "commuters.json")
    cohorts = {g: read(worker_dir / f"{g}.json") for g in sorted(workers["groups"])}
    homes = read(folder / "homes.json")
    places = read(root / "cityday" / joint["versions"]["day"] / "places.json")
    controls = census_transit(archive / "data/raw/statcan", workers["groups"])
    prepared = {}
    offset = 0
    for group, cohort in cohorts.items():
        ids = cohort["homes"]
        anchors = homes[offset:offset+len(ids)]
        if [p[3] for p in anchors] != [f"Home census area {da}" for da in ids]:
            raise ValueError("Incoming homes differ from the reference cohort")
        prepared[group] = dict(people=cohort["people"], points=[p[:2] for p in anchors], margins=[controls[da] for da in ids])
        offset += len(ids)
    if offset != len(homes):
        raise ValueError("The mode margins did not cover the home catalogue")
    inputs = dict(groups=prepared, jobs=[p[:2] for p in places], mode=workers["modes"].index("Public transit"))
    family = "incoming-home-fit"
    with tempfile.TemporaryDirectory() as temp:
        payload, result = (Path(temp) / name for name in ("fit-input.json", "fit-output.json"))
        write_json(payload, inputs)
        subprocess.run(["clojure", "-M", "-m", "city.vancouver.incoming-homes", str(payload), str(result)], check=True)
        fitted = read(result)
        comparison = verify_fit(inputs, fitted)

        def stage(out):
            for group, calibration in fitted["groups"].items():
                write_json(out / f"{group}.json", calibration.pop("changes"))
            evidence = dict(joint=joint_id, baseline=baseline, workerRelease=joint["commuters"], source=SOURCE, **fitted, **comparison)
            write_json(out / "report.json", evidence)

        version = package(root, family, stage)
    pointer(root / family / f"{joint_id}.json", {"version": version})
    print(version, sum(r["moved"] for r in fitted["groups"].values()), "changed workers", flush=True)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("joint")
    parser.add_argument("baseline")
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    args = parser.parse_args()
    publish(args.root, args.archive, args.joint, args.baseline)
