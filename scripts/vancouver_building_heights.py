"""Publish building heights estimated from paired LidarBC surface and ground rasters."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from hashlib import file_digest
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

from matplotlib.path import Path as PolygonPath
import numpy as np
from PIL import Image
from tifffile import TiffFile

from scripts.vancouver_atlas import write_json
from scripts.vancouver_region import package, read
from scripts.vancouver_transit_commutes import pointer


CATALOGUE = "https://services6.arcgis.com/ubm4tcTYICKBpist/arcgis/rest/services/LiDAR_BC_S3_Public/FeatureServer"
FRAME = (-123.31, 49.188, -122.945, 49.392)
YEAR = 2025
LAYERS = {"surface": 1, "ground": 5}
CRS = 3157
GRID_BUCKET = 1000
EDGE_CLEARANCE = .75
MIN_PIXELS = 7
MIN_COVERAGE = .7


def catalogue_url(layer):
    query = dict(where=f"year={YEAR}", geometry=",".join(map(str, FRAME)), geometryType="esriGeometryEnvelope",
                 inSR=4326, spatialRel="esriSpatialRelIntersects", outFields="maptile,year,filename,s3Url",
                 returnGeometry="false", f="json")
    return f"{CATALOGUE}/{layer}/query?"+urlencode(query)


def catalogued_inputs(folder, *, fetch=False):
    by_kind = {}
    for kind, layer in LAYERS.items():
        url = catalogue_url(layer)
        index = folder/(kind+".json")
        if not index.exists():
            if not fetch:
                raise FileNotFoundError(f"Missing {index}. Re-run with --fetch to build the LiDAR archive.")
            with urlopen(url, timeout=45) as response:
                payload = json.load(response)
            if payload.get("exceededTransferLimit") or not payload.get("features"):
                raise ValueError(f"Incomplete {kind} index for the selected survey")
            pointer(index,payload)
        entries = [row["attributes"] for row in json.loads(index.read_text())["features"]]
        by_kind[kind] = {entry["maptile"]:entry for entry in entries}
        if len(entries)!=len(by_kind[kind]):
            raise ValueError(f"Ambiguous {kind} rasters for a tile")
    if by_kind["surface"].keys()!=by_kind["ground"].keys():
        raise ValueError("The LidarBC surface and ground indexes cover different map tiles")
    return {tile:{kind:entries[tile] for kind,entries in by_kind.items()} for tile in sorted(by_kind["surface"])}


def acquire_entry(folder, entry):
    url = entry["s3Url"]
    parsed = urlsplit(url)
    if parsed.scheme!="https" or parsed.hostname!="nrs.objectstore.gov.bc.ca" or not parsed.path.endswith("/"+entry["filename"]):
        raise ValueError("Unexpected object path in the public elevation index")
    destination = folder/Path(parsed.path).name
    if not destination.exists():
        with tempfile.TemporaryDirectory(dir=folder) as directory:
            pending = Path(directory)/destination.name
            with urlopen(url, timeout=90) as src, pending.open("wb") as output:
                shutil.copyfileobj(src, output)
            with TiffFile(pending) as tif:
                if len(tif.pages[0].shape)!=2:
                    raise ValueError(f"Expected a single-band raster in {destination.name}")
            pending.replace(destination)
    return destination


def acquire(folder):
    folder.mkdir(parents=True, exist_ok=True)
    inputs = catalogued_inputs(folder,fetch=True)
    entries = [entry for pair in inputs.values() for entry in pair.values()]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i,_ in enumerate(pool.map(lambda entry:acquire_entry(folder,entry), entries),1):
            if i%40==0 or i==len(entries):
                print(f"Archived {i} of {len(entries)} public elevation rasters",flush=True)


def raster_info(path):
    with TiffFile(path) as tif:
        page = tif.pages[0]
        tags = page.geotiff_tags
        if (tags.get("ProjectedCSTypeGeoKey")!=CRS or tags.get("VerticalCSTypeGeoKey")!=6647 or
                tags.get("GTRasterTypeGeoKey")!=1 or tags["ModelPixelScale"][:2]!=[1.0,1.0]):
            raise ValueError(f"Unexpected projection, datum or pixel size in {path.name}")
        offsets = tags["ModelTiepoint"]
        if offsets[:3]!=[0,0,0] or any(int(value)!=value for value in offsets[3:5]):
            raise ValueError(f"Unexpected raster origin in {path.name}")
        x,top = map(int,offsets[3:5])
        height,width = page.shape
        return (x,top-height,x+width,top),float(page.tags[42113].value)


def buckets(bounds):
    a,b,c,d = bounds
    for x in range(a//GRID_BUCKET,(c-1)//GRID_BUCKET+1):
        for y in range(b//GRID_BUCKET,(d-1)//GRID_BUCKET+1):
            yield x,y


class RoofRasters:
    def __init__(self, folder):
        self.lookup = defaultdict(set)
        self.bounds, self.inputs = {}, []
        for tile,pair in catalogued_inputs(folder).items():
            records = []
            for kind,entry in pair.items():
                path = folder/entry["filename"]
                extent,nodata = raster_info(path)
                with path.open("rb") as stream:
                    checksum = file_digest(stream,"sha256").hexdigest()
                records.append((path,extent,nodata))
                self.inputs.append(dict(tile=tile,kind=kind,file=path.name,source=entry["s3Url"],sha256=checksum))
            ((surface,bounds,roof_na),(ground,terrain_bounds,ground_na)) = records
            if bounds!=terrain_bounds:
                raise ValueError(f"Surface and terrain pixels do not align for {tile}")
            self.bounds[tile] = (bounds,surface,ground,roof_na,ground_na)
            for bucket in buckets(bounds):
                self.lookup[bucket].add(tile)

    @lru_cache(maxsize=12)
    def raster(self, tile):
        _,surface,ground,roof_na,ground_na = self.bounds[tile]
        with Image.open(surface) as roof, Image.open(ground) as terrain:
            roofs,ground = np.asarray(roof),np.asarray(terrain)
        elevations = np.stack((roofs,ground))
        elevations[:,(roofs==roof_na)|(ground==ground_na)] = np.nan
        return elevations[:,::-1]

    def elevations(self, points):
        pixels = np.floor(points).astype(int)
        min_x,min_y = pixels.min(axis=0)
        max_x,max_y = pixels.max(axis=0)+1
        tiles = set().union(*(self.lookup.get(bucket,()) for bucket in buckets((min_x,min_y,max_x,max_y))))
        values = np.full((2,len(pixels)),np.nan,dtype=np.float32)
        xs,ys = pixels.T
        for tile in sorted(tiles):
            x,y,right,top = self.bounds[tile][0]
            inside = (x<=xs)&(xs<right)&(y<=ys)&(ys<top)&~np.isfinite(values).all(axis=0)
            if np.any(inside):
                values[:,inside] = self.raster(tile)[:,ys[inside]-y,xs[inside]-x]
        return values

    def sample(self, points):
        surface,ground = self.elevations(points)
        return surface-ground

    def covers(self, bounds):
        return any(self.lookup.get(bucket) for bucket in buckets(bounds))


def matching_pixels(rings):
    outer,*holes = map(np.asarray,rings)
    low = np.floor(outer.min(axis=0)).astype(int)
    high = np.ceil(outer.max(axis=0)).astype(int)
    x,y = np.meshgrid(*(np.arange(a,b)+.5 for a,b in zip(low,high,strict=True)))
    points = np.column_stack((x.ravel(),y.ravel()))
    polygon = PolygonPath(outer)
    cutouts = [PolygonPath(hole) for hole in holes]
    for offset in ((0,0),(-EDGE_CLEARANCE,0),(EDGE_CLEARANCE,0),(0,-EDGE_CLEARANCE),(0,EDGE_CLEARANCE)):
        probe = points+offset
        keep = polygon.contains_points(probe)
        for cutout in cutouts:
            keep &= ~cutout.contains_points(probe)
        points = points[keep]
    return points


def estimate_height(values):
    valid = values[np.isfinite(values)]
    if len(valid)<MIN_PIXELS or len(valid)<MIN_COVERAGE*len(values):
        return None,"insufficient pixels"
    low,middle,high = np.quantile(valid,[.25,.5,.75])
    if not 2 <= middle <= 350 or low<1.5:
        return None,"no consistent elevated surface"
    spread = high-low
    if spread>max(2.8,.22*middle):
        return None,"mixed elevations"
    return [round(float(middle),1),len(valid),round(float(spread),1)],"supported"


def transform(coords, source_crs, target_crs, precision):
    with tempfile.TemporaryFile(mode="w+b") as source, tempfile.TemporaryFile(mode="w+b") as out:
        np.savetxt(source,coords,fmt="%.10f")
        source.seek(0)
        subprocess.run(["cs2cs","-f",precision,source_crs,target_crs],stdin=source,stdout=out,check=True)
        out.seek(0)
        result = np.loadtxt(out,usecols=(0,1))
    if result.shape!=coords.shape or not np.all(np.isfinite(result)):
        raise ValueError("Building coordinates did not reach the LidarBC raster CRS")
    return result


def project(points):
    # Source tiles use the city's planar coordinates. Transform them from the
    # same geographic frame as the browser before looking up source pixels.
    coords = np.asarray(points,dtype=float)
    coords[:,0] = coords[:,0]/72600-123.1
    coords[:,1] = 49.26-coords[:,1]/111195
    return transform(coords,"OGC:CRS84",f"EPSG:{CRS}","%.3f")


def footprints(street_folder):
    meta = read(street_folder/"streets.json")
    buildings, locations, vertices = {}, {}, {}
    for name in meta["tiles"]:
        for id,height,basis,ring,*details in read(street_folder/(name+".json"))["buildings"]:
            if id not in buildings:
                holes = details[0].get("holes",[]) if details else []
                rings = [[vertices.setdefault(tuple(p),len(vertices)) for p in r] for r in [ring,*holes]]
                buildings[id] = (height,basis,rings)
                locations[id] = []
            locations[id].append(name)
    if len(buildings)!=meta["buildings"]:
        raise ValueError("The footprint tiles and street manifest have different counts")
    local = np.asarray(list(vertices))
    return meta,buildings,locations,local,project(local)


def measure(street_folder, rasters):
    meta,buildings,locations,_,coords = footprints(street_folder)
    outputs, outcomes, replaced, comparison = defaultdict(list), Counter(), Counter(), []
    order = sorted(buildings,key=lambda id:tuple(coords[buildings[id][2][0][0]]//GRID_BUCKET))
    for id in order:
        height,basis,indices = buildings[id]
        pixels = matching_pixels([coords[ring] for ring in indices])
        evidence, outcome = estimate_height(rasters.sample(pixels) if len(pixels)>=MIN_PIXELS else np.array([]))
        if evidence and basis=="height":
            comparison.append(abs(height-evidence[0]))
            outcome = "kept mapped height"
        elif evidence and basis=="levels" and abs(height-evidence[0])>max(5,.35*height):
            outcome = "kept floor estimate after disagreement"
        elif evidence:
            replaced[basis] += 1
            for tile in locations[id]:
                outputs[tile].append([id,*evidence])
        outcomes[outcome] += 1
    report = dict(schema=1, streets=street_folder.name, source=CATALOGUE, year=YEAR, epsg=CRS,
                  verticalDatum="CGVD2013", cellMetres=1, inputs=rasters.inputs, footprintCount=len(buildings),
                  bounds=FRAME, tiles=sorted(outputs), original=meta["heightSources"], replacements=dict(replaced),
                  outcomes=dict(outcomes), mappedComparison=dict(count=len(comparison),
                      medianAbsoluteMetres=round(float(np.median(comparison)),2) if comparison else None),
                  minimumPixels=MIN_PIXELS, minimumCoverage=MIN_COVERAGE, edgeClearance=EDGE_CLEARANCE)
    return report,outputs


def publish(root, street_folder, rasters):
    report,outputs = measure(street_folder,rasters)
    def build(folder):
        write_json(folder/"report.json",report)
        for key,rows in outputs.items():
            write_json(folder/(key+".json"),sorted(rows))
    version = package(root,"building-heights",build)
    pointer(root/"building-heights"/(street_folder.name+".json"),dict(version=version))
    print(version,street_folder.name,report["original"],report["replacements"],report["outcomes"],flush=True)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=Path("data/region/building-elevation"))
    parser.add_argument("--fetch", action="store_true", help="Archive the published LiDAR tiles and indexes")
    parser.add_argument("--root",type=Path,default=Path("public/data/vancouver"))
    parser.add_argument("--streets",type=Path, action="append", help="Path to a published street release to measure")
    args = parser.parse_args()
    if args.fetch:
        acquire(args.inputs)
    rasters = RoofRasters(args.inputs)
    for street_folder in args.streets or [args.root/"streets"/read(args.root/"streets/current.json")["version"],
                                          args.root/"region/streets"/read(args.root/"region/current.json")["streets"]]:
        publish(args.root,street_folder,rasters)
