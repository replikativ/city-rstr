"""Build the connected Vancouver, UBC and North Shore study extent from census and GIS releases."""
import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from collections import Counter
from datetime import date
from urllib.request import urlopen
import shutil
from pathlib import Path

import duckdb

from scripts import vancouver_atlas as atlas
from scripts import vancouver_cityday as cityday
from scripts import vancouver_streets as streets
from scripts.vancouver_basemap import basemap
from scripts.vancouver_census_geography import DA, area_membership, profile_cells

FRAME=(-123.335,49.188,-122.905,49.481)
CAMPUS="UBC Vancouver campus"
NAMES={"5915046":"District of North Vancouver","5915051":"City of North Vancouver","5915055":"West Vancouver"}
ELECTORAL="5915020"
SOURCES={
    "ubc-buildings.geojson":"https://raw.githubusercontent.com/UBCGeodata/ubc-geospatial-opendata/885732d332a20a59143f655c83fb15e1367ebe4d/ubcv/locations/geojson/ubcv_buildings.geojson",
    "campus.geojson":"https://services2.arcgis.com/NlsizNmbMFiinWw4/ArcGIS/rest/services/Vancouver_Campus_Boundary/FeatureServer/1/query?where=1%3D1&outFields=*&outSR=4326&f=geojson",
    "vancouver.osm.pbf":"https://download.bbbike.org/osm/bbbike/Vancouver/Vancouver.osm.pbf",
}


def acquire(inputs):
    inputs.mkdir(parents=True,exist_ok=True)
    for name,url in SOURCES.items():
        if (inputs/name).exists():continue
        with tempfile.TemporaryDirectory(dir=inputs) as tmp:
            file=Path(tmp)/name
            with urlopen(url,timeout=120) as response,file.open("wb") as output:
                shutil.copyfileobj(response,output)
            file.replace(inputs/name)



def read(path):
    return json.loads(path.read_text())


def emit(stream,obj):
    stream.write(json.dumps(obj,separators=(",",":"))+"\n")


def campus_geometry(inputs):
    shape=read(inputs/"campus.geojson")["features"][0]["geometry"]
    if shape["type"]!="LineString" or shape["coordinates"][0]!=shape["coordinates"][-1]:
        raise ValueError("UBC legal boundary must be a closed ring")
    return {"type":"Polygon","coordinates":[shape["coordinates"]]}


def prepare_census(raw,inputs,work):
    codes = area_membership(raw / "statcan", {*NAMES, ELECTORAL})
    campus=campus_geometry(inputs)
    with duckdb.connect() as db:
        db.execute("LOAD spatial")
        db.execute("create table members (da varchar,csd varchar)");db.executemany("insert into members values (?,?)",list(codes.items()))
        db.execute("""create temp table da as select m.da,m.csd,st_makevalid(s.geom) g from st_read(?) s join members m on m.da=s.DAUID""",[str(raw/"statcan/lda_000b21a_e.shp")])
        db.execute("""create temp table campus as select st_transform(st_geomfromgeojson(?),'EPSG:4326','EPSG:3347',always_xy:=true) g""",[json.dumps(campus)])
        ratios=dict(db.execute("select da,st_area(st_intersection(d.g,c.g))/st_area(d.g) from da d,campus c where csd=?",[ELECTORAL]).fetchall())
        selected={k for k,v in ratios.items() if v>=.5}
        if not selected:raise ValueError("No census areas matched the campus boundary")
        db.executemany("delete from da where da=?",[(k,) for k in ratios if k not in selected])
        def geometry(expr):
            return "st_asgeojson(st_transform(st_simplifypreservetopology("+expr+",4),'EPSG:3347','EPSG:4326',always_xy:=true))"
        geos={k:json.loads(g) for k,g in db.execute("select da,"+geometry("g")+" from da").fetchall()}
        shapes={NAMES[csd]:json.loads(g) for csd,g in db.execute("select csd,"+geometry("st_union_agg(g)")+" from da where csd<>? group by csd",[ELECTORAL]).fetchall()}
        shapes[CAMPUS]=campus
    sums=Counter();controls={};quality={}
    keys = {DA + d for d in geos} | {"2021A0005" + csd for csd in NAMES}
    profiles = profile_cells(raw / "statcan", keys, atlas.ROSTER_CELLS, columns=(11, 13, 15))
    with (work / "vancouver_da_marginals.jsonl").open("w") as output:
        for key, cells in profiles.items():
            if key.startswith("2021A0005"):
                controls[NAMES[key[-7:]]] = (int(cells[1][0]), int(cells[5][0]))
                continue
            da = key[-8:]
            area = NAMES.get(codes[da], CAMPUS)
            m = {k: [int(value) if value is not None else None for value in row] for k, row in cells.items()}
            emit(output, dict(dauid=da, local_area=area, m=m))
            if m[56][0] is None or m[8][0] is None:
                quality[da] = [m[1][0], m[5][0]]
            sums[area, "people"] += m[1][0]
            sums[area, "homes"] += m[5][0]
    for name,(n,h) in controls.items():
        if (sums[name,"people"],sums[name,"homes"])!=(n,h):raise ValueError("Census subdivision mismatch "+name)
    with (work/"vancouver_da_boundaries.jsonl").open("w") as stream:
        for da,g in geos.items():emit(stream,dict(dauid=da,geometry=g))
    atlas.write_json(work/"areas.json",shapes)
    atlas.write_json(work/"coverage.json",dict(controls=controls,campusDAs={k:round(ratios[k],4) for k in sorted(selected)},
        campusResidents=sums[CAMPUS,"people"],campusHomes=sums[CAMPUS,"homes"],limited=quality))
    print("Regional sources:",len(geos),"census areas;",controls,"campus",sums[CAMPUS,"people"],"limited",quality,flush=True)


