"""Publish a paired taxi and ride-hail replay for Vancouver-resident diary trips."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile

from scripts.vancouver_atlas import write_json
from scripts.vancouver_mobility import PRIORITY
from scripts.vancouver_region import package, read
from scripts.vancouver_trip_demand import linked_trips

EVIDENCE = {
    "city": {"share": 0.013, "year": 2025, "figure": 24,
             "url": "https://vancouver.ca/files/cov/2025-transportation-survey-report.pdf#page=51"},
    "split": {"taxi": 565000, "ridehail": 2800000, "month": "2025-03",
              "region": "Lower Mainland and Whistler",
              "url": "https://www.ptboard.bc.ca/data-newsletters/november-2025"},
}


def terms(diary, template):
    labels = {mode: mode for mode in PRIORITY}
    return [[start, duration, mode, display, a, b,
             all(episode[3] == display for episode in diary["episodes"]
                 if start <= episode[0] < start + duration)]
            for start, duration, mode, display, a, b, _, _ in linked_trips(diary, template, report=labels)]


def publish(city_root, regional, day_id):
    municipal = read(city_root / "cityday/current.json")
    city_atlas = read(city_root / "atlas" / municipal["atlas"] / "atlas.json")
    root = city_root / "region" if regional else city_root
    ptr = read(root / "current.json") if regional else municipal
    atlas_dir = root / "atlas" / ptr["atlas"]
    day_dir = root / "cityday" / (day_id or ptr.get("day", ptr.get("version")))
    atlas, day = read(atlas_dir / "atlas.json"), read(day_dir / "day.json")
    city_das = set(city_atlas["das"])
    missing_das = sorted(city_das - set(day["das"]))
    if not regional and missing_das:
        raise ValueError("The municipal weekday and atlas use different census geography")
    streets = ptr.get("streets") or read(root / "streets/current.json")["version"]
    speed = root / "drive-profile" / (streets + ".json")
    parents = {"atlas": atlas_dir.name, "day": day_dir.name, "streets": streets}
    family = root / "hired-rides"

    with tempfile.TemporaryDirectory() as tmp:
        inputs, candidates = Path(tmp) / "inputs.json", Path(tmp) / "candidates.json"
        write_json(inputs, {"das": [d for d in day["das"] if d in city_das],
                            "trips": [terms(d, t) for d, t in zip(atlas["templates"], day["templates"], strict=True)]})
        subprocess.run(["clojure", "-J-Xmx1g", "-M", "-m", "city.vancouver.hired-rides",
                        atlas_dir, day_dir, inputs, candidates], check=True)
        if not regional:
            extraction = read(candidates)["fifths"]
            mobility = read(day_dir / "mobility.json")["main"]
            if extraction["trips"] != round(5 * mobility["trips"]) or extraction["residents"] != round(5 * mobility["people"]):
                raise ValueError("Hired-ride extraction disagrees with the weekday mobility totals")
        write_json(inputs, {"versions": parents, "evidence": EVIDENCE, "missingCityAreas": missing_das,
                            "driveProfileDigest": hashlib.sha256(speed.read_bytes()).hexdigest()})

        def build(folder):
            subprocess.run(["node", "scripts/vancouver_hired_routes.mjs", candidates, inputs, day_dir / "places.json",
                            root / "streets" / streets / "network.json", speed, folder / "rides.json"], check=True)

        version = package(root, "hired-rides", build)
        with tempfile.TemporaryDirectory(dir=family) as staging:
            pointer = Path(staging) / "pointer.json"
            write_json(pointer, {"version": version})
            pointer.replace(family / ("_".join(parents.values()) + ".json"))
        print(root, version, read(family / version / "rides.json")["counts"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--region", action="store_true")
    parser.add_argument("--day")
    args = parser.parse_args()
    publish(args.data, args.region, args.day)
