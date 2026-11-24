"""Publish an operational fixed-fleet comparison for a hired-ride weekday."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile

from scripts.vancouver_atlas import write_json
from scripts.vancouver_region import package, read

EVIDENCE = {
    "occupancy": {"taxi": 0.39, "ridehail": 0.54, "period": "January–March 2025",
                  "url": "https://www.ptboard.bc.ca/data-newsletters/june-2026-newsletter"},
    "waitSeconds": {"taxi": 332, "ridehail": 276, "period": "September 2024",
                    "url": "https://www.ptboard.bc.ca/data-newsletters/march-2025"},
    "fare5km": {"taxi": [16.4, 16.9], "ridehail": [11.6, 12.9], "period": "2024",
                "url": "https://www.ptboard.bc.ca/data-newsletters/may-2025"},
}


def publish(city_root, regional, day_id, clock=None):
    root = city_root / "region" if regional else city_root
    wanted = read(root / ("current.json" if regional else "cityday/current.json"))
    day = day_id or wanted.get("day", wanted.get("version"))
    streets = wanted.get("streets") or read(root / "streets/current.json")["version"]
    versions = {"atlas": wanted["atlas"], "day": day, "streets": streets}
    if clock == "spread":
        clock = read(root / "departure-clock" / (wanted["atlas"] + "_" + day + ".json"))["version"]
    if clock:
        versions["clock"] = clock
    family = root / "hired-dispatch"
    rides_root = root / "hired-rides"
    release = read(rides_root / ("_".join(versions.values()) + ".json"))["version"]
    ride_file = rides_root / release / "rides.json"
    speed = root / "drive-profile" / (streets + ".json")
    report = read(ride_file)
    if report["versions"] != versions or report["driveProfileDigest"] != hashlib.sha256(speed.read_bytes()).hexdigest():
        raise ValueError("Dispatch must use the hired trips' published street and road speed profile")
    baseline = {}
    parent_files = []
    if clock:
        parent = report["parentRides"]
        dispatch_id = read(family / (parent + ".json"))["version"]
        reference = read(family / dispatch_id / "dispatch.json")
        if (reference["rides"] != parent or reference["driveProfileDigest"] != report["driveProfileDigest"] or
                reference["versions"] != {key: value for key, value in versions.items() if key != "clock"}):
            raise ValueError("The paired dispatch requires the matching original fleet and streets")
        parent_files = [rides_root / parent / "rides.json", family / dispatch_id / "traces.json"]
        baseline = {"reference": {"dispatch": dispatch_id, "rides": parent,
                    "fleet": {mode: data["reference"]["capacity"] for mode, data in reference["summaries"].items()},
                    "results": {mode: {key: data["reference"][key] for key in
                                       ("served", "diary", "dispatch", "median", "p90", "occupancy")}
                                for mode, data in reference["summaries"].items()}}}

    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "assumptions.json"
        write_json(config, {"versions": versions, "rides": release, "driveProfileDigest": report["driveProfileDigest"],
                            "evidence": EVIDENCE, "patience": 900, "walkMetresPerMinute": 80, **baseline})

        def build(folder):
            command = ["node", "scripts/vancouver_dispatch.mjs", ride_file, config,
                       root / "cityday" / day / "places.json", root / "streets" / streets / "network.json",
                       speed, folder, *parent_files]
            subprocess.run(command, check=True)

        version = package(root, "hired-dispatch", build)
        with tempfile.TemporaryDirectory(dir=family) as staging:
            pointer = Path(staging) / "pointer.json"
            write_json(pointer, {"version": version})
            pointer.replace(family / (release + ".json"))
        print(root, release, version, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--region", action="store_true")
    parser.add_argument("--day")
    parser.add_argument("--clock", help="Use the spread departure clock or a pinned departure clock version")
    args = parser.parse_args()
    publish(args.data, args.region, args.day, args.clock)
