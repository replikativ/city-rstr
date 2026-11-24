"""Publish minute arrivals at the Burrard Inlet bridges before any capacity constraint."""
import argparse
from pathlib import Path

import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_bridge_layers import BRIDGES
from scripts.vancouver_bridge_traffic import resident_legs, road_profile, score
from scripts.vancouver_flexible_transit import WORKPLACE_RUN
from scripts.vancouver_region import package, read
from scripts.vancouver_regional_inbound import driver_legs
from scripts.vancouver_transit_commutes import pointer

CAPACITIES = {
    "LionsGateBridge": dict(byLanes={"1": 1500, "2": 3500},
                            source="https://www2.gov.bc.ca/assets/gov/driving-and-transportation/reports-and-reference/reports-and-studies/lower-mainland/lions_gate_hwy1_connector_planning_study_summary.pdf",
                            operations="https://www.youtube.com/watch?v=EHlODJNkx6o"),
    "Ironworkers": dict(byLanes={"2": 3400, "3": 5100},
                        source="https://www.highway99tunnel.ca/app/uploads/sites/748/2023/06/APPENDIX-H-Traffic-and-Geometrics-Part-1.pdf"),
}


def count_path(root, family, versions):
    folder = root/family
    key = "_".join(versions[k] for k in ("atlas", "day", "streets"))
    index = read(folder/(key+"_time.json"))
    return index["version"], read(folder/index["version"]/"counts.json")


def minute_counts(legs, places, network, das, profile, reference):
    sites = [dict(name=name) for _, name, *_ in BRIDGES]
    score(legs, places, network, sites, das, bridges=BRIDGES, scenarios=1, profile=profile, minute_counts=True)
    result = {}
    for (key, *_), site in zip(BRIDGES, sites, strict=True):
        scenario, = site["scenarios"]
        minutes = np.asarray(scenario["minutes"])
        hourly = np.roll(minutes.reshape((2, 24, 60)).sum(axis=-1), 4, axis=1).tolist()
        if hourly != reference[key]["counts"] or hourly != scenario["counts"]:
            raise ValueError(f"Minute demand does not reconcile to the archived {key} counts")
        result[key] = scenario["minutes"]
    return result


def publish(root, workplace_run):
    workplace = read(root/"regional-workplaces"/workplace_run/"report.json")
    versions = {k: workplace["versions"][k] for k in ("atlas", "streets")}
    versions["day"] = workplace["day"]
    incoming = {**versions, "day": workplace["incomingDay"]}
    resident_id, resident = count_path(root, "bridge-traffic", versions)
    incoming_id, inbound = count_path(root, "incoming-bridges", incoming)
    graph = read(root/"streets"/versions["streets"]/"network.json")
    profile, routing = road_profile(root, versions["streets"], "time")
    if any(report["routing"]["profileDigest"] != routing["profileDigest"] for report in (resident, inbound)):
        raise ValueError("Minute demand uses different free-flow road speeds")
    day_dir = root/"cityday"/versions["day"]
    day = read(day_dir/"day.json")
    places = [p[:2] for p in read(day_dir/"places.json")]
    local = minute_counts(resident_legs(root, versions), places, graph, day["das"], profile,
                          {site["key"]: site["scenarios"][0] for site in resident["sites"]})
    places, legs, groups, _ = driver_legs(root, incoming, inbound["workerRelease"])
    external = minute_counts(legs, places, graph, groups, profile, inbound["sites"])
    report = dict(schema=1, versions=versions, workplaceRun=workplace_run, start=240, capacities=CAPACITIES,
                  roads=routing, residents=local, incoming=external, sourceReleases=[resident_id, incoming_id])
    family = "bridge-demand"
    release = package(root, family, lambda out: write_json(out/"arrivals.json", report))
    key = "_".join(versions[k] for k in ("atlas", "day", "streets"))
    pointer(root/family/(key+".json"), {"version": release})
    print(release, {key: [sum(map(sum, local[key])), sum(map(sum, external[key]))] for key, *_ in BRIDGES}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--workplace-run", default=WORKPLACE_RUN)
    args = parser.parse_args()
    publish(args.region, args.workplace_run)
