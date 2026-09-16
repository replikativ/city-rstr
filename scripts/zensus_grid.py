#!/usr/bin/env python3
"""Zensus 2022 100 m grid cells for a WGS84 bbox → JSONL (one row per cell,
joined across the downloaded tables, with cell centre in WGS84).
usage: zensus_grid.py RAWDIR/zensus2022 OUT.jsonl WEST SOUTH EAST NORTH"""
import sys, os, glob, subprocess, duckdb
zdir, out = sys.argv[1], sys.argv[2]
west, south, east, north = map(float, sys.argv[3:7])
for z in glob.glob(os.path.join(zdir, "*.zip")):
    subprocess.run(["unzip", "-nq", z, "-d", zdir], check=True)
csvs = [p for p in glob.glob(os.path.join(zdir, "**", "*100m*.csv"), recursive=True)]
con = duckdb.connect(); con.execute("INSTALL spatial; LOAD spatial;")
# bbox to EPSG:3035
(x0, y0), (x1, y1) = [con.execute(f"SELECT ST_X(p), ST_Y(p) FROM (SELECT ST_Transform(ST_Point({lon}, {lat}), 'EPSG:4326', 'EPSG:3035', always_xy := true) p)").fetchone() for lon, lat in ((west, south), (east, north))]
tables = []
for i, c in enumerate(csvs):
    t = f"t{i}"
    con.execute(f"""CREATE TABLE {t} AS SELECT * FROM read_csv('{c}', delim=';', header=true, all_varchar=true, ignore_errors=true)
                    WHERE TRY_CAST(x_mp_100m AS DOUBLE) BETWEEN {x0} AND {x1} AND TRY_CAST(y_mp_100m AS DOUBLE) BETWEEN {y0} AND {y1}""")
    cols = [r[0] for r in con.execute(f"DESCRIBE {t}").fetchall()]
    idcol = [k for k in cols if k.upper().startswith("GITTER_ID")][0]
    con.execute(f"ALTER TABLE {t} RENAME {idcol} TO gid")
    tables.append((t, [k for k in cols if k not in (idcol, "x_mp_100m", "y_mp_100m")]))
    print(os.path.basename(c), con.execute(f"SELECT count(*) FROM {t}").fetchone()[0], "cells")
# base = the table with the most cells (population), so nothing is dropped by the join
base = max(tables, key=lambda t: con.execute(f"SELECT count(*) FROM {t[0]}").fetchone()[0])[0]
sel = ", ".join(f'{t}."{k}" AS "{k}"' for t, ks in tables for k in ks)
joins = " ".join(f"LEFT JOIN {t} USING (gid)" for t, _ in tables if t != base)
con.execute(f"""CREATE TABLE cells AS
SELECT {base}.gid, TRY_CAST({base}.x_mp_100m AS DOUBLE) AS x, TRY_CAST({base}.y_mp_100m AS DOUBLE) AS y, {sel} FROM {base} {joins}""")
con.execute("""CREATE TABLE cells2 AS SELECT *, ST_X(p) AS lon, ST_Y(p) AS lat FROM
  (SELECT *, ST_Transform(ST_Point(x, y), 'EPSG:3035', 'EPSG:4326', always_xy := true) AS p FROM cells)""")
con.execute(f"COPY (SELECT * EXCLUDE (p) FROM cells2) TO '{out}' (FORMAT JSON)")
print("cells:", con.execute("SELECT count(*) FROM cells2").fetchone()[0])
