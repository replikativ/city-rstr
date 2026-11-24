import {readFileSync,writeFileSync} from "node:fs";
import {join} from "node:path";
import {Worker} from "node:worker_threads";
import {CAR,Network,distance} from "../public/lab/vancouver-network.js";

const read=file=>JSON.parse(readFileSync(file));
const [source,assumptions,positions,network,speeds,out,parentSource,parentTrace]=process.argv.slice(2);
const rides=read(source),config=read(assumptions),places=read(positions);
const baseline=parentSource?read(parentSource).rows:null;
if(baseline&&(baseline.length!==rides.rows.length||baseline.some((row,i)=>
  row.some((field,k)=>k===2?Math.floor(field/60)!==Math.floor(rides.rows[i][k]/60):field!==rides.rows[i][k]))))
  throw Error("The paired dispatch requires the same riders, trip lengths, departure hours and places.");
const graph=new Network(read(network),null,read(speeds));
const first=240*60,hour=3600,day=24*hour;
const services=["taxi","ridehail"];
const seconds=minutes=>Math.ceil(minutes*60-1e-7);
const priorTimes=new Map();
if(parentTrace){
  for(const [mode,runs] of Object.entries(read(parentTrace))){
    for(const trace of Object.values(runs))for(const {id,miss,drop,board} of trace){
      if(miss)continue;
      const row=baseline[id],loaded=drop-board;
      if(!row||row[6]!==mode||!Number.isInteger(loaded)||loaded<=0||loaded>row[3]*60||
         (priorTimes.has(id)&&priorTimes.get(id)!==loaded))
        throw Error("A prior dispatch trace has an inconsistent road duration.");
      priorTimes.set(id,loaded);
    }
  }
}
function loadedTime(a,b,duration){
  const route=graph.driveRoute(places[a],places[b],duration);
  if(!route||route.offsets.at(-2)<=route.offsets[1])throw Error("A published hired ride no longer fits.");
  return seconds(route.offsets.at(-2)-route.offsets[1]);
}
const requests=Object.fromEntries(services.map(mode=>[mode,[]]));
for(const [id,[,,start,duration,a,b,mode]] of rides.rows.entries()){
  const pickup=graph.snap(places[a],CAR),destination=graph.snap(places[b],CAR);
  requests[mode].push({id,hail:start*60,due:(start+duration)*60,pickup,destination,
    access:seconds(distance(places[a],graph.nodes[pickup])/config.walkMetresPerMinute),
    loaded:priorTimes.get(id)??loadedTime(a,b,duration),
    egress:seconds(distance(places[b],graph.nodes[destination])/config.walkMetresPerMinute)});
}

function timeByHour(start,end,hours){
  for(let h=Math.floor((start-first)/hour);h<Math.ceil((end-first)/hour);h++){
    const a=first+h*hour;
    hours[h]+=Math.min(end,a+hour)-Math.max(start,a);
  }
}

function peakCapacity(group,occupancy){
  if(!group.length)return 0;
  const hours=new Array(24).fill(0);
  for(const {hail,access,loaded,due} of group){
    const board=hail+access;
    const end=Math.min(board+loaded,due);
    if(end>board)timeByHour(board,end,hours);
  }
  return Math.max(1,Math.ceil(Math.max(...hours)/(hour*occupancy)));
}

function runDispatch(group,staged){
  const worker=new Worker(new URL("./vancouver_dispatch_worker.mjs",import.meta.url),
    {workerData:{network,speeds,group,staged,patience:config.patience}});
  return new Promise((resolve,reject)=>{
    worker.once("message",resolve);
    worker.once("error",reject);
    worker.once("exit",code=>reject(Error("Dispatch worker exited before publishing results with status "+code)));
  });
}

function quantile(sorted,q){
  if(!sorted.length)return null;
  const index=(sorted.length-1)*q,lo=Math.floor(index),fraction=index-lo;
  return sorted[lo]+fraction*(sorted[Math.ceil(index)]-sorted[lo]);
}

