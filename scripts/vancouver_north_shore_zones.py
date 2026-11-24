"""Recover North Shore survey zones from Figure 2 and join modeled locations."""
import json
from pathlib import Path
import subprocess
import tempfile

import duckdb
import numpy as np
import pandas as pd
from PIL import Image
from scipy.ndimage import distance_transform_edt, label

from scripts.vancouver_cityday import ORIGIN, SCALE

# Figure 2 on PDF page 15, raster 1416 × 704. The affine transform was fitted
# to the 2021 Census cartographic coastline for the three municipalities and
# four reserves in Table 2 in NAD83 / UTM zone 10N. Mean boundary error is
# 1.5 pixels and intersection over union is 0.990.
FIGURE_SEEDS = [(1140, 340), (873, 335), (729, 332), (425, 310),
                (525, 480), (681, 535), (790, 540), (869, 570)]
UTM_ORIGIN = [492868.386, 5464906.178]
PIXEL_MATRIX = [[41.90074, 0.00661], [0.04489, -41.62883]]
PIXEL_ORIGIN = [719.96375, 466.77478]

# Table 3 populations aged 15+. Table 54 entries are rounded estimates.
ZONES = [
    ("District of North Vancouver East", 23500),
    ("District of North Vancouver Central", 26200),
    ("District of North Vancouver West", 21100),
    ("West Vancouver West", 20600),
    ("West Vancouver Centre", 21500),
    ("North Vancouver / West Vancouver Outer", 14700),
    ("City of North Vancouver Core", 31100),
    ("City / District of North Vancouver East", 15500),
]
ZONE_NAMES = [f"Zone {i} · {name}" for i, (name, _) in enumerate(ZONES, 1)]
OBSERVED = [
    [1200, 700, 100, "<50", 100, 200, 400, "<100"],
    [200, 100, "<50", "<50", "<50", 200, 300, 100],
    [500, 600, 400, 600, 400, "<50", 700, 100],
    [100, 200, "<50", 200, "<100", 100, 100, "<100"],
    [400, 400, 500, 100, 800, 400, 1000, 600],
    [900, 700, 600, "<50", 800, 1600, 1700, 300],
    [1300, 1700, 900, 400, 400, 900, 1800, 700],
    [300, 100, "<100", "<50", 100, 200, 400, 300],
    [2300, 2400, 1600, 500, 1400, 1500, 5400, 800],
    [1700, 1400, 700, 500, 1000, 1700, 2700, 1100],
    [1300, 1300, 500, 200, 100, 300, 1540, 400],
    ["<100", "<50", "<50", "<50", "<50", "<50", "<100", "<50"],
]
WORK_ZONES = [*ZONE_NAMES, "Downtown or West End", "Rest of Vancouver or UBC",
              "Burnaby", "New Westminster"]


def figure_zones(survey):
    with tempfile.TemporaryDirectory() as temp:
        prefix = Path(temp) / "figure"
        subprocess.run(["pdfimages", "-f", "15", "-l", "15", "-png", survey, prefix], check=True)
        with Image.open(prefix.with_name("figure-002.png")) as chart:
            if chart.size != (1416, 704):
                raise ValueError("Unexpected North Shore zone figure dimensions")
            rgb = np.asarray(chart.convert("RGB"), dtype=np.int16)
    red, green, blue = rgb.transpose(2, 0, 1)
    components, _ = label((blue - red > 27) & (green - red > 8) & (green > 70))
    seeds = [int(components[y, x]) for x, y in FIGURE_SEEDS]
    if len(set(seeds)) != len(ZONES) or 0 in seeds:
        raise ValueError("The survey boundaries did not split into eight zones")
    result = np.zeros(components.shape, dtype=np.uint8)
    for zone, seed in enumerate(seeds, 1):
        result[components == seed] = zone
    return result


