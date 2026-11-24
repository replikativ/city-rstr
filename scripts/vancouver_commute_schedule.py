"""Publish the regional work commute check against Statistics Canada Table 98-10-0479."""
import argparse
import csv
import hashlib
import io
from pathlib import Path
import subprocess
import tempfile
from zipfile import ZipFile

from scripts.vancouver_atlas import write_json
from scripts.vancouver_region import NAMES, package, read

TABLE = Path("data/mobility/98100479-eng.zip")
SOURCE = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810047901"
PLACES = {"5915022": "Vancouver", **NAMES}
MODES = (
    ("All modes", (1,)), ("Car driver", (3,)), ("Car passenger", (7,)),
    ("Public transit", (12,)), ("Walking", (18,)), ("Cycling", (19,)), ("Other", (20, 21)),
)
DEPARTURES = ("05:00–05:59", "06:00–06:59", "07:00–07:59", "08:00–08:59", "09:00–11:59", "12:00–04:59")
DURATIONS = ("Under 15 min", "15–29 min", "30–44 min", "45–59 min", "60 min or more")
USUAL = "Place of work status (3A):Usual place of work[3]"


def census_schedule(path):
    geo = {"2021A0005" + code: name for code, name in PLACES.items()}
    expected = {(time, duration, mode) for time in range(1, 8) for duration in range(1, 7)
                for _, members in MODES for mode in members}
    cells = {name: {} for name in geo.values()}
    with ZipFile(path) as archive, archive.open("98100479.csv") as entry:
        rows = csv.reader(io.TextIOWrapper(entry, encoding="utf-8-sig"))
        header = next(rows)
        year, dguid, coordinate, value = map(header.index, ("REF_DATE", "DGUID", "Coordinate", USUAL))
        if header[value + 1] != "Symbol":
            raise ValueError("Missing workplace status symbols in the census extract")
        for row in rows:
            if len(row) <= dguid:
                continue
            name = geo.get(row[dguid])
            if name is None:
                continue
            _, t, d, m = map(int, row[coordinate].split("."))
            cell = t, d, m
            if cell not in expected:
                continue
            if row[year] != "2021" or cell in cells[name]:
                raise ValueError("Unexpected year or repeated commute census cell")
            cells[name][cell] = None if row[value + 1] or not row[value] else int(row[value])
    for name, values in cells.items():
        if values.keys() != expected or not values[1, 1, 1]:
            raise ValueError("Incomplete commute census table for " + name)

    def merge(values):
        return None if any(n is None for n in values) else sum(values)

    def cube(values):
        return [[[merge([values[t, d, m] for m in members]) for d in range(1, 7)]
                 for t in range(1, 8)] for _, members in MODES]

    shore = {cell: merge([cells[name][cell] for name in NAMES.values()]) for cell in expected}
    return dict(source=SOURCE, census={"North Shore": cube(shore), **{name: cube(v) for name, v in cells.items()}},
                labels=dict(modes=[label for label, _ in MODES], departures=DEPARTURES, durations=DURATIONS))


def publish(region, table, day_ids):
    geography = read(region / "current.json")
    atlas = region / "atlas" / geography["atlas"]
    source = census_schedule(table)
    with table.open("rb") as stream:
        source["digest"] = hashlib.file_digest(stream, "sha256").hexdigest()
    folder = region / "commute-schedule"
    with tempfile.TemporaryDirectory() as tmp:
        inputs = Path(tmp) / "census.json"
        write_json(inputs, source)
        for day_id in day_ids or [geography["day"]]:
            day = region / "cityday" / day_id

            def build(directory):
                subprocess.run(["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.commute-schedule",
                                atlas, day, inputs, directory / "report.json"], check=True)

            version = package(region, "commute-schedule", build)
            with tempfile.TemporaryDirectory(dir=folder) as temp:
                pointer = Path(temp) / "pointer.json"
                write_json(pointer, {"version": version})
                pointer.replace(folder / f"{atlas.name}_{day_id}.json")
            print(day_id, version, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--census", type=Path, default=TABLE)
    parser.add_argument("--day", action="append", help="Existing regional weekday (repeat to build several)")
    args = parser.parse_args()
    publish(args.region, args.census, args.day)
