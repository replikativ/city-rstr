import {loadRouteGeometry} from "./regional-transit.js";
import {onwardRide,publishedStreetWalks,rideTiming,ScheduledPassengers} from "./transit-passenger.js";

const el=id=>document.getElementById(id);
const release=/^[a-f0-9]{20}$/;
const count=n=>n.toLocaleString("en-CA");

async function published(root,joint,incoming,outbound,json,requested){
  if(!incoming||!outbound)return null;
  const folder=root+"transit-shopping/";
  let version=requested;
  if(version===null){
    const response=await fetch(folder+[joint.id,incoming,outbound].join("_")+".json");
    if(response.status===404)return null;
    if(!response.ok)throw Error("The transit shopping comparison is unavailable.");
    ({version}=await response.json());
  }
  if(!release.test(version??""))throw Error("Invalid transit shopping release.");
  const path=folder+version+"/",report=await json(path+"report.json");
  if(report.schema!==1||report.joint!==joint.id||report.riders!==joint.riders||
     report.incoming!==incoming||report.outbound!==outbound||!release.test(report.timetable)||
     Object.entries(joint.versions).some(([key,v])=>report.versions[key]!==v)||
     Object.entries(joint.workplaces).some(([key,v])=>report.workplaces[key]!==v))
    throw Error("The transit shopping comparison uses a different weekday or set of vehicle bookings.");
  return {version,path,report};
}

export async function loadTransitShopping(root,joint,incoming,outbound,places,day,json,refresh,requested){
  const data=await published(root,joint,incoming,outbound,json,requested);
  if(!data)throw Error("The transit shopping comparison requires its published incoming and outbound transit releases.");
  const {version,path,report}=data,schedule=root+"transit/"+report.timetable+"/";
  const [manifest,streetRows]=await Promise.all([json(schedule+"transit.json"),json(path+"street.json")]);
  const people=new Set(streetRows.map(row=>day.das[row[0]]+"/"+row[1]));
  const areas=new Set(report.areas),shards=new Map(),byResident=new Map();
  const error=e=>{el("transit-shopping-status").textContent=e.message;};
  const passengers=new ScheduledPassengers({manifest,routeData:id=>loadRouteGeometry(json,schedule+id+".json")},
    places,refresh,error);
  const routes=leg=>{
    const ids=new Set();
    for(let row=leg;row;row=onwardRide(row))ids.add(row[6]);
    return ids;
  };
  async function loadResident(da){
    if(!areas.has(da))return;
    if(!shards.has(da))shards.set(da,Promise.all([json(path+da+".json"),json(path+da+"-walks.json")])
      .then(([rows,walks])=>{
        for(const row of rows)byResident.set(da+"/"+row[0],{row,walking:publishedStreetWalks(walks,row[0])});
        refresh();
      }).catch(e=>{shards.delete(da);throw e;}));
    await shards.get(da);
  }
  function state(da,i,minute){
    const key=da+"/"+i;
    if(minute<990||minute>=1140||!people.has(key))return null;
    const entry=byResident.get(key);
    if(!entry){
      if(!shards.has(da))loadResident(da).catch(error);
      return null;
    }
    const {row:[,,site,arrive,leave,starts,legs],walking}=entry;
    const storefront=places[site];
    if(arrive<=minute&&minute<leave)
      return {mode:"stop",p:storefront,a:storefront,kind:"store",activityLabel:"Shopping · scheduled transit chain"};
    const k=legs.findIndex(row=>row[2]<=minute&&minute<row[2]+row[3]);
    if(k<0)return null;
    const leg=legs[k],start=starts[k],a=places[leg[4]],b=places[leg[5]];
    if(minute<start)return {mode:"stop",p:a,a,kind:"origin",
      activityLabel:leg[2]===990?"Waiting to leave after work":"Waiting to leave the shop",
      description:"At "+(a[3]||(leg[2]===990?"the workplace":"the shop"))+" until the scheduled departure"};
    const missing=[...routes(leg)].filter(id=>!passengers.routes.has(id));
    if(missing.length){
      for(const id of missing)passengers.routeData(id).catch(error);
      return {mode:"transit",a,b,scheduled:true,description:"Loading the booked journey"};
    }
    const replay=[...leg];
    replay[2]=start;replay[3]=leg[2]+leg[3]-start;
    const ride=replay[12]?passengers.transferPosition(replay,minute,walking):passengers.position(replay,minute,walking,true);
    return {...ride,mode:"transit",a,b,start,dur:replay[3],scheduled:true,activityLabel:"Scheduled transit · shopping chain"};
  }
  async function exampleTimes(){
    const [da,i]=report.example;
    await loadResident(da);
    const {row:[,,,arrive,leave,,legs]}=byResident.get(da+"/"+i);
    const commands=[];
    for(const [index,leg] of legs.entries()){
      const clock=rideTiming(leg,await passengers.routeData(leg[6]),true);
      commands.push([leg[2]===990?"Ride from work":"Ride from the shop",(clock.boardAt+clock.alightAt)/120]);
      if(index===0)commands.push(["At the shop",(arrive+leave)/2]);
    }
    return {da,i,commands};
  }
  return {version,report,streetRows,state,loadResident,exampleTimes,
    delta:minute=>report.occupancyDelta[minute-240]};
}

export async function showTransitShopping(root,joint,incoming,outbound,active,json,follow){
  const info=active??await published(root,joint,incoming,outbound,json,null);
  if(!info)return;
  const {version,report}=info,stats=report.counts;
  const n=key=>count(stats[key]??0);
  const panel=el("transit-shopping-info"),link=el("transit-shopping-link");
  el("transit-shopping-result").textContent=n("priorComplete")+" of "+n("residents")+" residents already had both legs booked. "+
    "This comparison completes "+n("completed")+" more chains with "+n("additionalLegs")+" new bookings. "+
    n("changedStore")+" use a different mapped shop.";
  el("transit-shopping-departures").textContent=n("shiftedWorkDepartures")+
    " additional work-to-shop riders can leave after 16:30 using the three-minute boarding margin. "+
    n("outsideWorkplace")+" residents have an outside workplace. "+n("noSameShopInTimetable")+
    " checked residents have no single shop that fits both legs under the stop, timetable and booking rules.";
  el("transit-shopping-source").href=report.source;
  link.textContent=active?"Replay the original itineraries":"Replay the completed transit chains";
  const update=()=>{
    const url=new URL(location.href),p=url.searchParams;
    if(active)p.delete("transitShopping");else p.set("transitShopping",version);
    p.set("jointRun",joint.id);p.set("incomingTransit",incoming);p.set("outboundTransit",outbound);
    p.set("tripTiming","pm");url.hash="transit-shopping-info";link.href=url;
  };
  update();link.onfocus=update;link.onpointerdown=update;
  panel.hidden=false;
  if(active||location.hash==="#transit-shopping-info")panel.open=true;
  if(active){
    const {da,i,commands}=await active.exampleTimes();
    const actions=el("transit-shopping-actions");
    for(const [label,minute] of commands){
      const button=document.createElement("button");
      button.type="button";button.textContent=label;button.onclick=()=>follow(da,i,minute);
      actions.append(button);
    }
    actions.hidden=false;
  }
}
