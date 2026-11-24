"""Publish direction-specific road speed assumptions aligned to an immutable street graph."""
import argparse
from collections import Counter
import hashlib
from pathlib import Path
import re
import tempfile

from scripts.vancouver_atlas import write_json
from scripts.vancouver_region import read, rows
from scripts.vancouver_streets import encode_way, permissions

DEFAULTS = {
    "motorway": 80, "motorway_link": 50, "trunk": 60, "trunk_link": 40,
    "primary": 50, "primary_link": 40, "secondary": 50, "secondary_link": 40,
    "tertiary": 40, "tertiary_link": 30, "unclassified": 40,
    "residential": 30, "living_street": 20, "service": 20,
}


def posted(value):
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(km/h|kmh|kph|mph)?", (value or "").strip(), re.IGNORECASE)
    if not match:
        return None
    value = float(match[1]) * (1.609344 if (match[2] or "").lower() == "mph" else 1)
    return round(value, 2) if 5 <= value <= 130 else None


def direction_speeds(tags, bits, use):
    speeds = []
    for bit, direction in ((2, "forward"), (4, "backward")):
        if not bits & bit:
            speeds.append(0)
            continue
        speed = posted(tags.get("maxspeed:" + direction)) or posted(tags.get("maxspeed"))
        use["posted" if speed else "byClass"] += 1
        speeds.append(speed or DEFAULTS[tags["highway"]])
    return speeds


def build(streets, roads):
    nodes, ids, names, speeds = [], {}, {}, []
    use = Counter()
    ordered = iter(streets["ways"])
    for way in roads:
        tags = way.get("tags", {})
        bits = permissions(tags)
        if not bits or len(way.get("nodes", [])) < 2:
            continue
        if next(ordered, None) != encode_way(way, bits, nodes, ids, names):
            raise ValueError("Road inventory does not match the released street graph")
        speeds.append(direction_speeds(tags, bits, use))
    if next(ordered, None) is not None or nodes != streets["nodes"] or list(names) != streets["names"]:
        raise ValueError("Speed profile and street release have different coverage")
    return dict(kmh=speeds, connectorKmh=22.8, connectorMetres=500,
                coverage=dict(use), defaults=DEFAULTS)


def publish(root, version, source, regional):
    streets = read(root/"streets"/version/"network.json")
    roads = rows(source) if regional else read(source)["elements"]
    profile = build(streets, roads)
    profile["streets"] = version
    with source.open("rb") as stream:
        profile["sourceDigest"] = hashlib.file_digest(stream, "sha256").hexdigest()
    parent = root/"drive-profile"
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as tmp:
        output = Path(tmp)/"profile.json"
        write_json(output, profile)
        output.replace(parent/(version+".json"))
    print(root, version, profile["coverage"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--inputs", type=Path, default=Path("data/region"))
    args = parser.parse_args()
    publish(args.data, read(args.data/"streets/current.json")["version"],
            args.archive/"data/raw/osm-overpass/vancouver_highways.json", False)
    region = args.data/"region"
    publish(region, read(region/"current.json")["streets"], args.inputs/"work/roads.jsonl", True)
