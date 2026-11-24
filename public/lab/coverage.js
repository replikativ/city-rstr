import {changeStudyArea} from "../js/replay/replay.js";

import {loadManifest} from "./run-manifest.js";

const params=new URLSearchParams(globalThis.location?.search);
// Archived scenarios without an explicit coverage parameter use the municipal roster.
const overviewLink=!globalThis.location?.hash&&[...params.keys()].every(key=>["city","minute"].includes(key));
export const regional=params.get("coverage")==="region"||overviewLink;
export const coverageParams={coverage:regional?"region":"city"};
if(params.has("dayRun"))coverageParams.dayRun=params.get("dayRun");
if(!regional&&params.has("jointRun"))coverageParams.jointRun=params.get("jointRun");
if(!regional&&params.has("shoppingClock"))coverageParams.shoppingClock=params.get("shoppingClock");
if(!regional&&params.has("outboundRoad"))coverageParams.outboundRoad=params.get("outboundRoad");
if(!regional&&params.has("outboundTransit"))coverageParams.outboundTransit=params.get("outboundTransit");
if(!regional&&params.has("outboundClock"))coverageParams.outboundClock=params.get("outboundClock");
export async function publishedWeekday(json,replay){
  if(!params.has("dayRun"))return null;
  const id=params.get("dayRun");
  if(!/^[a-f0-9]{64}$/.test(id))throw Error("Invalid published weekday identifier.");
  const run=await loadManifest("vancouver",id,json);
  const versions=[run.atlas,run.day,run.streets];
  if(regional)versions.push(run.transit);
  if(run.release!==id||run.city!=="vancouver"||run.coverage!==(regional?"region":"city")||
     !versions.every(v=>/^[a-f0-9]{20}$/.test(v))||
     (run.jointRun&&(![run.jointRun,run.incomingTransit].every(v=>/^[a-f0-9]{20}$/.test(v))||regional))||
     (run.outboundRoad&&(!run.jointRun||!/^[a-f0-9]{20}$/.test(run.outboundRoad)))||
     (run.outboundTransit&&(!run.jointRun||!/^[a-f0-9]{20}$/.test(run.outboundTransit)))||
     (replay&&["atlas","day","streets"].some(k=>run[k]!==replay[k])))
    throw Error("The selected weekday and study area or saved opening have different releases.");
  return run;
}
export const scopeName=regional?"Vancouver, UBC & North Shore":"City of Vancouver";

export function layersForNewDay(params){
  if(params.get("buildingHeights")!=="tags")params.delete("buildingHeights");
  for(const key of ["voting","votingRun","votingLayout","votingSite","votingDate","votingSchedule"])params.delete(key);
  params.delete("bridgeChoice");
  params.delete("bridgeDestination");
  params.delete("hiredRides");
  params.delete("dispatchRun");
  params.delete("departureClock");
  params.delete("jointRun");
  params.delete("shoppingClock");
  params.delete("tripTiming");
  params.delete("jointSite");
  params.delete("incomingTransit");
  params.delete("roadGate");
  params.delete("roadDirection");
  params.delete("roadVehicles");
  params.delete("outboundRoad");
  params.delete("outboundTransit");
  params.delete("outboundClock");
  if(params.has("personalTransit"))params.set("personalTransit","1");
  const transit=params.get("workTransit")??"";
  if(/^[a-f0-9]{20}$/.test(transit))params.set("workTransit","flex");
  else if(/^recorded-[a-f0-9]{20}$/.test(transit))params.set("workTransit","1");
  for(const [release,key,value] of [["outingsRun","outings","fit"],["recreationRun","recreation","on"],
    ["schoolRun","schools","on"],["attendanceRun","attendance","on"],["easternOutingRun","easternOutings","on"]]){
    if(!params.has(release))continue;
    params.delete(release);
    params.set(key,value);
  }
}

export async function regionalRelease(root,clock,json){
  const current=await json(root+"current.json");
  if(!clock||clock==="household")return current;
  if(!/^[a-f0-9]{20}$/.test(clock))throw Error("Unknown regional household clock.");
  const report=await json(root+"household-clock/"+clock+"/report.json");
  if(report.atlas===current.atlas&&report.day===current.day)return current;
  if(![report.atlas,report.day].every(v=>/^[a-f0-9]{20}$/.test(v)))throw Error("Invalid regional clock parents.");
  const saved=await json(root+"releases/"+report.atlas+"_"+report.day+".json");
  if(saved.atlas!==report.atlas||saved.day!==report.day)throw Error("Regional release and household clock disagree.");
  return saved;
}

export function linkStudyArea(){
  for(const link of document.querySelectorAll(".masthead a[href='cityday.html'],.masthead a[href='population.html'],.masthead a[href='vancouver.html']")){
    const q=new URLSearchParams(coverageParams);
    if(link.getAttribute("href")==="vancouver.html"){
      q.delete("dayRun");q.delete("outboundRoad");q.delete("outboundTransit");q.delete("outboundClock");
      q.delete("jointRun");q.delete("shoppingClock");
    }
    else for(const key of ["marketRun","clock","scheduled","departureClock"])if(params.has(key))q.set(key,params.get(key));
    if(link.getAttribute("href")==="cityday.html"||params.has("departureClock")&&link.getAttribute("href")==="population.html")
      for(const key of ["workplaceRun","workplaceBasis"])if(params.has(key))q.set(key,params.get(key));
    link.search=q.toString();
  }
}

export function coverageControl(currentMinute){
  linkStudyArea();
  const control=document.getElementById("coverage");
  control.value=regional?"region":"city";
  control.onchange=async()=>{
    const coverage=control.value;
    control.disabled=true;
    const url=new URL(location.href);
    const minute=currentMinute?.();
    if(Number.isFinite(minute))url.searchParams.set("minute",String(minute));
    const runs=await fetch("data/runs/current.json",{cache:"no-cache"})
      .then(r=>r.ok?r.json():[]).catch(()=>[]);
    location.assign(changeStudyArea(url.href,Array.isArray(runs)?runs:[],coverage));
  };
}
