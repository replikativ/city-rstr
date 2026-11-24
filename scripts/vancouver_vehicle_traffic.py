"""Apply the exact vehicle-access routes to the combined Downtown comparisons."""
import argparse
from collections import defaultdict
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_downtown import MODE_INDEX, station_counts
from scripts.vancouver_mobility import PRIORITY, REPORT
from scripts.vancouver_region import read
from scripts.vancouver_street_scenarios import VEHICLE_ACCESS
from scripts.vancouver_transit_commutes import pointer


def project(root, archive, version):
    family = root / VEHICLE_ACCESS
    model = family / version
    vehicle = read(model / "report.json")
    joint = read(root / "joint-weekday" / vehicle["joint"] / "report.json")
    if vehicle["versions"] != dict(joint["versions"], transit=joint["transit"]):
        raise ValueError("The vehicle assignment and Downtown comparison use different inputs")
    rider_dir = root / "transit-riders" / joint["riders"]
    original = read(rider_dir / "downtown.json")
    works = joint["workplaces"]
    short_rows, transit = [], defaultdict(list)
    for da in vehicle["areas"]:
        for row in read(model / (da + ".json")):
            short_rows.append(row[:7])
            _, person, start, duration, a, b, mode, payload, *_ = row
            if mode == "transit":
                transit[da].append([da, person, start, duration, a, b, *payload])
    if len(short_rows) != vehicle["stats"]["switchedTrips"]:
        raise ValueError("The assignment and Downtown projection have different trip counts")
    with tempfile.TemporaryDirectory(dir=family) as folder:
        request, replacements, result = (Path(folder) / name for name in ("inputs.json", "trips.json", "projection.json"))
        write_json(replacements, short_rows)
        write_json(request, dict(joint["versions"], outbound=works["outbound"], worksites=works["worksites"],
                                 tracts=works["tract-workplaces"], outings=joint["outings"], priority=PRIORITY,
                                 surveyModes=REPORT, vehicleTraffic=str(replacements)))
        subprocess.run(["node", "scripts/vancouver_joint_trips.mjs", root, request, result], check=True)
        changes = read(result)["traffic"]
    if changes["modes"][:-1] != list(MODE_INDEX):
        raise ValueError("Downtown travel modes are inconsistent")
    prior, delta = np.asarray(original["counts"]), np.asarray(changes["delta"])
    updated = prior + delta
    if np.any(updated < 0) or np.any(delta.sum(axis=-1)):
        raise ValueError("Vehicle access changed the number of trips arriving in or leaving Downtown")
    path = archive / "data/raw/probes/transit_translink_tspr2025_skytrainavgalightsbrdgs_yearstationdaytypehourly.csv"
    schedules = root / "transit" / joint["transit"]
    new_rail = station_counts(path, schedules, read(schedules / "transit.json"), transit)
    if new_rail["observed"] != original["rail"]["observed"]:
        raise ValueError("The matched station counts use another set of observations")
    matched = np.asarray(original["rail"]["matched"]) + np.asarray(new_rail["matched"])
    projection = dict(original, vehicleAccess=version, jointRelease=vehicle["joint"], counts=updated.tolist(),
                      rail=dict(original["rail"], matched=matched.tolist()))
    pointer(family / (version + "_downtown.json"), projection)
    print(version, "Downtown mode changes", int(np.sum(abs(delta)))//2,
          "additional station events", np.sum(new_rail["matched"], axis=0).tolist(), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("version")
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    args = parser.parse_args()
    project(args.root, args.archive, args.version)
