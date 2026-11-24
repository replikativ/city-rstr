"""Compare license employment weights with the 2021 Census by tract of work."""
import argparse
import csv
import io
from pathlib import Path
import sys
import zipfile

import duckdb
import pandas as pd

from scripts.vancouver_cityday import licensed_jobs
from scripts.vancouver_survey_zones import ZONES


def census_counts(archive):
    with zipfile.ZipFile(archive) as z, z.open("98100498.csv") as raw:
        rows = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"))
        total = "Employment income groups (18):Total - Employment income[1]"
        result = {}
        for row in rows:
            tract = row["DGUID"]
            if tract.startswith("2021S0507933") and row["Place of work status (3)"] == "Usual place of work":
                if tract in result:
                    raise ValueError(f"Duplicate census tract {tract}")
                value = row[total]
                result[tract] = int(value) if value.isdigit() else None
        return result


def compare(data, city_archive):
    counts = census_counts(data / "98100498-eng.zip")
    jobs = licensed_jobs(city_archive / "data/raw/vancouver-ods")
    points = pd.DataFrame([(x, y, weight) for (x, y), weight in jobs.items()],
                          columns=["x", "y", "weight"])
    with duckdb.connect() as db:
        db.execute("load spatial")
        db.register("points", points)
        db.execute("""create temp table tracts as select DGUID as id,
            ST_Transform(geom, 'EPSG:4326', 'EPSG:26910', always_xy := true) as g
            from ST_Read(?)""", [str(data / "vancouver-tracts-2021.geojson")])
        if {r[0] for r in db.execute("select id from tracts").fetchall()} != set(counts):
            raise ValueError("Tract boundaries and workplace census rows differ")
        db.execute("""create temp table zones as select gh as code,
            ST_Union_Agg(ST_MakeValid(ST_Transform(geom, 'EPSG:4326', 'EPSG:26910', always_xy := true))) as g
            from ST_Read(?) where MUNI_1 = 'Vancouver' group by gh""", [str(data / "taz-gvrd.geojson")])
        tracts = db.execute("""select t.id, z.code from tracts t join zones z on ST_Intersects(t.g, z.g)
            where ST_Area(ST_Intersection(t.g, z.g)) >= 0.99 * ST_Area(t.g)""").fetchall()
        weights = dict(db.execute("""select t.id, sum(p.weight) from tracts t join
            (select ST_Transform(ST_Point(x,y), 'EPSG:4326', 'EPSG:26910', always_xy := true) as g,
                    weight from points) p on ST_Contains(t.g, p.g) group by t.id""").fetchall())
    result = []
    for code, name, *_ in ZONES:
        ids = [tract for tract, zone in tracts if zone == code]
        known = [i for i in ids if counts[i] is not None]
        result.append((name, len(known), len(ids) - len(known),
                       sum(counts[i] for i in known), int(sum(weights.get(i, 0) for i in known))))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("city_archive", type=Path)
    parser.add_argument("--data", type=Path, default=Path("data/mobility"))
    args = parser.parse_args()
    writer = csv.writer(sys.stdout)
    writer.writerow(["Zone", "Tracts with counts", "Suppressed tracts", "Usual workplace, 2021",
                     "Employees on issued city licences with positive counts and coordinates, 2025"])
    writer.writerows(compare(args.data, args.city_archive))
