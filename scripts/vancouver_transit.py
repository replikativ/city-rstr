"""Export a two-calendar-day TransLink timetable across the UBC and North Shore study areas."""
import argparse
import csv
import hashlib
import io
import json
import tempfile
import zipfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_cityday import xy


def seconds(value):
    h,m,s=map(int,value.split(":"));return 3600*h+60*m+s


def active_services(calendar,exceptions,day):
    stamp=day.strftime("%Y%m%d");weekday=day.strftime("%A").lower()
    active={r["service_id"] for r in calendar if r["start_date"]<=stamp<=r["end_date"] and r[weekday]=="1"}
    for r in exceptions:
        if r["date"]==stamp:
            if r["exception_type"]=="1":active.add(r["service_id"])
            else:active.discard(r["service_id"])
    return active


def stop_distances(line,points):
    """Project successive stops onto a forward traversal of the schedule shape."""
    v=np.array(line,dtype=float);a=v[:-1];segments=v[1:]-a
    length=np.linalg.norm(segments,axis=1);cum=np.r_[0,np.cumsum(length)]
    previous=0.;out=[]
    for point in points:
        t=np.clip(((point-a)*segments).sum(axis=1)/np.maximum(length**2,.00001),0,1)
        # Also permit the remaining part of the segment containing the previous stop.
        t=np.maximum(t,np.clip((previous-cum[:-1])/np.maximum(length,.00001),0,1))
        d=np.linalg.norm(a+t[:,None]*segments-point,axis=1)
        d[cum[1:]<previous-1e-7]=np.inf
        j=int(np.argmin(d))
        if d[j]>150:return None
        previous=float(cum[j]+t[j]*length[j]);out.append(round(previous,1))
    return out