def place_kinds(tags):
    building=tags.get("building");amenity=tags.get("amenity");kinds=[]
    residential_address=(tags.get("addr:housenumber") and not (amenity or tags.get("shop") or tags.get("office")) and building in (None,"yes"))
    if residential_address or building in {"house","residential","apartments","detached","semidetached_house","terrace","dormitory"}:
        kinds.append("home")
    if building=="yes" and not kinds and not any(tags.get(k) for k in ("amenity","shop","office","tourism","leisure","industrial")):
        kinds.append("home-proxy")
    if tags.get("shop"):kinds.append("store")
    if amenity in {"restaurant","cafe","fast_food","bar","pub","food_court"}:kinds.append("restaurant")
    if amenity in {"university","college"}:kinds.append("college")
    if amenity in {"hospital","clinic","doctors","dentist"}:kinds.append("clinic")
    if amenity=="place_of_worship":kinds.append("worship")
    if tags.get("tourism") in {"museum","gallery"} or amenity in {"library","theatre","cinema"}:kinds.append("culture")
    if tags.get("leisure") in {"park","garden","playground"}:kinds.append("outdoors")
    if tags.get("leisure") in {"sports_centre","fitness_centre","pitch","swimming_pool"}:kinds.append("sports-venue")
    if tags.get("office") or building in {"commercial","retail","office","industrial","warehouse"}:kinds.append("business")
    if any(k in kinds for k in ("business","store","restaurant","clinic","college")):kinds.append("job")
    return kinds


def prepare_osm(inputs,work):
    west,south,east,north=FRAME
    with duckdb.connect() as db:
        db.execute("load spatial");db.execute("set threads=3");db.execute("set enable_progress_bar=false")
        db.execute("""create temp table nodes as select id,lon,lat,tags from st_readosm(?)
            where kind='node' and lon between ? and ? and lat between ? and ?""",
            [str(inputs/"vancouver.osm.pbf"),west,south,east,north])
        db.execute("""create temp table ways as select id,tags,refs from st_readosm(?) where kind='way' and
            (tags['highway'] is not null or tags['building'] is not null or tags['amenity'] is not null
             or tags['shop'] is not null or tags['leisure'] is not null or tags['office'] is not null)""",
            [str(inputs/"vancouver.osm.pbf")])
        db.execute("""create temp table within_frame as select w.id, list(n.lon order by seq) as xs,
            list(n.lat order by seq) as ys from (select id,unnest(refs) as ref,generate_subscripts(refs,1) seq from ways) w
            join nodes n on n.id=w.ref group by w.id""")
        campus=campus_geometry(inputs)
        query="""select w.id,w.tags,w.refs,f.xs,f.ys,st_covers(st_geomfromgeojson(?),
            st_point(list_avg(xs),list_avg(ys))) from ways w join within_frame f using (id)
            where len(w.refs)=len(xs) order by w.id"""
        counts=Counter()
        with (work/"roads.jsonl").open("w") as roads,(work/"buildings.jsonl").open("w") as buildings,(work/"places.jsonl").open("w") as places:
            def place(x,y,tags):
                # Existing municipal sources supply City destinations. Keep this catalogue
                # outside Vancouver by testing exact census membership in catalogue().
                for kind in place_kinds(tags):emit(places,[x,y,kind,tags.get("name",""),1])
            for x,y,tags in db.execute("select lon,lat,tags from nodes where cardinality(tags)>0 order by id").fetchall():
                place(x,y,tags)
            cursor=db.execute(query,[json.dumps(campus)])
            while records:=cursor.fetchmany(2000):
                for ref,tags,nodes,xs,ys,in_campus in records:
                    way=dict(type="way",id=ref,tags=tags,nodes=nodes,geometry=[dict(lon=x,lat=y) for x,y in zip(xs,ys)])
                    if tags.get("highway"):
                        emit(roads,way);counts["roads"]+=1
                    if tags.get("building") and not in_campus:
                        emit(buildings,way);counts["osmBuildings"]+=1
                    if not in_campus or not tags.get("building"):place(sum(xs)/len(xs),sum(ys)/len(ys),tags)
            for index,feat in enumerate(read(inputs/"ubc-buildings.geojson")["features"]):
                props=feat["properties"];g=feat["geometry"]
                if not g or props.get("CONSTR_STATUS") in {"Demolished","Proposed"}:continue
                polygons=[g["coordinates"]] if g["type"]=="Polygon" else g["coordinates"]
                def polygon_area(poly):
                    return abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(poly[0],poly[0][1:])))
                main=max(range(len(polygons)),key=lambda j:polygon_area(polygons[j]))
                for j,poly in enumerate(polygons):
                    ring=poly[0];x=sum(p[0] for p in ring)/len(ring);y=sum(p[1] for p in ring)/len(ring)
                    tags={"building":"yes","name":props.get("NAME") or "UBC building"}
                    for key,source in [("height","BLDG_HEIGHT"),("building:levels","MAX_FLOORS")]:
                        if props.get(source):tags[key]=str(props[source])
                    emit(buildings,dict(type="way",id=-(index*100+j+1),tags=tags,
                         geometry=[dict(lon=p[0],lat=p[1]) for p in ring],holes=poly[1:]))
                    counts["campusFootprints"]+=1
                    if j!=main:continue
                    usage=(props.get("BLDG_USAGE") or "").lower()
                    for kind in (["home"] if "hous" in usage or "residen" in usage else
                                 ["college","job"] if "academic" in usage or "research" in usage else ["business","job"]):
                        emit(places,[x,y,kind,tags["name"],1])
        print("Regional GIS:",dict(counts),flush=True)


