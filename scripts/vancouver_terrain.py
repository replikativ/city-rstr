"""Publish offline MapLibre elevation tiles from NRCan bare-earth GeoTIFF extracts."""
import argparse
import hashlib
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates
from tifffile import TiffFile

from scripts.vancouver_atlas import write_json


WORLD = math.pi * 6378137
TILE = 256
BOUNDS = (-123.50, 49.10, -122.78, 49.58)
ZOOMS = (9, 14)
HRDEM_EXTENTS = {
    "hrdem-ne": (-13705016, 6334234, -13677500, 6366500),
    "hrdem-nw": (-13732500, 6334234, -13704984, 6366500),
    "hrdem-se": (-13705016, 6302000, -13677500, 6334266),
    "hrdem-sw": (-13732500, 6302000, -13704984, 6334266),
}
MRDEM_URL = "https://canelevation-dem.s3.ca-central-1.amazonaws.com/mrdem-30/mrdem-30-dtm.tif"
INPUTS = (*HRDEM_EXTENTS, "mrdem-context")


def hrdem_url(bounds, identifier="dtm", spacing=16):
    projection = "urn:ogc:def:crs:EPSG::3857"
    query = dict(SERVICE="WCS", VERSION="1.1.1", REQUEST="GetCoverage", FORMAT="image/geotiff",
                 IDENTIFIER=identifier, BOUNDINGBOX=",".join(map(str, (*bounds, projection))),
                 GRIDBASECRS=projection, GRIDOFFSETS=f"{spacing},-{spacing}")
    return "https://datacube.services.geo.ca/ows/elevation?" + urlencode(query)


def fetch_inputs(inputs):
    inputs.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=inputs) as directory:
        for name in INPUTS:
            path = inputs / (name + ".tif")
            receipt = path.with_suffix(".url")
            if path.is_file() and receipt.is_file():
                continue
            pending = Path(directory) / path.name
            if name in HRDEM_EXTENTS:
                url = hrdem_url(HRDEM_EXTENTS[name])
                with urlopen(url, timeout=320) as response, pending.open("wb") as output:
                    shutil.copyfileobj(response, output)
            else:
                url = MRDEM_URL
                subprocess.run([
                    "gdalwarp", "--config", "GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR",
                    "--config", "GDAL_HTTP_TIMEOUT", "40", "--config", "GDAL_HTTP_MAX_RETRY", "2",
                    "-te", "-13775880", "6261628", "-13619152", "6418358", "-tr", "46", "46",
                    "-t_srs", "EPSG:3857", "-novshift", "-r", "bilinear", "-dstnodata", "-32767",
                    "-co", "COMPRESS=DEFLATE", "/vsicurl/" + url, str(pending),
                ], check=True)
            with TiffFile(pending) as tiff:
                if tiff.pages[0].geotiff_tags.get("ProjectedCSTypeGeoKey") != 3857:
                    raise ValueError(f"Unexpected projection in {name} response")
            pending.replace(path)
            receipt.write_text(url + "\n")


def mercator(lon, lat):
    return lon * WORLD / 180, math.asinh(math.tan(math.radians(lat))) * WORLD / math.pi


def tile_coordinates(z, bounds):
    west, south = mercator(*bounds[:2])
    east, north = mercator(*bounds[2:])
    span = 2 * WORLD / (2 ** z)
    for x in range(math.floor((west + WORLD) / span), math.ceil((east + WORLD) / span)):
        for y in range(math.floor((WORLD - north) / span), math.ceil((WORLD - south) / span)):
            yield x, y


def tile_centres(z, x, y):
    step = 2 * WORLD / (TILE * 2 ** z)
    offset = np.arange(TILE) + .5
    return np.meshgrid((x * TILE + offset) * step - WORLD, WORLD - (y * TILE + offset) * step)


