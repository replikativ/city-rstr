"""Count the routed resident drives and scheduled buses in the combined municipal weekday."""
import argparse
import hashlib
from pathlib import Path

import numpy as np

from scripts.vancouver_bridge_layers import buses
from scripts.vancouver_bridge_traffic import ARCHIVE, IRONWORKERS_FILE, resident_legs, score_window
from scripts.vancouver_incoming_road_crossings import BRIDGES, road_screens
from scripts.vancouver_region import read
from scripts.vancouver_transit_commutes import pointer


def publish(root, archive, joint_id, fit_id, ironworkers):
    joint = read(root/"joint-weekday"/joint_id/"report.json")
    incoming = read(root/"incoming-drives"/f"{fit_id}.json")
    if (incoming["joint"], incoming["homeFit"], incoming["workerRelease"], incoming["basis"]) != (
            joint_id, fit_id, joint["commuters"], "free-flow"):
        raise ValueError("The resident and incoming drivers use different combined weekdays")
    versions = joint["versions"]
    work = joint["workplaces"]
    roads = root/"commuter-drive"/incoming["network"]
    network, profile = [read(roads/f"{name}.json") for name in ("network", "profile")]
    day = root/"cityday"/versions["day"]
    das = read(day/"day.json")["das"]
    places = [row[:2] for row in read(day/"places.json")]
    counters = archive/"data/raw/probes"/ARCHIVE
    sites, arcs = road_screens(network, counters, ironworkers)
    inputs = dict(versions, outbound=work["outbound"], worksites=work["worksites"], tracts=work["tract-workplaces"])
    legs = resident_legs(root, inputs, fitted=True)
    external = legs[:, -1] == 1
    if np.any(external & np.all(legs[:, 1:3] >= 0, axis=1)):
        raise ValueError("An unresolved external workplace has supposedly located drive endpoints")
    scenarios = ("residentWork", "residentOther")
    print(f"Checking road screens against {len(legs):,} recorded all-driving trips.", flush=True)
    coverage, searches = score_window(legs[:, :7], places, network, sites, das, scenarios=len(scenarios),
                                      profile=profile, arcs=arcs, elapsed=True)
    layers = {key: dict(row, external=int(np.sum(external & (legs[:, 0] == 1 << i))))
              for i, (key,row) in enumerate(zip(scenarios, coverage, strict=True))}
    if sum(row["legs"] for row in layers.values()) != len(legs):
        raise ValueError("The resident purposes do not partition all driving trips")
    bridge_cuts = [s["point"] for s in sites[:len(BRIDGES)]]
    eastern_cuts = [s["point"] for s in sites[len(BRIDGES):]]
    schedule = buses(root/"transit"/joint["transit"], bridge_cuts, eastern_cuts)
    for site, bus_site in zip(sites, schedule.pop("sites"), strict=True):
        site["layers"] = dict(zip(scenarios, site.pop("scenarios"), strict=True))
        site["layers"]["buses"] = bus_site["counts"]
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (counters, ironworkers)}
    report = dict(joint=joint_id, versions=versions, workplaces=work, network=incoming["network"], clock=incoming["basis"],
                  timetable=joint["transit"], schedule=schedule, sites=sites, coverage=layers, sources=sources)
    pointer(root/"resident-road-crossings"/f"{joint_id}.json", report)
    print("Screen audit", searches, layers, "scheduled bus routes", len(schedule["routes"]), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("joint")
    parser.add_argument("fit")
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--ironworkers", type=Path, default=Path("data/mobility")/IRONWORKERS_FILE)
    args = parser.parse_args()
    publish(args.root, args.archive, args.joint, args.fit, args.ironworkers)