def rows(file):
    with file.open() as stream:yield from map(json.loads,stream)


def package(root,name,fn,seed=""):
    folder=root/name;folder.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        payload=Path(tmp)/"payload";payload.mkdir();fn(payload)
        h=hashlib.sha256(seed.encode())
        for file in sorted(payload.iterdir()):
            h.update(file.name.encode());h.update(file.read_bytes())
        version=h.hexdigest()[:20]
        if not (folder/version).exists():payload.rename(folder/version)
        return version


def publish_versions(output, versions):
    history = output / "releases"
    history.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output) as tmp:
        # A pinned clock describes its atlas/day. Preserve the original street and transit versions too.
        current = output / "current.json"
        for release in ([read(current), versions] if current.exists() else [versions]):
            key = release["atlas"] + "_" + release["day"] + ".json"
            if not (history / key).exists():
                file = Path(tmp) / key
                atlas.write_json(file, release)
                file.replace(history / key)
        pointer = Path(tmp) / "pointer"
        atlas.write_json(pointer, versions)
        pointer.replace(current)


def copy_roster(source, dest):
    try:
        os.link(source, dest)
    except OSError:
        shutil.copyfile(source, dest)


def merge_municipality(regional, core, folder, coverage):
    city = read(core / "atlas.json")
    if any(regional[key] != city[key] for key in ("templates", "fields", "labels", "heldout", "ages", "seed")):
        raise ValueError("Incompatible roster fields or diary templates")
    if regional["das"].keys() & city["das"].keys() or regional["areas"].keys() & city["areas"].keys():
        raise ValueError("Overlapping census rosters")
    for da in city["das"]:
        copy_roster(core / (da + ".json"), folder / (da + ".json"))
    regional["areas"].update(city["areas"])
    regional["das"].update(city["das"])
    regional["city"] = atlas.sums(list(regional["das"].values()))
    regional["coverage"] = dict(coverage, municipalAtlas=core.name)
    atlas.write_json(folder / "atlas.json", regional)


