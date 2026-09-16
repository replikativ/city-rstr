#!/usr/bin/env python3
"""Stuttgart Kleinräumige Gliederung → JSONL of areas in WGS84.
usage: stuttgart_klgl.py GPKG OUT.jsonl"""
import sys, json, duckdb
gpkg, out = sys.argv[1], sys.argv[2]
con = duckdb.connect(); con.execute("INSTALL spatial; LOAD spatial;")
layers = {"KLGL_BRUTTO_STADTBEZIRK": ("stadtbezirk", "STADTBEZIRKNR", "STADTBEZIRKNAME", None),
          "KLGL_BRUTTO_STADTTEIL": ("stadtteil", "STADTTEILNR", "STADTTEILNAME", "STADTBEZIRKNR"),
          "KLGL_BRUTTO_BAUBLOCK": ("baublock", "BAUBLOCKNR", None, None)}
srid = None
for l in con.execute(f"SELECT unnest(layers) FROM st_read_meta('{gpkg}')").fetchall():
    d = l[0]
    if d["name"] == "KLGL_BRUTTO_STADTBEZIRK":
        try: srid = d["geometry_fields"][0]["crs"]["auth_code"]
        except Exception: srid = None
srid = srid or "25832"
n = 0
with open(out, "w") as f:
    for layer, (level, nrcol, namecol, parentcol) in layers.items():
        cols = [nrcol] + ([namecol] if namecol else []) + ([parentcol] if parentcol else [])
        q = f"SELECT {', '.join(cols)}, ST_AsGeoJSON(ST_Transform(SHAPE, 'EPSG:{srid}', 'EPSG:4326', always_xy := true)) FROM st_read('{gpkg}', layer='{layer}')"
        for r in con.execute(q).fetchall():
            rec = {"level": level, "nr": str(r[0]), "name": r[1] if namecol else None,
                   "parent_nr": str(r[1 + (1 if namecol else 0)]) if parentcol else None,
                   "geometry": json.loads(r[-1])}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); n += 1
print("areas:", n, "srid:", srid)
