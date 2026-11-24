// Check trip feasibility using the same directed speed profile as weekday playback.
import {readFileSync,writeFileSync} from "node:fs";
import {Network} from "../public/lab/vancouver-network.js";

const read=path=>JSON.parse(readFileSync(path));
const [candidateFile,inputs,positions,network,speeds,output]=process.argv.slice(2);
const {fifths,candidates}=read(candidateFile),metadata=read(inputs),places=read(positions);
const graph=new Network(read(network),null,read(speeds));

function rank([d,i,minute]){
  let n=Math.imul(d,0x9e3779b1)^Math.imul(i,0x85ebca77)^Math.imul(minute,0xc2b2ae3d);
  n=Math.imul(n^(n>>>16),0x7feb352d);
  n=Math.imul(n^(n>>>15),0x846ca68b);
  return (n^(n>>>16))>>>0;
}

const trips=fifths.trips/5,original={taxi:fifths.taxi/5,ridehail:fifths.ridehail/5};
const target=Math.round(trips*metadata.evidence.city.share);
const replacement=Math.max(0,Math.round(target-original.taxi-original.ridehail));
const split=metadata.evidence.split;
const taxiTarget=Math.round(target*split.taxi/(split.taxi+split.ridehail));
const newTaxis=Math.max(0,Math.min(replacement,Math.round(taxiTarget-original.taxi)));
const ordered=candidates.filter(row=>row[6]==="car-passenger")
  .map(row=>[rank(row),row]).sort((a,b)=>a[0]-b[0]);
const rows=[],count={recorded:{taxi:0,ridehail:0},assigned:{taxi:0,ridehail:0}};
const hours=Array.from({length:24},()=>[0,0]);
let screened=0,rejected=0,example=null;

function add(row,service,assigned){
  const [d,i,start,duration,a,b]=row;
  const route=graph.driveRoute(places[a],places[b],duration);
  if(!route||route.offsets.at(-2)<=route.offsets[1])return false;
  rows.push([d,i,start,duration,a,b,service,assigned]);
  count[assigned?"assigned":"recorded"][service]++;
  hours[Math.floor(start/60)%24][service==="taxi"?0:1]++;
  if(assigned&&service==="ridehail"&&duration>=10&&(!example||Math.abs(start-1080)<Math.abs(example[2]-1080))){
    const point=route.path[Math.floor(route.path.length/2)];
    example=[d,i,start,duration,point];
  }
  return true;
}

for(const row of candidates)if(row[6]!=="car-passenger")add(row,row[6],false);
for(const [,row] of ordered){
  const served=count.assigned.taxi+count.assigned.ridehail;
  if(served>=replacement)break;
  const chooseTaxi=Math.floor((served+1)*newTaxis/replacement)>Math.floor(served*newTaxis/replacement);
  screened++;
  if(!add(row,chooseTaxi?"taxi":"ridehail",true))rejected++;
}
rows.sort((a,b)=>a[0]-b[0]||a[1]-b[1]||a[2]-b[2]);
writeFileSync(output,JSON.stringify({...metadata,counts:{trips,original,target,eligible:ordered.length,screened,rejected,...count},
  departures:hours,example,rows}));
