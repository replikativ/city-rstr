"""Offline cartography for the Vancouver population atlas, independent of its population coverage."""
import json
from pathlib import Path

import duckdb

# A little adjacent land makes the peninsula, inlets and river readable at city scale.
FRAME = (-123.280, 49.185, -123.004, 49.331)
PARKS = Path(__file__).resolve().parents[1] / "public/data/vancouver/parks.geojson"


def prepare_parks(source):
    """Reduce the municipal park polygons to a city-scale offline reference layer."""
    features = []
    with duckdb.connect() as db:
        db.execute("LOAD spatial")
        for item in json.loads(source.read_text())["features"]:
            if not item["geometry"]:
                continue
            geometry, = db.execute("""
                SELECT ST_AsGeoJSON(ST_Transform(ST_SimplifyPreserveTopology(
                    ST_Transform(ST_GeomFromGeoJSON(?), 'EPSG:4326','EPSG:26910',always_xy := true), 3),
                    'EPSG:26910','EPSG:4326',always_xy := true))
            """, [json.dumps(item["geometry"])]).fetchone()
            rounded = json.loads(geometry, parse_float=lambda x: round(float(x), 5))
            features.append({"type":"Feature","properties":{"name":item["properties"]["park_name"]},
                             "geometry":rounded})
    PARKS.parent.mkdir(parents=True, exist_ok=True)
    PARKS.write_text(json.dumps({"type":"FeatureCollection","features":features}, separators=(",",":")))


def basemap(raw,frame=FRAME,ways=None):
    shapefile = raw/"statcan/lda_000b21a_e.shp"
    with duckdb.connect() as db:
        db.execute("LOAD spatial")
        coast, = db.execute("""
            WITH frame AS (SELECT ST_MakeEnvelope(?, ?, ?, ?) AS geo),
            bounds AS (SELECT geo, ST_Envelope(ST_Transform(geo, 'EPSG:4326', 'EPSG:3347',
                                                             always_xy := true)) AS projected FROM frame),
            local AS (
                SELECT ST_Intersection(ST_MakeValid(d.geom), b.projected) AS geom
                FROM ST_Read(?) AS d, bounds AS b
                WHERE d.PRUID='59' AND ST_Intersects(d.geom, b.projected)
            ),
            merged AS (SELECT ST_SimplifyPreserveTopology(ST_Union_Agg(geom), 10) AS geom FROM local)
            SELECT ST_AsGeoJSON(ST_Intersection(b.geo, ST_Transform(m.geom,'EPSG:3347','EPSG:4326',
                                                                     always_xy := true)))
            FROM merged AS m, bounds AS b
        """, [*frame,str(shapefile)]).fetchone()
    land = json.loads(coast)
    if land["type"] not in {"MultiPolygon","Polygon"}:
        raise ValueError("Expected census cartographic land polygons")
    if ways is None:ways = json.loads((raw/"osm-overpass/vancouver_highways.json").read_text())["elements"]
    roads = {"street":[],"arterial":[],"bridge":[]}
    major = {"motorway","trunk","primary","secondary"}
    local = {"tertiary","residential","unclassified","living_street"}
    west,south,east,north = frame
    for way in ways:
        tags = way.get("tags",{})
        road = tags.get("highway")
        if road not in major and road not in local:
            continue
        pts = [(round(p["lon"],5),round(p["lat"],5)) for p in way["geometry"]]
        if any(west <= x <= east and south <= y <= north for x,y in pts):
            key = "arterial" if road in major else "street"
            if tags.get("bridge") not in (None,"no") and road in major:
                key = "bridge"
            roads[key].append(pts)
    return {"frame":frame,"land":land,"roads":roads}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=prepare_parks.__doc__)
    parser.add_argument("parks_export", type=Path)
    prepare_parks(parser.parse_args().parks_export)
