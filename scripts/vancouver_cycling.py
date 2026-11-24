"""Publish a directed cycling graph from the study area's archived OSM highway ways."""
import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from scripts.artifacts import package, write_json
from scripts.vancouver_region import rows
from scripts.vancouver_streets import DRIVE, encode_way

FORWARD, REVERSE = 8, 16
BIKE_ROADS = (DRIVE - {"motorway", "trunk", "motorway_link", "trunk_link"}) | {"cycleway", "track"}
OPEN = {"yes", "designated", "permissive", "official"}
ONE_WAY = {"yes", "true", "1"}


def directions(tags):
    kind = tags.get("highway")
    if tags.get("area") == "yes" or kind in {None, "construction", "proposed", "steps"}:
        return 0
    access = tags.get("bicycle", tags.get("vehicle", tags.get("access")))
    if access is not None and access not in OPEN:
        return 0
    if kind not in BIKE_ROADS and tags.get("bicycle") not in OPEN:
        return 0
    car_direction = tags.get("oneway", "yes" if tags.get("junction") == "roundabout" else "no")
    direction = tags.get("oneway:bicycle", car_direction)
    if "oneway:bicycle" not in tags and any(
        tags.get(key, "").startswith("opposite") for key in ("cycleway", "cycleway:left", "cycleway:right")
    ):
        direction = "no"
    forward = direction != "-1" and tags.get("bicycle:forward", "yes") in OPEN
    reverse = direction not in ONE_WAY and tags.get("bicycle:backward", "yes") in OPEN
    return (FORWARD if forward else 0) | (REVERSE if reverse else 0)


def publish(archive, root, *, regional_roads=None, streets=None):
    source = regional_roads or archive/"data/raw/osm-overpass/vancouver_highways.json"
    streets = streets or json.loads((root/"streets/current.json").read_bytes())["version"]
    def build(folder):
        nodes, ids, ways, names = [], {}, [], {}
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        ways_in = rows(source) if regional_roads else json.loads(source.read_bytes())["elements"]
        for way in ways_in:
            bits = directions(way.get("tags", {}))
            if bits and len(way.get("nodes", [])) >= 2:
                ways.append(encode_way(way, bits, nodes, ids, names))
        write_json(folder/"network.json", dict(nodes=nodes, ways=ways, names=list(names)))
        write_json(folder/"source.json", dict(streets=streets, sha256=digest,
                                              nodes=len(nodes), ways=len(ways), speedUnit="metres per minute"))
    version = package(root, "cycling", build)
    pointer = root/"cycling"/(streets+".json")
    with tempfile.TemporaryDirectory(dir=pointer.parent) as tmp:
        path = Path(tmp)/"pointer"
        write_json(path, {"version": version})
        path.replace(pointer)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--region", action="store_true")
    parser.add_argument("--inputs", type=Path, default=Path("data/region"))
    args = parser.parse_args()
    if args.region:
        root = args.data/"region"
        print(publish(args.archive, root, regional_roads=args.inputs/"work/roads.jsonl",
                      streets=json.loads((root/"current.json").read_bytes())["streets"]))
    else:
        print(publish(args.archive, args.data))
