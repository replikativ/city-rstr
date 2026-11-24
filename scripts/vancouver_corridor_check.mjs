// Compare a corridor replay or one resident's distance- and time-based routes.
import {readFileSync,existsSync} from "node:fs";
import {join} from "node:path";
import {CAR,Network,distance} from "../public/lab/vancouver-network.js";
import {affectedSegments,reusableFreeFlow,routeKey} from "../public/lab/weekday-pathfinder.js";

function measureDrive(graph,ids,path){
  let metres=0,minutes=0;
  const streets=new Map();
  for(let i=1;i<path.length;i++){
    const from=path[i-1],to=path[i],length=distance(from,to);
    metres+=length;
    if(i===1||i===path.length-1){
      minutes+=length/graph.connectorSpeed;
      continue;
    }
    const a=ids.get(from),b=ids.get(to);
    let rate=0,name="";
    for(let edge=graph.offset[a];edge<graph.offset[a+1];edge++){
      if(graph.to[edge]!==b||!(graph.mask[edge]&CAR)||graph.driveSpeed[edge]<=rate)continue;
      rate=graph.driveSpeed[edge];
      name=graph.names[graph.street[edge]];
    }
    if(!rate)throw Error("Route uses an edge without a driving speed.");
    minutes+=length/rate;
    if(name)streets.set(name,(streets.get(name)??0)+length);
  }
  const longestStreets=[...streets].sort((a,b)=>b[1]-a[1]).slice(0,5);
  return {metres,minutes,longestStreets};
}

function compareDistance({da,person,start,day,places,driverParts,graph}){
  const resident=day.sample.find(([d,i])=>day.das[d]===da&&i+1===person);
  if(!resident)throw Error("This resident is outside the animation sample.");
  const [,,template,plan]=resident;
  const leg=driverParts[template].find(([departure])=>departure===start);
  if(!leg)throw Error("No single-mode driving leg departs at this minute.");
  const [,duration,,from,to]=leg,a=places[plan[from]],b=places[plan[to]];
  if(!a||!b)throw Error("The driving leg has an unresolved endpoint.");
  const fastest=graph.driveRoute(a,b);
  const shortest=graph.route(a,b,CAR);
  if(!fastest||!shortest)throw Error("The driving leg has no connected route within the access limits.");
  const ids=new Map(graph.nodes.map((node,i)=>[node,i]));
  const byDistance=measureDrive(graph,ids,shortest),byTime=measureDrive(graph,ids,fastest.path);
  if(Math.abs(fastest.minutes-byTime.minutes)>1e-6||
    byTime.minutes>byDistance.minutes+1e-6||byDistance.metres>byTime.metres+1e-6)
    throw Error("The reported routes disagree with the explicit street cost calculation.");
  return {da,person,start,duration,byDistance,byTime};
}

const root=process.argv[2]??"public/data/vancouver/region";
const read=file=>JSON.parse(readFileSync(join(root,file)));
const current=existsSync(join(root,"current.json"))?read("current.json"):read("cityday/current.json");
const dayId=process.argv[3]??current.day??current.version;
const {atlas}=current;
const streets=current.streets??read("streets/current.json").version;
const day=read(`cityday/${dayId}/day.json`);
const places=read(`cityday/${dayId}/places.json`);
const templates=read(`atlas/${atlas}/atlas.json`).templates;
const driverParts=day.templates.map((template,i)=>template.parts.filter(([start,n,mode])=>mode==="car-driver"&&
  templates[i].episodes.every(([s,d,,travel])=>s>=start+n||s+d<=start||travel===mode)));

const [option,da,person,start]=process.argv.slice(4);
if(option){
  if(option!=="--compare-distance"||!da||!Number.isInteger(Number(person))||!Number.isInteger(Number(start)))
    throw Error("Expected --compare-distance DA PERSON DEPARTURE_MINUTE.");
  const graph=new Network(read(`streets/${streets}/network.json`),null,read(`drive-profile/${streets}.json`));
  const result=compareDistance({da,person:Number(person),start:Number(start),day,places,driverParts,graph});
  console.log(JSON.stringify({atlas,day:dayId,streets,...result},null,2));
}else{
  console.log(JSON.stringify(compareCorridorTimes(),null,2));
}

function compareCorridorTimes(){
  const trafficId=read(`drive-profile/${streets}_corridor-times.json`).version;
  const prefix=`drive-profile/corridor-times/${trafficId}/`;
  const traffic=read(prefix+"report.json");
  const affected=affectedSegments(traffic.affected);
  const routeId=read(`overview-routes/${atlas}_${dayId}_${streets}.json`).version;
  const routes=`overview-routes/${routeId}/`;
  const manifest=read(routes+"manifest.json");
  if(manifest.driveProfileDigest!==traffic.baselineDigest)throw Error("Rebuild the baseline overview routes for this weekday.");

  const observed=new Network(read(`streets/${streets}/network.json`),null,read(prefix+"profile.json"));
  const windows=[[7,8],[16,17]];
  const peak=[];
  for(const hours of windows){
    const cache=new Map(hours.map(hour=>[hour,new Map(read(routes+hour+".json"))]));
    const summary={hours,located:0,baselineFeasible:0,baselineAffected:0,becameInfeasible:0,
      changedPath:0,stillFeasibleMeanDelayMinutes:0};
    const alternates=new Map();
    let delaySum=0,maxDelay=-1,example=null;
    for(const [d,i,template,plan] of day.sample){
      for(const [start,duration,,from,to] of driverParts[template]){
        const hour=Math.floor(start/60),baseline=cache.get(hour),a=places[plan[from]],b=places[plan[to]];
        if(!baseline||!a||!b)continue;
        summary.located++;
        const key=routeKey(2,a,b,duration,380,false);
        if(!baseline.has(key))throw Error("The baseline is missing a located trip.");
        const old=baseline.get(key);
        if(!old)continue;
        summary.baselineFeasible++;
        if(reusableFreeFlow(old,affected))continue;
        summary.baselineAffected++;
        const variant=key+"/"+hour;
        if(!alternates.has(variant))alternates.set(variant,observed.driveRoute(a,b,duration,start));
        const route=alternates.get(variant);
        if(!route){summary.becameInfeasible++;continue;}
        const delay=route.minutes-old.minutes;
        if(delay < -1e-6)throw Error("The observed profile produced a faster shortest route.");
        delaySum+=delay;
        const changed=JSON.stringify(route.path)!==JSON.stringify(old.path);
        if(changed)summary.changedPath++;
        if(delay>maxDelay){
          maxDelay=delay;
          example={da:day.das[d],person:i+1,start,duration,freeMinutes:old.minutes,observedMinutes:route.minutes,changed};
        }
      }
    }
    const compared=summary.baselineAffected-summary.becameInfeasible;
    summary.stillFeasibleMeanDelayMinutes=compared?delaySum/compared:null;
    peak.push({...summary,example});
  }
  return {atlas,day:dayId,streets,baseline:routeId,traffic:trafficId,sampleResidents:day.sample.length,peak};
}