function summarize(group,results,capacity){
  const waits=[],occupied=new Array(24).fill(0),emptyMoving=new Array(24).fill(0);
  const calls=Array.from({length:24},()=>({served:0,diary:0,dispatch:0}));
  let diary=0,dispatch=0;
  for(const [i,request] of group.entries()){
    const row=results[i];
    if(row.id!==request.id)throw Error("Dispatch rows and requests differ.");
    const cell=calls[Math.floor((request.hail-first)/hour)];
    if(row.miss==="diary"){diary++;cell.diary++;continue;}
    if(row.miss==="dispatch"){dispatch++;cell.dispatch++;continue;}
    cell.served++;
    waits.push(row.curb-request.hail);
    if(row.depart<request.hail||row.curb<row.depart||row.board<row.curb||
       row.drop-row.board!==request.loaded||row.arrive>request.due)
      throw Error("A ride violated its dispatch or diary clock.");
    timeByHour(row.board,row.drop,occupied);
    if(row.curb>row.depart)timeByHour(row.depart,row.curb,emptyMoving);
  }
  waits.sort((a,b)=>a-b);
  const sum=rows=>rows.reduce((total,n)=>total+n,0);
  return {capacity,served:waits.length,diary,dispatch,median:quantile(waits,.5),p90:quantile(waits,.9),
    occupiedSeconds:sum(occupied),emptyMovingSeconds:sum(emptyMoving),
    occupancy:capacity?sum(occupied)/(capacity*day):null,calls};
}

function drawPath(path,offsets,duration){
  return {path:path.map(p=>p.slice(0,2)),offsets:offsets.map(n=>n*60),duration};
}

function journey(request,row){
  if(row.miss)return row;
  const [, ,,,a,b]=rides.rows[request.id];
  const loaded=graph.driveRoute(places[a],places[b]);
  const approach=row.from===request.pickup?null:
    graph.driveRoute(graph.nodes[row.from],graph.nodes[request.pickup]);
  if(row.curb>row.depart&&(!approach||seconds(approach.minutes)!==row.curb-row.depart))
    throw Error("The selected dispatch time and approach route disagree.");
  const lo=loaded.offsets[1],hi=loaded.offsets.at(-2);
  if(seconds(hi-lo)!==request.loaded)throw Error("The selected ride and its road duration disagree.");
  return {...row,approach:approach?drawPath(approach.path,approach.offsets,row.curb-row.depart):null,
    origin:places[a].slice(0,2),destination:places[b].slice(0,2),
    loaded:drawPath(loaded.path.slice(1,-1),loaded.offsets.slice(1,-1).map(t=>t-lo),row.drop-row.board),
    access:drawPath(loaded.path.slice(0,2),[0,lo],request.access),
    egress:drawPath(loaded.path.slice(-2),[0,loaded.minutes-hi],request.egress)};
}

const summaries={},examples={},traces={};
for(const service of services){
  const group=requests[service].sort((a,b)=>a.hail-b.hail||a.id-b.id);
  const capacity=config.reference?.fleet[service]??peakCapacity(group,config.evidence.occupancy[service]);
  const stageOrder=baseline?[...group].sort((a,b)=>baseline[a.id][2]-baseline[b.id][2]||a.id-b.id):group;
  const staged=Array.from({length:capacity},(_,i)=>stageOrder[Math.floor((i+.5)*stageOrder.length/capacity)].pickup);
  const reduced=staged.filter((_,i)=>(i+1)%4!==0);
  const [ref,stress]=await Promise.all([runDispatch(group,staged),runDispatch(group,reduced)]);
  summaries[service]={reference:summarize(group,ref,staged.length),reduced:summarize(group,stress,reduced.length)};
  traces[service]={reference:ref,reduced:stress};
  let selected;
  let best=-Infinity;
  for(const [i,request] of group.entries()){
    const lhs=ref[i],rhs=stress[i];
    if(lhs.miss||rhs.miss||lhs.from===request.pickup||!rides.rows[request.id][7])continue;
    const difference=rhs.curb-lhs.curb;
    const score=difference*2+lhs.curb-lhs.depart-Math.abs(request.hail-1020*60)/60;
    if(score>best){selected=i;best=score;}
  }
  if(selected!==undefined){
    const request=group[selected],[d,i,start,duration]=rides.rows[request.id];
    examples[service]={d,i,start,duration,reference:journey(request,ref[selected]),reduced:journey(request,stress[selected])};
  }
  console.log(service,JSON.stringify(summaries[service],(key,value)=>key==="calls"?undefined:value));
}
writeFileSync(join(out,"dispatch.json"),JSON.stringify({...config,summaries,examples}));
writeFileSync(join(out,"traces.json"),JSON.stringify(traces));
