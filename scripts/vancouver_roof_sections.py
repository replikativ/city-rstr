"""Fit stepped building volumes from the existing Vancouver LiDAR archive."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import shutil

import numpy as np
from scipy.ndimage import binary_closing, find_objects, label
from scipy.signal import find_peaks
from shapely import box, get_parts, intersects_xy, make_valid, set_precision, union_all
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient

from scripts.vancouver_atlas import write_json
from scripts.vancouver_building_heights import CRS, GRID_BUCKET, RoofRasters, footprints, matching_pixels, transform
from scripts.vancouver_region import package, read
from scripts.vancouver_transit_commutes import pointer


MINIMUM_PIXELS = 120
MINIMUM_SECTION_AREA = 24
LEVEL_STEP = 3.5
LEVEL_TOLERANCE = 1.25
SOURCE = "https://isprs-annals.copernicus.org/articles/V-4-2021/169/2021/"


def spatial_split(points):
    """Keep paired 2 m cells together across fitting, selection and audit."""
    x,y = np.floor(points).astype(int).T
    withheld = (x//2%2==0)&(y//2%2==0)
    select = withheld&((x//4+y//4)%2==0)
    return ~withheld,select,withheld&~select


def levels(surface):
    bins = np.rint(surface*2).astype(int)
    offset = bins.min()
    histogram = np.bincount(bins-offset)
    smoothed = np.convolve(np.pad(histogram,4),[1,2,3,2,1],mode="same")
    peaks,_ = find_peaks(smoothed,distance=int(LEVEL_STEP*2))
    found = []
    support = max(14,min(65,int(len(surface)*.11)))
    for peak in peaks:
        nearby = surface[abs(surface-(peak-4+offset)/2)<=LEVEL_TOLERANCE]
        if len(nearby)>=support:
            found.append((float(np.median(nearby)),len(nearby)))
    return found


def cells_to_shape(mask, origin):
    """Union contiguous raster runs before fitting them to the original footprint."""
    edges = np.diff(np.pad(mask,((0,0),(1,1))).astype(np.int8),axis=1)
    rows,first = np.where(edges==1)
    _,last = np.where(edges==-1)
    x,y = origin
    return union_all(box(x+first,y+rows,x+last,y+rows+1))


def roof_geometry(mask, footprint, origin):
    components,n = label(binary_closing(mask,structure=np.ones((3,3),dtype=bool)))
    if not n:
        return None
    pieces = []
    for i,window in enumerate(find_objects(components),1):
        region = components[window]==i
        observed = mask[window]&region
        if observed.sum()<MINIMUM_SECTION_AREA*.55 or region.sum()<MINIMUM_SECTION_AREA:
            continue
        anchor = origin+np.array([window[1].start,window[0].start])
        shape = (cells_to_shape(region,anchor).buffer(.6,join_style="mitre")
                 .simplify(.7,preserve_topology=True).intersection(footprint))
        pieces.extend(p for p in get_parts(shape) if p.geom_type=="Polygon" and p.area>=MINIMUM_SECTION_AREA)
    return union_all(pieces) if pieces else None


def predict(sections, points):
    heights = np.full(len(points),np.nan)
    for elevation,polygon in sections:
        heights[intersects_xy(polygon,points[:,0],points[:,1])] = elevation
    return heights


def roof_sections(rings, points, surface, ground, reference_height, original_height, basis):
    present = np.isfinite(surface)&np.isfinite(ground)&(surface-ground>=1.65)
    if present.sum()<max(MINIMUM_PIXELS,.8*len(points)):
        return None
    fit,select,audit = (mask&present for mask in spatial_split(points))
    if fit.sum()<32 or min(select.sum(),audit.sum())<8 or np.quantile(surface[fit],.9)-np.quantile(surface[fit],.1)<LEVEL_STEP:
        return None
    grade = float(np.median(ground[fit]))
    candidates = [(elevation,n) for elevation,n in levels(surface[fit]) if 2<=elevation-grade<=350]
    base = next((elevation for elevation,n in candidates if n>=.17*fit.sum()),None)
    if base is None:
        return None
    upper = [elevation for elevation,_ in candidates if elevation>=base+LEVEL_STEP]
    if not upper:
        return None
    footprint = Polygon(rings[0],rings[1:])
    if not footprint.is_valid or footprint.area<MINIMUM_PIXELS:
        return None
    pixels = np.floor(points).astype(int)
    minimum = pixels.min(axis=0)-2
    indexes = pixels-minimum
    width,height = indexes.max(axis=0)+3
    remaining = footprint
    sections = []
    # Start with the highest parts so every cell belongs to at most one volume.
    for level in reversed(upper[-4:]):
        mask = np.zeros((height,width),dtype=bool)
        xs,ys = indexes[fit&(abs(surface-level)<=LEVEL_TOLERANCE)].T
        mask[ys,xs] = True
        shape = roof_geometry(mask,remaining,minimum)
        if shape is not None:
            sections.append((level,shape))
            remaining = remaining.difference(shape)
    if not sections or not remaining.is_valid or remaining.area<.15*footprint.area:
        return None
    tolerance = max(5,(.2 if basis=="height" else .35)*original_height)
    if basis!="assumed" and abs(sections[0][0]-grade-original_height)>tolerance:
        return None
    sections.append((base,remaining))
    predicted = predict(sections,points)
    # Use a separate set of raster cells to decide whether the extra detail is warranted.
    # The audit cells remain unused until both the shapes and the choice are fixed.
    baseline = min((float(np.median(surface[fit])), grade+reference_height),
                   key=lambda z:np.abs(surface[select]-z).mean())
    old = np.abs(surface-baseline)
    new = np.abs(surface-predicted)
    if not np.isfinite(new[select|audit]).all():
        return None
    if new[select].mean()>min(old[select].mean()-.5,old[select].mean()*.8):
        return None
    volumes = [(round(elevation-grade,1),shape) for elevation,shape in reversed(sections)]
    return volumes,(points[audit],surface[audit]-grade,old[audit])


def polygons(part):
    if part.geom_type=="Polygon":
        if part.area>0:
            yield orient(part)
    elif part.geom_type in {"MultiPolygon","GeometryCollection"}:
        for shape in get_parts(part):
            yield from polygons(shape)


def encode_sections(qualified):
    if not qualified:
        return {},np.zeros(3)
    vertices,records = {},{}
    for id,(parts,_,_) in qualified.items():
        records[id] = []
        for height,shape in parts[1:]:
            rings = []
            for polygon in polygons(shape):
                rings.append([[vertices.setdefault(p,len(vertices)) for p in ring.coords]
                              for ring in [polygon.exterior,*polygon.interiors]])
            if not rings:
                raise ValueError("A selected volume has no roof polygon")
            records[id].append((height,rings))
    starts = {}
    offset = len(vertices)
    for id,(_,_,(points,_,_)) in qualified.items():
        starts[id] = slice(offset,offset+len(points))
        offset += len(points)
    geographic = transform(np.concatenate([np.asarray(list(vertices)),*(v[2][0] for v in qualified.values())]),
                           f"EPSG:{CRS}","OGC:CRS84","%.10f")
    local = np.column_stack(((geographic[:,0]+123.1)*72600,(49.26-geographic[:,1])*111195))
    encoded,audit = {},np.zeros(3)
    for id,(parts,boundary,(_,observed,reference_error)) in qualified.items():
        original = Polygon(boundary[0],boundary[1:])
        if not original.is_valid:
            continue
        remaining = set_precision(original,.001)
        prepared = []
        # Reclip in the renderer's plane. The projection can curve straight
        # segment joins, especially where a roof section meets a facade.
        for height,rings in reversed(records[id]):
            shape = MultiPolygon([Polygon(local[r[0]], [local[hole] for hole in r[1:]]) for r in rings])
            shape = set_precision(union_all(list(polygons(make_valid(shape)))),.001).intersection(remaining)
            shape = union_all([part for part in polygons(shape) if part.area>=1])
            if shape.is_empty:
                continue
            remaining = remaining.difference(shape)
            prepared.append((height,shape))
        if not prepared or remaining.is_empty:
            continue
        prepared.append((parts[0][0],remaining))
        prepared.reverse()
        geometries = [shape for _,shape in prepared]
        coverage = union_all(geometries)
        if (not all(shape.is_valid for shape in geometries) or coverage.symmetric_difference(original).area>.05 or
                sum(shape.area for shape in geometries)-coverage.area>.05):
            raise ValueError(f"Roof sections do not partition footprint {id}")
        predicted = predict(prepared,local[starts[id]])
        if not np.all(np.isfinite(predicted)):
            raise ValueError(f"Roof sections do not cover the audit cells for footprint {id}")
        audit += len(observed),reference_error.sum(),abs(predicted-observed).sum()
        encoded[id] = [[height,[[np.round(np.asarray(ring.coords),3).tolist()
                                 for ring in [piece.exterior,*piece.interiors]] for piece in polygons(shape)]]
                       for height,shape in prepared]
    return encoded,audit


def publish(root, street_folder, rasters):
    parent = root/"building-heights"
    reference = read(parent/(street_folder.name+".json"))["version"]
    baseline = read(parent/reference/"report.json")
    if "roofSections" in baseline:
        reference = baseline["roofSections"]["reference"]
        baseline = read(parent/reference/"report.json")
    if baseline["streets"]!=street_folder.name or baseline["inputs"]!=rasters.inputs:
        raise ValueError("Roof sections need the same footprints and elevation archive as the flat heights")
    _,buildings,locations,local,coords = footprints(street_folder)
    flat = {row[0]:row[1] for tile in baseline["tiles"] for row in read(parent/reference/(tile+".json"))}
    qualified,counts = {},Counter()
    order = sorted(buildings,key=lambda id:tuple(coords[buildings[id][2][0][0]]//GRID_BUCKET))
    for id in order:
        height,basis,indices = buildings[id]
        boundary = coords[indices[0]]
        lo = np.floor(boundary.min(axis=0)).astype(int)
        hi = np.ceil(boundary.max(axis=0)).astype(int)
        if np.prod(hi-lo)<MINIMUM_PIXELS or not rasters.covers((*lo,*hi)):
            continue
        rings = [boundary,*(coords[ring] for ring in indices[1:])]
        points = matching_pixels(rings)
        if len(points)<MINIMUM_PIXELS:
            continue
        counts["tested"] += 1
        result = roof_sections(rings,points,*rasters.elevations(points),flat.get(id,height),height,basis)
        if result:
            parts,audit_points = result
            qualified[id] = (parts,[local[ring] for ring in indices],audit_points)
    volumes,audit = encode_sections(qualified)
    section_tiles = defaultdict(list)
    for id,parts in volumes.items():
        for tile in locations[id]:
            section_tiles[tile].append([id,parts])
    summary = dict(reference=reference,source=SOURCE,tiles=sorted(section_tiles),buildings=len(volumes),
                   parts=sum(map(len,volumes.values())),tested=counts["tested"],auditPixels=int(audit[0]),
                   auditFlatMAE=round(float(audit[1]/audit[0]),2) if audit[0] else None,
                   auditSectionMAE=round(float(audit[2]/audit[0]),2) if audit[0] else None,
                   coordinateSpace="city-grid",
                   minimumStep=LEVEL_STEP,minimumSectionArea=MINIMUM_SECTION_AREA)

    def build(output):
        write_json(output/"report.json",dict(baseline,roofSections=summary))
        for name in baseline["tiles"]:
            shutil.copyfile(parent/reference/(name+".json"),output/(name+".json"))
        for name,rows in section_tiles.items():
            write_json(output/("sections-"+name+".json"),sorted(rows))

    version = package(root,"building-heights",build)
    pointer(parent/(street_folder.name+".json"),dict(version=version))
    print(street_folder.name,version,{k:v for k,v in summary.items() if k!="tiles"},flush=True)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs",type=Path,default=Path("data/region/building-elevation"))
    parser.add_argument("--root",type=Path,default=Path("public/data/vancouver"))
    parser.add_argument("--streets",type=Path,action="append")
    args = parser.parse_args()
    rasters = RoofRasters(args.inputs)
    city = args.root/"streets"
    region = args.root/"region"
    for street_folder in args.streets or [city/read(city/"current.json")["version"],
                                         region/"streets"/read(region/"current.json")["streets"]]:
        publish(args.root,street_folder,rasters)
