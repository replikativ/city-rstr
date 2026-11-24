"""Extend the replay's offline cartography across the archived metro routing graph."""
import argparse
from pathlib import Path

from scripts.vancouver_basemap import basemap
from scripts.vancouver_commuter_coverage import road_sections
from scripts.vancouver_outbound_road_jobs import digest
from scripts.vancouver_region import read
from scripts.vancouver_transit_commutes import pointer


def publish(root, archive, pbf, network):
    road = read(root/"commuter-drive"/network/"report.json")
    if digest(pbf)!=road["sourceDigest"]:
        raise ValueError("The basemap and routes must use the same street archive")
    major = {"motorway", "trunk", "primary", "secondary"}
    ways = (dict(tags=tags,geometry=[dict(lon=x,lat=y) for x,y in zip(lons,lats,strict=True)])
            for tags,_,lons,lats in road_sections(pbf,road["bounds"]) if tags.get("highway") in major)
    context = basemap(archive/"data/raw",road["bounds"],ways)
    pointer(root/"commuter-basemap"/f"{network}.json",dict(context,network=network))
    print(network,{kind:len(lines) for kind,lines in context["roads"].items()},flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path)
    parser.add_argument("network")
    parser.add_argument("--root",type=Path,default=Path("public/data/vancouver"))
    parser.add_argument("--pbf",type=Path,default=Path("data/region/vancouver.osm.pbf"))
    args=parser.parse_args()
    publish(args.root,args.archive,args.pbf,args.network)