def build(feed,areas,day,output,*,passenger_rules=False,transfer_rules=False):
    if transfer_rules and not passenger_rules:
        raise ValueError("Transfers require boarding and alighting permissions")
    with zipfile.ZipFile(feed) as z:
        def rows(name):
            with z.open(name+".txt") as raw,io.TextIOWrapper(raw,encoding="utf-8-sig") as text:
                yield from csv.DictReader(text)
        cal=list(rows("calendar"));exceptions=list(rows("calendar_dates"))
        offsets=defaultdict(list)
        for delta in (-1,0,1):
            for sid in active_services(cal,exceptions,day+timedelta(days=delta)):offsets[sid].append(delta*86400)
        stops={r["stop_id"]:[float(r["stop_lon"]),float(r["stop_lat"]),r["stop_name"]] for r in rows("stops")}
        served=None
        if areas is not None:
            with duckdb.connect() as db:
                db.execute("load spatial")
                db.execute("create temp table stops(id varchar,x double,y double)")
                db.executemany("insert into stops values (?,?,?)",[(sid,v[0],v[1]) for sid,v in stops.items()])
                db.execute("create temp table study(g geometry)")
                db.executemany("insert into study values(st_geomfromgeojson(?))",[(json.dumps(g),) for g in areas.values()])
                served={sid for sid, in db.execute("select distinct id from stops join study on st_covers(g,st_point(x,y))").fetchall()}
        trips={r["trip_id"]:r for r in rows("trips") if r["service_id"] in offsets}
        times=defaultdict(list)
        accepted=None if served is None else {r["trip_id"] for r in rows("stop_times")
                                              if r["stop_id"] in served and r["trip_id"] in trips}
        for r in rows("stop_times"):
            key=r["trip_id"]
            if key in trips and (accepted is None or key in accepted):
                times[key].append((int(r["stop_sequence"]),r["stop_id"],seconds(r["arrival_time"]),seconds(r["departure_time"]),
                    r.get("pickup_type") or "0", r.get("drop_off_type") or "0"))
        accepted=times.keys()
        shapeids={trips[k]["shape_id"] for k in accepted};shapes=defaultdict(list)
        for r in rows("shapes"):
            if r["shape_id"] in shapeids:
                shapes[r["shape_id"]].append((int(r["shape_pt_sequence"]),xy(float(r["shape_pt_lon"]),float(r["shape_pt_lat"]))))
        routes={r["route_id"]:r for r in rows("routes")};byroute=defaultdict(list)
        for k in sorted(accepted):byroute[trips[k]["route_id"]].append(k)
        info=next(rows("feed_info"));manifest=dict(date=day.isoformat(),feed=info["feed_version"],routes=[])
        for rid,keys in byroute.items():
            patterns=[];lookup={};rides=[];stopids={};station=[]
            for k in keys:
                trip=trips[k];events=sorted(times[k]);ids=tuple(e[1] for e in events);rules=tuple((int(e[4]=="0")+2*int(e[5]=="0")) for e in events)
                key=(trip["shape_id"],ids,rules if passenger_rules else ())
                schedules=[offset for offset in offsets[trip["service_id"]]
                           if events[0][2]+offset<28*3600 and events[-1][3]+offset>=4*3600]
                if not schedules or len(events)<2:continue
                if key not in lookup:
                    coords=[xy(*stops[s][:2]) for s in ids]
                    line=[p for _,p in sorted(shapes[trip["shape_id"]])]
                    dist=stop_distances(line,coords) if len(line)>1 else None
                    mapped=dist is not None
                    if not mapped:
                        line=coords;dist=np.r_[0,np.cumsum(np.linalg.norm(np.diff(coords,axis=0),axis=1))].round(1).tolist()
                    indices=[]
                    for sid,pt in zip(ids,coords):
                        if sid not in stopids:
                            stopids[sid]=len(station);station.append([*pt,stops[sid][2]])
                        indices.append(stopids[sid])
                    lookup[key]=len(patterns);patterns.append(dict(line=line,dist=dist,stops=indices,mapped=mapped))
                    if passenger_rules:patterns[-1]["access"]=rules
                first=events[0][2];relative=[v-first for e in events for v in e[2:4]]
                for offset in schedules:rides.append([lookup[key],first+offset,relative,trip["trip_headsign"]])
            if not rides:continue
            r=routes[rid]
            manifest["routes"].append(dict(id=rid,name=r["route_short_name"].lstrip("0") or r["route_long_name"],
                label=r["route_long_name"],trips=len(rides)))
            if passenger_rules:manifest["routes"][-1]["type"]=int(r["route_type"])
            payload=dict(patterns=patterns,rides=sorted(rides,key=lambda v:v[1]),stations=station)
            if transfer_rules:
                payload["stopIds"]=list(stopids)
            write_json(output/(rid+".json"),payload)
        if not manifest["routes"]:
            raise ValueError(f"No transit runs for the study area on {day}")
        manifest["routes"].sort(key=lambda r:(r["name"]!="SeaBus",r["name"].zfill(5)))
        if transfer_rules:
            pairs, linked = {}, 0
            transfers = rows("transfers") if "transfers.txt" in z.namelist() else ()
            for row in transfers:
                kind = int(row["transfer_type"])
                if kind in (4, 5):
                    linked += 1
                    continue
                if kind not in (0, 1, 2, 3) or any(row.get(k) for k in
                        ("from_trip_id", "to_trip_id", "from_route_id", "to_route_id")):
                    raise ValueError("Expected stop-pair rules for changes of vehicle")
                pair = row["from_stop_id"], row["to_stop_id"]
                if pair in pairs:
                    raise ValueError("Repeated transit transfer stop pair")
                pairs[pair] = kind, int(row["min_transfer_time"] or 0)
            write_json(output/"transfers.json",
                       dict(pairs=[[*pair, *rule] for pair, rule in sorted(pairs.items())], linkedTrips=linked))
            with feed.open("rb") as archive:
                manifest["feedDigest"] = hashlib.file_digest(archive, "sha256").hexdigest()
        write_json(output/"transit.json",manifest)
        return manifest


if __name__=="__main__":
    from scripts.vancouver_region import package
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("archive",type=Path)
    parser.add_argument("--inputs",type=Path,default=Path("data/region"));parser.add_argument("--date",type=date.fromisoformat,default=date(2026,9,15))
    parser.add_argument("--region",type=Path,default=Path("public/data/vancouver/region"));args=parser.parse_args()
    polygons=json.loads((args.inputs/"work/areas.json").read_text())
    v=package(args.region,"transit",lambda folder:build(args.archive/"data/raw/probes/transit_translink_gtfs_static.zip",polygons,args.date,folder))
    with tempfile.TemporaryDirectory(dir=args.region) as temp:
        f=Path(temp)/"pointer";write_json(f,{"version":v});f.replace(args.region/"transit/current.json")
    print(v,flush=True)