def rebase_atlas(output, regional_id, municipal_id):
    """Publish a candidate roster. The current regional weekday keeps its original parents."""
    core = output.parent / "atlas" / municipal_id
    prior = output / "atlas" / regional_id
    audit = read(core.parent / ("boundary-" + municipal_id + ".json"))
    if (audit["atlas"] != municipal_id or audit["municipality"] != "5915022" or audit["adjacent"]
            or audit["missing"] or audit["municipalAreas"] != audit["inReplay"]):
        raise ValueError("The municipal atlas needs a matched census boundary")
    city = read(core / "atlas.json")
    if len(city["das"]) != audit["inReplay"] or city["city"]["population"] != audit["municipalPopulation"]:
        raise ValueError("Municipal population or area count disagrees with the census audit")

    def population(folder):
        regional = read(prior / "atlas.json")
        coverage = regional["coverage"]
        names = [*NAMES.values(), CAMPUS]
        areas = {name: regional["areas"][name] for name in names}
        ids = [da for area in areas.values() for da in area["das"]]
        if len(ids) != len(set(ids)) or set(areas[CAMPUS]["das"]) != set(coverage["campusDAs"]):
            raise ValueError("Regional extension has overlapping areas or a different campus boundary")
        for name, area in areas.items():
            control = ([coverage["campusResidents"], coverage["campusHomes"]] if name == CAMPUS
                       else coverage["controls"][name])
            if [area["population"], area["homes"]] != list(control):
                raise ValueError("Regional controls disagree for " + name)
        regional["areas"] = areas
        regional["das"] = {da: regional["das"][da] for da in ids}
        for name in ["basemap.json", *(da + ".json" for da in ids)]:
            copy_roster(prior / name, folder / name)
        merge_municipality(regional, core, folder, dict(coverage, extensionAtlas=regional_id,
                           municipalBoundarySource=audit["source"]))

    return package(output, "atlas", population)


def package_weekday(archive, work, output, atlas_id):
    shapes = {r["dauid"]: r["geometry"] for r in rows(work / "vancouver_da_boundaries.jsonl")}
    def write_day(folder):
        cityday.build(archive, output / "atlas" / atlas_id, folder,
                      extra_shapes=shapes, extra_places=rows(work / "places.jsonl"))
    return package(output, "cityday", write_day, atlas_id)


def build(archive,inputs,output,prepare=True):
    from scripts.vancouver_transit import build as transit_build
    acquire(inputs)
    raw=archive/"data/raw";work=inputs/"work";work.mkdir(exist_ok=True)
    if prepare:
        prepare_census(raw,inputs,work);prepare_osm(inputs,work)
    core_dir=output.parent/"atlas"
    core=core_dir/read(core_dir/"current.json")["version"]
    sources=read(work/"coverage.json")
    def population(folder):
        donors=json.loads(subprocess.check_output(["clojure","-M","-m","city.vancouver.atlas-diaries",str(archive)]))
        map_data=basemap(raw,FRAME,rows(work/"roads.jsonl"))
        regional=atlas.build(archive,folder,atlas.Weekday(donors),derived=work,area_geometry=read(work/"areas.json"),map_data=map_data)
        merge_municipality(regional, core, folder, sources)
    av=package(output,"atlas",population)
    from scripts.vancouver_population_check import publish as check_population
    check_population(archive, output/"atlas"/av, regional=True)
    print("Regional atlas",av,flush=True)
    sv=package(output,"streets",lambda out:streets.build(raw,out,roads=rows(work/"roads.jsonl"),buildings=rows(work/"buildings.jsonl")))
    print("Regional streets",sv,flush=True)
    from scripts.vancouver_cycling import publish as publish_cycling
    publish_cycling(archive,output,regional_roads=work/"roads.jsonl",streets=sv)
    dv=package_weekday(archive,work,output,av)
    tv=package(output,"transit",lambda out:transit_build(raw/"probes/transit_translink_gtfs_static.zip",read(work/"areas.json"),date(2026,9,15),out))
    from scripts.vancouver_campus import publish as publish_campus
    versions=dict(atlas=av,day=dv,streets=sv,transit=tv)
    from scripts.vancouver_raster import publish as publish_raster
    publish_raster(output,av,dv)
    publish_campus(output,versions)
    from scripts.vancouver_visitors import publish as publish_visitors
    publish_visitors(archive,output,versions,inputs)
    from scripts.vancouver_street_walks import publish as publish_walks
    publish_walks(output,versions)
    publish_versions(output, versions)
    print("Regional day",dv,flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path);parser.add_argument("--inputs",type=Path,default=Path("data/region"))
    parser.add_argument("--output",type=Path,default=Path("public/data/vancouver/region"))
    parser.add_argument("--reuse-inputs",action="store_true",help="Use the previously extracted census, road and place rows")
    parser.add_argument("--rebase-atlas", nargs=2, metavar=("REGIONAL_ATLAS", "MUNICIPAL_ATLAS"),
                        help="Build a regional roster using a census-audited municipal release and existing regional shards")
    parser.add_argument("--candidate-day", action="store_true",
                        help="Also build a full resident weekday for the rebased atlas")
    args=parser.parse_args()
    if args.candidate_day and not args.rebase_atlas:
        parser.error("--candidate-day requires --rebase-atlas")
    if args.rebase_atlas:
        candidate = rebase_atlas(args.output, *args.rebase_atlas)
        print("Regional atlas", candidate, flush=True)
        if args.candidate_day:
            print("Regional day", package_weekday(args.archive, args.inputs / "work", args.output, candidate))
    else:
        build(args.archive,args.inputs,args.output,not args.reuse_inputs)
