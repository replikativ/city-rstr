import {loadRouteGeometry} from "./regional-transit.js";
import {onwardRide,publishedStreetWalks,ScheduledPassengers} from "./transit-passenger.js";

const el=id=>document.getElementById(id);
const release=/^[a-f0-9]{20}$/;
const fmt=n=>n.toLocaleString("en-CA");

export async function loadOutboundTransit(root,joint,incoming,basePlaces,json,refresh,follow,pinned=null){
  const params=new URLSearchParams(location.search),requested=params.get("outboundTransit"),timed=params.get("outboundClock");
  if(!release.test(incoming))return null;
  const active=requested!=="off"&&(requested||pinned);
  const family=root+"outbound-transit/";
  let version=active||pinned;
  if(!version){
    const response=await fetch(family+joint.id+"_"+incoming+".json");
    if(response.status===404)return null;
    if(!response.ok)throw Error("Outbound transit evidence is unavailable.");
    ({version}=await response.json());
  }
  if(!release.test(version))throw Error("Invalid outbound transit release.");
  const dir=family+version+"/",report=await json(dir+"report.json");
  if(report.joint!==joint.id||report.incoming!==incoming||!release.test(report.timetable)||report.basePlaces!==basePlaces.length||
    Object.entries(joint.versions).some(([k,v])=>report.versions[k]!==v)||
    Object.entries(joint.workplaces).some(([k,v])=>report.workplaces[k]!==v))
    throw Error("The outbound transit release uses a different weekday.");

  const details=el("outbound-transit-work"),status=el("outbound-transit-status"),link=el("outbound-transit-link");
  status.textContent=fmt(report.workers)+" residents have a mapped job and "+fmt(report.journeys)+" booked journeys on the "+report.serviceDate+" timetable.";
  link.textContent=active?"Return to municipality-only transit jobs":"Replay mapped transit commutes";
  const updateLink=()=>{
    const url=new URL(location.href);
    if(active&&pinned)url.searchParams.set("outboundTransit","off");
    else if(active)url.searchParams.delete("outboundTransit");
    else url.searchParams.set("outboundTransit",version);
    url.searchParams.delete("outboundClock");
    url.hash="outbound-transit-work";
    link.href=url;
  };
  updateLink();link.onfocus=updateLink;link.onpointerdown=updateLink;
  details.hidden=false;
  if(!active)return null;

  const schedule=root+"transit/"+report.timetable+"/";
  const loadClock=async()=>{
    const family=root+"outbound-transit-clock/";
    let id=timed;
    if(!id){
      const r=await fetch(family+version+".json");
      if(r.status===404)return null;
      if(!r.ok)throw Error("Outbound timing comparison is unavailable.");
      ({version:id}=await r.json());
    }
    if(!release.test(id))throw Error("Invalid outbound timing identifier.");
    const data=await json(family+id+"/clock.json");
    if(data.release!==version||data.joint!==joint.id||data.timetable!==report.timetable||data.journeys!==report.journeys||
      data.occupancyDelta.length!==1440)throw Error("The outbound timing comparison belongs to different vehicle bookings.");
    const [recorded,held,census]=data.durations.meanMinutes.map(n=>n.toFixed(1));
    const atOrigin=data.meanMinutesByStage.atOrigin.toFixed(1);
    el("outbound-transit-timing-summary").textContent="Timing the same vehicles moves "+atOrigin+
      " minutes of the average home-to-work trip from stop waiting to time at the origin. Travel takes "+held+
      " minutes with this timing, "+recorded+" from the recorded departure and "+census+" in the distance-matched Census reference.";
    const toggle=el("outbound-transit-timing-link");
    toggle.textContent=timed?"Use recorded departure times":"Time departures for the booked vehicles";
    const timingLink=()=>{
      const url=new URL(location.href);
      if(timed)url.searchParams.delete("outboundClock");else url.searchParams.set("outboundClock",id);
      url.hash="outbound-transit-work";toggle.href=url;
    };
    timingLink();toggle.onfocus=timingLink;toggle.onpointerdown=timingLink;
    el("outbound-transit-timing").hidden=false;
    return data;
  };
  const [jobs,manifest,calibration]=await Promise.all([json(dir+"places.json"),json(schedule+"transit.json"),loadClock()
    .catch(error=>{if(timed)throw error;return null;})]);
  const places=[...basePlaces,...jobs];
  const available=new Set(report.areas),shards=new Map(),selected=new Map();
  const passengers=new ScheduledPassengers({manifest,routeData:id=>loadRouteGeometry(json,schedule+id+".json")},
    places,refresh,error=>{status.textContent=error.message;});
  const changes=new Map();
  for(const [da,people] of Object.entries(timed?calibration.windows:{}))
    for(const [i,windows] of people)changes.set(da+"/"+i,new Map(windows.map(([start,leave,arrive])=>[start,{leave,arrive}])));
  function view(row,walks){
    const [person,site,work,legs]=row,routes=new Set();
    for(const first of legs)for(let leg=first;leg;leg=onwardRide(leg))routes.add(leg[6]);
    return {job:jobs[site],work,legs,routes,walking:publishedStreetWalks(walks,person)};
  }
  const preview=new Map();
  let audit,last=-1;
  fetch(root+"outbound-transit-audit/"+version+".json").then(r=>r.ok?r.json():null).then(result=>{
    if(result?.release!==version||result.joint!==joint.id||result.timetable!==report.timetable)return;
    audit=result;
    for(const [da,row] of audit.workClock.sample)preview.set(da+"/"+row[0],view(row,audit.sampleWalks[da]));
    if(audit.commuteDurations){
      const {meanMinutes,compared,source}=audit.commuteDurations;
      const [diary,replay,census]=meanMinutes.map(n=>n.toFixed(1));
      el("outbound-transit-duration-summary").textContent="For "+fmt(compared)+" booked home-to-work journeys, the replay averages "+
        replay+" minutes, the original diaries "+diary+" and the distance-matched Census reference "+census+".";
      el("outbound-transit-census").href=source;
      el("outbound-transit-duration").hidden=false;
    }
    refresh();
  }).catch(error=>{status.textContent=error.message;});
  const control=el("outbound-transit-city"),button=el("outbound-transit-follow");
  control.replaceChildren(...Object.keys(report.examples).map(city=>new Option(city,city)));
  el("outbound-transit-actions").hidden=false;
  button.onclick=()=>{
    const [da,person,minute]=report.examples[control.value];
    follow(da,person,changes.get(da+"/"+person)?.get(minute)?.leave??minute).catch(error=>{status.textContent=error.message;});
  };
  return {
    version,
    rail:calibration?.rail,
    downtownDelta:timed?calibration.downtownDelta:null,
    occupancyDelta(minute){return timed?calibration.occupancyDelta[Math.floor(minute)-240]:null;},
    atWork(minute){
      const i=Math.floor(minute)-240,counts=audit?.workClock.counts[i];
      if(!counts)return 0;
      const placed=counts.slice(1).reduce((a,b)=>a+b,0);
      if(i!==last){
        const label=el("outbound-transit-at-work");
        label.textContent=fmt(placed)+" residents from this transit cohort are at their mapped workplaces.";
        label.hidden=false;last=i;
      }
      return placed;
    },
    async loadResident(da,person){
      if(!available.has(da))return;
      const key=da+"/"+person;
      if(selected.has(key))return;
      if(!shards.has(da))shards.set(da,Promise.all([json(dir+da+".json"),json(dir+da+"-walks.json")])
        .catch(error=>{shards.delete(da);throw error;}));
      const [rows,walks]=await shards.get(da),row=rows.find(([i])=>i===person);
      if(!row)return;
      const data=view(row,walks);
      await Promise.all([...data.routes].map(id=>passengers.routeData(id)));
      selected.set(key,data);
    },
    state(da,person,part,minute){
      const key=da+"/"+person,row=selected.get(key)??preview.get(key);
      if(!row)return null;
      const [start,duration,mode,slot]=part;
      if(mode==="stop"&&row.work.includes(slot))return {mode,p:row.job,a:row.job,kind:"job",description:row.job[3]+" · "+row.job[4]};
      const leg=row.legs.find(leg=>leg[2]===start);
      if(!leg)return null;
      const a=places[leg[4]],b=places[leg[5]],window=changes.get(key)?.get(start);
      let replay=leg;
      if(window){
        const {leave,arrive}=window;
        if(minute<leave)return {mode:"stop",p:a,a,activityLabel:"Waiting to leave",description:"At the origin until the scheduled departure"};
        if(minute*60>=arrive)return {mode:"stop",p:b,a:b,activityLabel:"Arrived",description:"At the destination until the next diary activity"};
        replay=[...leg];replay[2]=leave;replay[3]=start+duration-leave;
      }
      const missing=[...row.routes].filter(id=>!passengers.routes.has(id));
      if(missing.length){
        for(const id of missing)passengers.routeData(id).catch(error=>passengers.onError(error));
        return null;
      }
      const state=replay[12]?passengers.transferPosition(replay,minute,row.walking):passengers.position(replay,minute,row.walking,true);
      return state&&{...state,mode:"transit",start:replay[2],dur:replay[3],a,b,scheduled:true};
    }
  };
}
