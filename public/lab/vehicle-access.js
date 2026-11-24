import {loadRouteGeometry} from "./regional-transit.js";
import {onwardRide,ScheduledPassengers} from "./transit-passenger.js";
import {positionOn} from "./vancouver-network.js";

const el=id=>document.getElementById(id);
const idPattern=/^[a-f0-9]{20}$/;
const fmt=n=>n.toLocaleString("en-CA");
const identity=(d,i)=>d+"/"+i;
const same=(a,b)=>a[0]===b[0]&&a[1]===b[1];
const surveyModes=["Auto driver","Auto passenger","Transit","Walking","Cycling","Other / unspecified"];

export async function vehicleRelease(joint,requested,json){
  const family=joint.root+"vehicle-access/";
  if(requested&&!idPattern.test(requested))throw Error("Invalid household vehicle comparison release.");
  if(!requested){
    const response=await fetch(family+joint.id+".json");
    if(response.status===404)return null;
    if(!response.ok)throw Error("Household vehicle comparison is unavailable.");
    ({version:requested}=await response.json());
  }
  if(!idPattern.test(requested))throw Error("Invalid household vehicle comparison release.");
  const base=family+requested+"/",report=await json(base+"report.json");
  if(report.joint!==joint.id||report.versions.transit!==joint.transit||Object.entries(joint.versions).some(([k,v])=>report.versions[k]!==v))
    throw Error("The household vehicle comparison belongs to a different weekday.");
  return {base,report,version:requested};
}

function byPerson(rows){
  const result=new Map();
  for(const row of rows){
    const key=identity(...row);
    if(!result.has(key))result.set(key,[]);
    result.get(key).push(row);
  }
  return result;
}

export class VehicleAccess{
  constructor(release,root,day,places,json,refresh){
    Object.assign(this,{...release,root,day,places,json,refresh});
    this.areas=new Set(release.report.areas);
    this.shards=new Map();this.pending=new Map();
  }
  async init(){
    const schedule=this.root+"transit/"+this.report.versions.transit+"/";
    const [rows,departures,manifest]=await Promise.all(["sample.json","departures.json"].map(file=>this.json(this.base+file))
      .concat(this.json(schedule+"transit.json")));
    this.sample=byPerson(rows);
    this.departures=new Set(departures.map(row=>row.join("/")));
    if(this.departures.size!==this.report.stats.switchedTrips)throw Error("Household vehicle trips differ from the weekday index.");
    this.modeChanges=new Map(surveyModes.map((mode,i)=>[mode,this.report.modeDelta.reduce((sum,row)=>sum+row[i],0)]));
    this.passengers=new ScheduledPassengers({manifest,routeData:id=>loadRouteGeometry(this.json,schedule+id+".json")},
      this.places,this.refresh,error=>this.error(error));
    return this;
  }
  error(error){el("vehicle-access-status").textContent=error.message;}
  async downtown(){
    const report=await this.json(this.root+"vehicle-access/"+this.version+"_downtown.json");
    if(report.vehicleAccess!==this.version||report.jointRelease!==this.report.joint)
      throw Error("Downtown counts and household vehicle access use different weekdays.");
    return report;
  }
  hasTrip(d,i,start){return this.departures.has(d+"/"+i+"/"+start);}
  loadResident(da){
    if(!this.areas.has(da))return Promise.resolve();
    if(!this.pending.has(da))this.pending.set(da,this.json(this.base+da+".json").then(rows=>{
      this.shards.set(da,byPerson(rows));this.refresh();
    }).catch(error=>{this.pending.delete(da);throw error;}));
    return this.pending.get(da);
  }
  state(d,i,minute,exact=true){
    const da=this.day.das[d],group=this.shards.get(da);
    if(exact&&!group)this.loadResident(da).catch(error=>this.error(error));
    const rows=(group??this.sample).get(identity(d,i));
    const chosen=rows?.find(row=>row[2]<=minute&&minute<row[2]+row[3]);
    if(!chosen)return null;
    const [,,start,dur,a,b,mode,payload,connections]=chosen;
    if(mode!=="transit")return {mode,start,dur,a:this.places[a],b:this.places[b],routed:true,path:payload,
      p:positionOn(payload,(minute-start)/dur),method:"household vehicle access comparison"};
    const row=[da,i,start,dur,a,b,...payload];
    const missing=new Set();
    for(let leg=row;leg;leg=onwardRide(leg))if(!this.passengers.routes.has(leg[6]))missing.add(leg[6]);
    if(missing.size){
      for(const route of missing)this.passengers.routeData(route).catch(error=>this.error(error));
      return {mode,scheduled:true,start,dur,positionNote:"loading scheduled vehicle"};
    }
    const walking={route:(p,q)=>connections.find(path=>same(path[0],p)&&same(path.at(-1),q))};
    const position=row[12]?this.passengers.transferPosition(row,minute,walking):this.passengers.position(row,minute,walking,true);
    return {...position,mode,start,dur,scheduled:true};
  }
}

export function showVehicleAccess(release,active,day,follow){
  if(!release)return;
  const {version,report}=release,panel=el("vehicle-access"),link=el("vehicle-access-replay");
  const url=new URL(location.href);
  if(active)url.searchParams.delete("vehicleRun");else url.searchParams.set("vehicleRun",version);
  url.hash="vehicle-access";
  link.href=url;
  link.textContent=active?"Replay the combined weekday before vehicle access":"Replay with household vehicle access";
  const {stats}=report;
  el("vehicle-access-status").textContent=fmt(stats.switchedTours)+" of "+fmt(stats.candidateTours)+
    " complete driver tours can switch within their existing times. "+fmt(stats.assignedNoVehicleDriverTrips-stats.switchedTrips)+
    " driver trips in households assigned no vehicle still use their original mode in this comparison.";
  const examples=el("vehicle-access-examples");
  for(const [mode,label] of [["walk","Walking"],["bike","Cycling"],["transit","Transit"]]){
    const trip=report.examples[mode];
    if(!trip)continue;
    const text=label+" · "+fmt(stats.modes[mode])+" trips";
    if(active){
      const button=document.createElement("button");button.type="button";button.textContent=text;
      button.onclick=()=>{
        const [d,i,start,length]=trip;
        follow(day.das[d],i,mode==="transit"?start+0.1:start+length/2).catch(error=>active.error(error));
      };
      examples.append(button);
    }
  }
  panel.hidden=false;
  if(active||location.hash==="#vehicle-access")panel.open=true;
}