def pixel_lookup(survey):
    outline = figure_zones(survey)
    distances = np.stack([distance_transform_edt(outline != zone)
                          for zone in range(1, len(ZONES) + 1)])
    nearest = distances.argmin(axis=0) + 1
    first, second = np.partition(distances, 1, axis=0)[:2]

    def locate(utm):
        pixels = (utm - UTM_ORIGIN) / 1000 @ PIXEL_MATRIX + PIXEL_ORIGIN
        x, y = np.rint(pixels).astype(int).T
        valid = (0 <= x) & (x < outline.shape[1]) & (0 <= y) & (y < outline.shape[0])
        x, y = np.clip(x, 0, outline.shape[1] - 1), np.clip(y, 0, outline.shape[0] - 1)
        # Permit map and Census coastline differences, including small piers.
        # A difference of six pixels between the two nearest zones is a
        # three-pixel position tolerance on either side of their boundary.
        zone = np.where(valid & (first[y, x] <= 10), nearest[y, x], 0)
        uncertain = (zone > 0) & (second[y, x] - first[y, x] <= 6)
        return zone.tolist(), uncertain.tolist()

    return locate


def crosswalk(survey, atlas, roster, places, areas, home_names):
    """Return approximate survey zone and boundary flag for each local place."""
    locate = pixel_lookup(survey)
    local = [i for i, p in enumerate(places) if p[2] >= 0 and areas[p[2]] in home_names]
    wgs = np.array([places[i][:2] for i in local]) / SCALE + ORIGIN
    points = pd.DataFrame({"lon": wgs[:, 0], "lat": wgs[:, 1]})
    das = [da for name in home_names for da in atlas["areas"][name]["das"]]
    geometries = pd.DataFrame(
        {"da": das, "shape": [json.dumps(json.loads((roster / f"{da}.json").read_text())["geometry"])
                               for da in das]})
    with duckdb.connect() as db:
        db.execute("load spatial")
        db.register("positions", points)
        utm = db.execute("""select st_x(p), st_y(p) from (
            select st_transform(st_point(lon,lat),'EPSG:4326','EPSG:26910',always_xy:=true) p
            from positions)""").fetchnumpy()
        db.register("areas", geometries)
        centres = db.execute("""select da, st_x(p), st_y(p) from (
            select da, st_pointonsurface(st_transform(st_geomfromgeojson(shape),
              'EPSG:4326','EPSG:26910',always_xy:=true)) p from areas) order by da""").fetchall()
    zones, flags = locate(np.column_stack(tuple(utm.values())))
    place_zones, place_flags = [0] * len(places), [False] * len(places)
    for place, zone, flag in zip(local, zones, flags, strict=True):
        place_zones[place] = zone
        place_flags[place] = flag
    das_zone, _ = locate(np.array([row[1:] for row in centres]))
    fallback = dict(zip((row[0] for row in centres), das_zone, strict=True))
    return dict(placeZones=place_zones, placeFlags=place_flags, daZones=fallback)


def reference(areas):
    return dict(homeZones=[dict(zone=i, label=name, residents=ZONES[i-1][1])
                           for i, name in enumerate(ZONE_NAMES, 1)],
                workplaces=[dict(key=name, observed=cells)
                            for name, cells in zip(WORK_ZONES, OBSERVED, strict=True)
                            if name not in ("Burnaby", "New Westminster") or name in areas])


def workplace_groups(places, areas, place_zones, local):
    groups = []
    local_names = ["Unmapped", *ZONE_NAMES]
    for (_, _, area, *_), zone in zip(places, place_zones, strict=True):
        name = areas[area] if area >= 0 else "Unmapped"
        if name in local:
            group = local_names[zone]
        elif name in ("Downtown", "West End"):
            group = "Downtown or West End"
        elif name in ("Burnaby", "New Westminster", "Unmapped"):
            group = name
        else:
            group = "Rest of Vancouver or UBC"
        groups.append(group)
    return groups
