"""Rebuild the resident weekday's shared layers for an income-fitted atlas."""
import argparse
from pathlib import Path

from scripts import (
    vancouver_inbound, vancouver_joint_weekday, vancouver_outbound, vancouver_pedestrians,
    vancouver_shopping_outings, vancouver_short_walks, vancouver_survey_zones, vancouver_tract_scenario, vancouver_trip_demand,
    vancouver_worksites,
)
from scripts.vancouver_region import read


def publish(root, archive, data, fitted, backend, transfers=False, *, preserve_modes=False, capacity=False,
            tract_release=None, reuse_riders_from=None):
    fit = read(root/"diary-fit"/(fitted+".json"))
    versions = fit["locations"]
    atlas, day, streets = (versions[k] for k in ("atlas","day","streets"))
    reference = dict(atlas=atlas,version=day)
    if fitted!=atlas or read(root/"streets/current.json")["version"]!=streets:
        raise ValueError("The fitted weekday requires its published street network")
    key = f"{atlas}_{day}"
    outbound_pointer = root/"outbound"/(key+".json")
    outbound = (read(outbound_pointer)["version"] if outbound_pointer.is_file() else
                vancouver_outbound.publish(archive,root,data/"98100462-eng.zip",backend,reference))
    worksite_pointer = root/"worksites"/(outbound+".json")
    worksites = (read(worksite_pointer)["version"] if worksite_pointer.is_file() else
                 vancouver_worksites.publish(root,reference))
    suffix = "_diary_modes.json" if preserve_modes else ".json"
    if tract_release is None and not (root/"tract-workplaces"/(worksites+suffix)).is_file():
        vancouver_tract_scenario.publish(root,data,archive,reference,preserve_modes=preserve_modes)
    if not (root/"survey-zones"/(worksites+".json")).is_file():
        print("Trips within the home zone",vancouver_survey_zones.publish(root,data/"taz-gvrd.geojson",versions),flush=True)

    if not (root/"short-walks"/f"{day}_{streets}.json").is_file():
        vancouver_short_walks.publish(root,atlas,day,streets)
    if not (root/"trip-demand"/(key+".json")).is_file():
        print("Trip demand",vancouver_trip_demand.publish(root,data/"taz-gvrd.geojson",day,atlas),flush=True)
    if not (root/"commuters"/(key+".json")).is_file():
        print("Incoming workers",vancouver_inbound.publish(archive,root,backend,day=reference),flush=True)
    if not (root/"pedestrians"/f"{day}_{streets}.json").is_file():
        vancouver_pedestrians.publish(archive,root,verify=True,versions=versions)
    if not (root/"discretionary-outings"/(key+".json")).is_file():
        vancouver_shopping_outings.publish(root,archive,backend,versions)
    return vancouver_joint_weekday.publish(root,archive,transfers=transfers,versions=versions,
                                           preserve_modes=preserve_modes,capacity=capacity,tract_release=tract_release,
                                           reuse_riders_from=reuse_riders_from)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path)
    parser.add_argument("fitted_atlas")
    parser.add_argument("--root",type=Path,default=Path("public/data/vancouver"))
    parser.add_argument("--data",type=Path,default=Path("data/mobility"))
    parser.add_argument("--backend",default="jvm")
    parser.add_argument("--transfers",action="store_true")
    parser.add_argument("--preserve-modes",action="store_true",help="keep fitted diary travel modes in the workplace scenario")
    parser.add_argument("--capacity",action="store_true",help="limit bookings to available bus capacity")
    parser.add_argument("--tract-release",help="use a pinned tract workplace layout")
    parser.add_argument("--reuse-riders-from",help="reuse bookings from a published combined weekday after checking every window")
    args=parser.parse_args()
    publish(args.root,args.archive,args.data,args.fitted_atlas,args.backend,args.transfers,
            preserve_modes=args.preserve_modes,capacity=args.capacity,tract_release=args.tract_release,
            reuse_riders_from=args.reuse_riders_from)
