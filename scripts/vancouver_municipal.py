"""Prepare the municipal population inputs from the 2021 Census subdivision hierarchy."""
import json

import duckdb

from scripts.vancouver_census_geography import CITY, DA, area_membership, compare, profile_cells
from scripts.vancouver_atlas import ROSTER_CELLS, neighbourhood_geometry


def prepare(archive, out, geographic):
    raw = archive/"data/raw/statcan"
    ids = list(area_membership(raw, {CITY[-7:]}))
    cells = profile_cells(raw, {CITY} | {DA+d for d in ids}, ROSTER_CELLS, columns=(11,13,15))
    _, points, boundary = compare(ids, geographic, CITY[-7:],
                                  profile_population={d: cells[DA+d][1][0] for d in ids})
    if boundary["adjacent"] or boundary["missing"]:
        raise ValueError("Census Profile index and Geographic Attribute File disagree on municipal membership")
    neighbourhoods = neighbourhood_geometry(archive)
    # Use the same municipal neighbourhood polygons as the atlas. Representatives on
    # an edge use the greatest overlapping land area, then the neighbourhood name.
    with duckdb.connect() as db:
        db.execute("LOAD spatial")
        db.execute("create table ids (da varchar, lon double, lat double)")
        db.executemany("insert into ids values (?, ?, ?)", [(d, *p) for d,p in zip(ids, points, strict=True)])
        db.execute("create table areas (name varchar, g geometry)")
        db.executemany("insert into areas values (?, ST_GeomFromGeoJSON(?))",
                       [(name, json.dumps(shape)) for name, shape in neighbourhoods.items()])
        db.execute("""create temporary table bounds as select ids.*, ST_Transform(ST_MakeValid(s.geom),
                   'EPSG:3347','EPSG:4326',always_xy:=true) g from ST_Read(?) s join ids on DAUID=da""",
                   [str(raw/"lda_000b21a_e.shp")])
        geos = dict(db.execute("select da, ST_AsGeoJSON(g) from bounds").fetchall())
        grouped = db.execute("""select b.da, a.name from bounds b join areas a
                  on ST_Intersects(b.g,a.g)
                  qualify row_number() over (partition by b.da order by
                  ST_Covers(a.g, ST_Point(b.lon,b.lat)) desc,
                  ST_Area(ST_Transform(ST_Intersection(a.g,b.g), 'EPSG:4326', 'EPSG:3347', always_xy:=true)) desc, name)=1""").fetchall()
    names = dict(grouped)
    if set(names) != set(ids) or set(geos) != set(ids):
        raise ValueError("Missing census boundaries or municipal neighbourhoods")
    with (out/"vancouver_da_boundaries.jsonl").open("w") as f:
        for d in ids:
            f.write('{"dauid":"'+d+'","geometry":'+geos[d]+'}\n')
    for key in (1,5):
        if sum(cells[DA+d][key][0] for d in ids) != cells[CITY][key][0]:
            raise ValueError("Municipal and dissemination-area census totals disagree")
    if cells[CITY][1][0] != boundary["municipalPopulation"]:
        raise ValueError("Census Profile population differs from the geographic hierarchy")
    with (out/"vancouver_da_marginals.jsonl").open("w") as f:
        for d in ids:
            f.write(json.dumps(dict(dauid=d, local_area=names[d], m=cells[DA+d]), separators=(",", ":"))+"\n")
    return boundary
