// Time index for drawing everyone walking to or from one scheduled service.
import {readFileSync,writeFileSync} from "node:fs";
import {join} from "node:path";
import {onwardRide,rideTiming} from "../public/lab/transit-passenger.js";

const [root,riders,out]=process.argv.slice(2),read=p=>JSON.parse(readFileSync(join(root,p)));
const riderDir="transit-riders/"+riders+"/",report=read(riderDir+"riders.json"),{versions}=report;
const das=read("cityday/"+versions.day+"/day.json").das,home=new Map(das.map((da,d)=>[da,d]));
const routes=new Map(),walks=new Map(),departures=new Map();
for(const id of Object.keys(report.byRoute)){
  routes.set(id,read("transit/"+versions.transit+"/"+id+".json"));walks.set(id,[]);departures.set(id,new Map());
}
let count=0;
for(const da of report.das){
  if(!home.has(da))throw Error("Unknown home area "+da);
  const {people}=read("atlas/"+versions.atlas+"/"+da+".json");
  for(const row of read(riderDir+da+".json")){
    const [area,i,,,a,b,id,,board,alight]=row;
    if(area!==da)throw Error("Rider shard and resident differ");
    const timing=rideTiming(row,routes.get(id),true);
    const onward=onwardRide(row),lastID=onward?.[6]??id;
    const last=onward?rideTiming(onward,routes.get(lastID),true):timing;
    const journeys=[[id,row[2]]];
    if(onward)journeys.push([lastID,Math.floor(last.boardAt/60)]);
    for(const [route,minute] of journeys){
      const groups=departures.get(route),template=people[i][7];
      if(!groups.has(minute))groups.set(minute,{count:0,templates:new Map()});
      const group=groups.get(minute);
      group.count++;
      group.templates.set(template,(group.templates.get(template)||0)+1);
    }
    for(const [route,start,duration,place,stop,direction] of [
      [id,timing.accessStart,timing.access,a,timing.pat.stops[board],0],
      [lastID,last.egressStart,last.egress,b,last.pat.stops[onward?.[9]??alight],1]]){
      if(duration>0)walks.get(route).push([start,duration,home.get(da),i,place,stop,direction]);
    }
    count++;
  }
}
if(count!==report.matched)throw Error("Incomplete scheduled rider index");
const manifest={riders,...versions,trips:count,segments:0,routes:{}};
for(const [id,rows] of walks){
  rows.sort((a,b)=>a[0]-b[0]||a[2]-b[2]||a[3]-b[3]||a[6]-b[6]);
  const maxSeconds=rows.reduce((max,row)=>Math.max(max,row[1]),0);
  const [minute,group]=[...departures.get(id)].sort((a,b)=>b[1].count-a[1].count||a[0]-b[0])[0];
  const peak={minute,count:group.count,templates:group.templates.size,largestGroup:Math.max(...group.templates.values())};
  manifest.routes[id]={segments:rows.length,maxSeconds,peak};manifest.segments+=rows.length;
  writeFileSync(join(out,id+".json"),JSON.stringify(rows));
}
writeFileSync(join(out,"walks.json"),JSON.stringify(manifest));