class Elevation:
    def __init__(self, path):
        with TiffFile(path) as tif:
            page = tif.pages[0]
            tags = page.geotiff_tags
            if (len(page.shape) != 2 or tags.get("ProjectedCSTypeGeoKey") != 3857 or
                    tags.get("GTRasterTypeGeoKey") != 1 or "ModelTransformation" in tags):
                raise ValueError(f"Expected a north-up, single-band Web Mercator raster in {path}")
            i, j, _, x, y, _ = tags["ModelTiepoint"]
            self.dx, self.dy, _ = tags["ModelPixelScale"]
            if self.dx <= 0 or self.dy <= 0:
                raise ValueError(f"Invalid pixel scale in {path}")
            self.x = x + (.5 - i) * self.dx
            self.y = y - (.5 - j) * self.dy
            self.values = page.asarray().astype(np.float32, copy=False)
            nodata = float(page.tags[42113].value)
        valid = np.isfinite(self.values) & (self.values != nodata)
        self.values[~valid] = 0
        self.support = valid.astype(np.float32)

    def sample(self, xs, ys):
        coords = [(self.y - ys) / self.dy, (xs - self.x) / self.dx]
        weights = map_coordinates(self.support, coords, order=1, mode="grid-constant")
        result = np.full(weights.shape, np.nan, dtype=np.float32)
        valid = weights >= .5
        if np.any(valid):
            observed = map_coordinates(self.values, [c[valid] for c in coords], order=1, mode="grid-constant")
            result[valid] = observed / weights[valid]
        return result


def composite(sources, xs, ys):
    heights = np.zeros(xs.shape, dtype=np.float32)
    use = np.zeros(xs.shape, dtype=np.uint8)
    for index, source in enumerate(sources, 1):
        remaining = np.flatnonzero(use == 0)
        if not remaining.size:
            break
        samples = source.sample(xs.flat[remaining], ys.flat[remaining])
        valid = np.isfinite(samples)
        cells = remaining[valid]
        use.flat[cells] = index
        heights.flat[cells] = samples[valid]
    return heights, use


def terrain_rgb(metres):
    # Mapbox RGB packs decimetres above -10000 m into three channels.
    value = np.rint((metres.astype(np.float64) + 10000) * 10).astype(np.int32)
    if np.any((value < 0) | (value > 0xffffff)):
        raise ValueError("Elevation lies outside the terrain encoding range")
    return np.stack((value >> 16, (value >> 8) & 255, value & 255), axis=-1).astype(np.uint8)


def build(inputs, payload):
    sources = [Elevation(inputs / (name + ".tif")) for name in INPUTS]
    receipts = []
    for name in INPUTS:
        with (inputs / (name + ".tif")).open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        receipts.append(dict(name=name, sha256=digest, source=(inputs / (name + ".url")).read_text().strip()))
    west, south = mercator(*BOUNDS[:2])
    east, north = mercator(*BOUNDS[2:])
    coverage = dict(highResolution=0, mediumResolution=0, seaLevelFill=0)
    tile_count = 0
    for z in range(ZOOMS[0], ZOOMS[1] + 1):
        for x, y in tile_coordinates(z, BOUNDS):
            xs, ys = tile_centres(z, x, y)
            heights, use = composite(sources, xs, ys)
            path = payload / str(z) / str(x) / f"{y}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(terrain_rgb(heights)).save(path)
            tile_count += 1
            if z == ZOOMS[1]:
                inside = (west <= xs) & (xs <= east) & (south <= ys) & (ys <= north)
                coverage["highResolution"] += int(np.count_nonzero(inside & (use > 0) & (use < len(sources))))
                coverage["mediumResolution"] += int(np.count_nonzero(inside & (use == len(sources))))
                coverage["seaLevelFill"] += int(np.count_nonzero(inside & (use == 0)))
    manifest = dict(bounds=BOUNDS, minzoom=ZOOMS[0], maxzoom=ZOOMS[1], tileSize=TILE, encoding="mapbox",
                    verticalDatum="CGVD2013", tileCount=tile_count, coverage=coverage, inputs=receipts)
    write_json(payload / "manifest.json", manifest)
    return manifest


def publish(inputs, root):
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as directory:
        payload = Path(directory) / "payload"
        payload.mkdir()
        manifest = build(inputs, payload)
        digest = hashlib.sha256()
        for file in sorted(p for p in payload.rglob("*") if p.is_file()):
            digest.update(file.relative_to(payload).as_posix().encode())
            with file.open("rb") as stream:
                digest.update(hashlib.file_digest(stream, "sha256").digest())
        version = digest.hexdigest()[:20]
        if not (root / version).exists():
            payload.rename(root / version)
        pointer = Path(directory) / "pointer"
        write_json(pointer, dict(version=version))
        pointer.replace(root / "current.json")
    print(version, manifest["tileCount"], manifest["coverage"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=Path("data/region/terrain"))
    parser.add_argument("--output", type=Path, default=Path("public/data/vancouver/terrain"))
    parser.add_argument("--fetch", action="store_true", help="Fetch missing NRCan extracts using HTTPS and gdalwarp")
    args = parser.parse_args()
    if args.fetch:
        fetch_inputs(args.inputs)
    publish(args.inputs, args.output)
