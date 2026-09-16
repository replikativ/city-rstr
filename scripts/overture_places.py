#!/usr/bin/env python3
"""Extract Overture Maps Places for a bbox to JSON lines.
usage: overture_places.py RELEASE WEST SOUTH EAST NORTH OUT.jsonl"""
import sys, json, duckdb
release, west, south, east, north, out = sys.argv[1:7]
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2';")
q = f"""
SELECT id, names.primary AS name, categories.primary AS category, categories.alternate AS alt_categories,
       confidence, websites, socials, phones, emails, brand.names.primary AS brand,
       addresses[1].freeform AS address, addresses[1].locality AS locality, addresses[1].postcode AS postcode,
       ST_X(geometry) AS lon, ST_Y(geometry) AS lat, sources[1].dataset AS source_dataset
FROM read_parquet('s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*', hive_partitioning=1)
WHERE bbox.xmin BETWEEN {west} AND {east} AND bbox.ymin BETWEEN {south} AND {north}
"""
rows = con.execute(q).fetchall()
cols = [d[0] for d in con.description]
with open(out, "w") as f:
    for r in rows:
        d = dict(zip(cols, r))
        for k in ("websites", "socials", "phones", "emails", "alt_categories"):
            v = d.get(k)
            d[k] = list(v) if v is not None else None
        f.write(json.dumps(d, default=str) + "\n")
print(len(rows))
