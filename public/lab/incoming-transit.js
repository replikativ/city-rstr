import {onwardRide,publishedStreetWalks,ScheduledPassengers} from "./transit-passenger.js";
import {loadRouteGeometry} from "./regional-transit.js";
import {metroRoadNetwork} from "./vancouver-network.js";

const el=id=>document.getElementById(id);
const fmt=n=>n.toLocaleString("en-CA");
const release=/^[a-f0-9]{20}$/;
const optionalJSON=url=>fetch(url).then(response=>response.ok?response.json():null).catch(()=>null);

function incomingPlayback(root,base,timetable,service,json,places,refresh,onError){
  const directory=timetable?root+"transit/"+timetable+"/":null;
  let playback;
  const shards=new Map();
  return async(group,person)=>{
    playback??=Promise.all([json(base+"homes.json"),directory?json(directory+"transit.json"):service.init()])
      .then(([homes,manifest])=>{
        const vehicles=directory?{manifest,routeData:id=>loadRouteGeometry(json,directory+id+".json")}:service;
        return new ScheduledPassengers(vehicles,[...places,...homes],refresh,onError);
      }).catch(e=>{playback=null;throw e;});
    if(!shards.has(group))shards.set(group,Promise.all([json(base+group+".json"),
      directory?json(base+group+"-walks.json"):null]).catch(e=>{shards.delete(group);throw e;}));
    const [passengers,[rows,paths]]=await Promise.all([playback,shards.get(group)]);
    const legs=rows.filter(row=>row[1]===person);
    const vehicleRoutes=new Set();
    for(const row of legs)for(let leg=row;leg;leg=onwardRide(leg))vehicleRoutes.add(leg[6]);
    await Promise.all([...vehicleRoutes].map(route=>passengers.routeData(route)));
    const walking=paths?publishedStreetWalks(paths,person):null;
    const homeIndex=legs[0]?.slice(4,6).find(i=>i>=places.length);
    return {passengers,legs,walking,home:passengers.places[homeIndex]};
  };
}

export async function loadMunicipalIncoming(root,joint,json,places,refresh,follow,pinned=null,followRoadResident,outboundRoad){
  const family=root+"incoming-transit/";
  let version=pinned;
  if(version===null){
    const response=await fetch(family+joint.id+".json");
    if(response.status===404)return null;
    if(!response.ok)throw Error("Incoming commuter itineraries are unavailable.");
    ({version}=await response.json());
  }
  if(!release.test(version))throw Error("Invalid incoming transit release.");
  const base=family+version+"/",report=await json(base+"report.json");
  if(report.joint!==joint.id||report.residentRiders!==joint.riders||report.workerRelease!==joint.commuters||
     !release.test(report.timetable)||report.homeIndex!==places.length||
     Object.entries(joint.versions).some(([key,value])=>report.versions[key]!==value))
    throw Error("Incoming workers and resident transit use different weekday inputs.");
  const status=el("downtown-incoming-status");
  const scheduled=incomingPlayback(root,base,report.timetable,null,json,places,refresh,e=>{status.textContent=e.message;});
  let comparison=report.timing?.version;
  const homePointer=report.homeFit?Promise.resolve({version:report.homeFit.baseline}):optionalJSON(family+joint.id+"_homes.json");
  let timingPresence=null,durations=null;
  if(report.timing){
    [timingPresence,durations]=await Promise.all([json(root+"incoming-timing-presence/"+version+".json"),
      optionalJSON(root+"incoming-duration-check/"+version+".json")]);
    if(timingPresence.incoming!==version||timingPresence.joint!==joint.id||timingPresence.workerRelease!==report.workerRelease||
       timingPresence.occupancyDelta.length!==1440)
      throw Error("The incoming itinerary and travel clock use different releases.");
    if(durations&&(durations.incoming!==version||durations.joint!==joint.id))durations=null;
  }
  if(!comparison){
    const timing=await optionalJSON(family+joint.id+"_timing.json");
    comparison=timing?.version;
  }
  const {version:homeComparison}=(await homePointer)??{};
  const fitId=report.homeFit?.version??(await optionalJSON(root+"incoming-home-fit/"+joint.id+".json"))?.version;
  const [driveEvidence,crossingEvidence,residentEvidence,outboundEvidence]=release.test(fitId)?await Promise.all([
    optionalJSON(root+"incoming-drives/"+fitId+".json"),optionalJSON(root+"incoming-road-crossings/"+fitId+".json"),
    optionalJSON(root+"resident-road-crossings/"+joint.id+".json"),
    outboundRoad?.evidence]):[null,null,null,null];
  let loadHomeFit=null;
  if(report.homeFit){
    const fit=report.homeFit.version;
    if(!release.test(fit)||!release.test(homeComparison))throw Error("Invalid incoming home fit.");
    const path=root+"incoming-home-fit/"+fit+"/",evidence=await json(path+"report.json");
    if(evidence.joint!==joint.id||evidence.workerRelease!==joint.commuters||
       evidence.baseline!==(report.homeFit.fitBasis??homeComparison))
      throw Error("The incoming home fit belongs to a different weekday.");
    const groups=new Map();
    loadHomeFit=group=>{
      if(!groups.has(group))groups.set(group,json(path+group+".json")
        .then(rows=>new Map(rows.map(([person, ,home])=>[person,home])))
        .catch(error=>{groups.delete(group);throw error;}));
      return groups.get(group);
    };
  }
  const followTrip=(row,replay=scheduled)=>follow(row.slice(0,3),{workerRelease:report.workerRelease,collection:"commuters",scheduled:replay});
  const followWorker=async(group,person,minute,stillSelected)=>{
    if(!report.groups[group]?.[1])throw Error("This worker’s municipality has no scheduled commuting trips in this replay.");
    const data=await scheduled(group,person);
    if(!stillSelected())return;
    if(!data.legs.length)throw Error("This worker has no booked transit trip in this replay.");
    const rank=row=>Math.min((row[2]-minute+1440)%1440,(minute-row[2]+1440)%1440);
    const trip=data.legs.reduce((a,b)=>rank(a)<=rank(b)?a:b);
    return followTrip(trip,()=>data);
  };
  let drive=null,followDriver=null,followResident=null;
  if(driveEvidence?.joint===joint.id&&driveEvidence.homeFit===fitId&&driveEvidence.workerRelease===joint.commuters&&
     driveEvidence.basis==="free-flow"&&release.test(driveEvidence.network)){
    drive=driveEvidence;
    let homes;
    const roadGraph=()=>metroRoadNetwork(root,drive.network,json);
    followResident=async example=>followRoadResident(example,await roadGraph());
    followDriver=async(group,person,minute,stillSelected,atCrossing=false)=>{
      homes??=json(base+"homes.json").then(rows=>new Map(rows.map(row=>[row[3],row])))
        .catch(e=>{homes=null;throw e;});
      const [streets,addresses,cohort,patch]=await Promise.all([roadGraph(),homes,
        json(root+"commuters/"+report.workerRelease+"/"+group+".json"),loadHomeFit?.(group)]);
      if(!stillSelected())return;
      const row=cohort.people[person],home=cohort.homes[patch?.get(person)??row[0]];
      const leave=row[5],back=leave+row[6]+row[7];
      const circular=start=>Math.min((start-minute+1440)%1440,(minute-start+1440)%1440);
      const seek=atCrossing?minute:(circular(leave)<=circular(back)?leave:back)+.15;
      const dayMinute=240+((seek-240)%1440+1440)%1440;
      return follow([group,person,dayMinute],
        {workerRelease:report.workerRelease,collection:"commuters",driver:{home:addresses.get("Home census area "+home),graph:streets}});
    };
  }
  let crossings=drive&&crossingEvidence?.network===drive.network&&crossingEvidence.joint===joint.id&&crossingEvidence.homeFit===fitId&&
    crossingEvidence.workerRelease===joint.commuters&&crossingEvidence.clock===drive.basis?crossingEvidence:null;
  if(crossings&&followRoadResident&&residentEvidence?.joint===joint.id&&residentEvidence.network===drive.network&&
    residentEvidence.clock===drive.basis&&residentEvidence.timetable===joint.transit&&
    Object.entries(joint.versions).every(([key,value])=>residentEvidence.versions?.[key]===value)&&
    Object.entries(joint.workplaces).every(([key,value])=>residentEvidence.workplaces?.[key]===value)&&
    Object.entries(residentEvidence.sources).every(([key,value])=>crossings.sources?.[key]===value)){
    const bySite=sites=>new Map(sites.map(site=>[site.key,site]));
    const matches=(a,b)=>b&&["point","directions","counters"].every(key=>JSON.stringify(a[key])===JSON.stringify(b[key]));
    const residents=bySite(residentEvidence.sites);
    const external=outboundEvidence&&outboundEvidence.jobs===outboundRoad.version&&outboundEvidence.joint===joint.id&&
      outboundEvidence.network===drive.network&&outboundEvidence.clock===drive.basis&&
      Object.entries(outboundEvidence.sources).every(([key,value])=>crossings.sources?.[key]===value)?bySite(outboundEvidence.sites):null;
    const sites=crossings.sites.map(site=>{
      const resident=residents.get(site.key), added=external?.get(site.key);
      const layers=matches(site,resident)?{...resident.layers}:{};
      if(matches(site,added))layers.outboundWork={counts:added.counts,examples:added.examples};
      return Object.keys(layers).length?{...site,layers}:site;
    });
    crossings={...crossings,sites,schedule:residentEvidence.schedule};
  }
  return {report,timingPresence,durations,comparison:release.test(comparison)?comparison:null,
    loadHomeFit,homeComparison:release.test(homeComparison)?homeComparison:null,
    follow:followTrip,followWorker,drive,followDriver,followResident,crossings};
}

export async function attachIncomingTransit(root,versions,service,json,places,refresh,follow){
  const key=[versions.atlas,versions.day,versions.streets].join("_");
  const url=root+"incoming-transit/";
  const requested=new URLSearchParams(location.search).get("incomingTransit");
  let version=requested;
  if(!release.test(version)){
    const response=await fetch(url+key+".json");
    if(response.status===404)return;
    if(!response.ok)throw Error("Incoming transit release is unavailable.");
    ({version}=await response.json());
  }
  if(!release.test(version))throw Error("Invalid incoming transit release.");
  const base=url+version+"/",panel=el("regional-incoming-transit"),status=el("regional-incoming-status");
  let pending;
  panel.ontoggle=()=>{
    if(!panel.open)return;
    pending??=json(base+"report.json").then(report=>{
      if(Object.entries(versions).some(([k,v])=>report.versions[k]!==v)||report.homeIndex!==places.length)
        throw Error("Incoming transit belongs to different simulation inputs.");
      const {rail,outcomes,groups,examples,expanded,transferComparison}=report;
      if(expanded&&![expanded.comparison,expanded.timetable,expanded.walking].every(id=>release.test(id)))
        throw Error("Invalid extended transit or walk release.");
      const total=Object.values(groups).reduce((sum,[n])=>sum+n,0);
      const two=outcomes.twoTransfers||0;
      status.textContent=fmt(outcomes.direct||0)+" direct trips and "+fmt(outcomes.transfer||0)+" with one transfer"+
        (transferComparison?", plus "+fmt(two)+" with two transfers":"")+", out of "+fmt(total)+" incoming work trips assigned to transit.";
      const missing=report.missingStopAccess;
      if(missing)el("regional-incoming-access").textContent="No stop within an 800 m walk for the home only on "+
        fmt(missing.home||0)+" trips, the workplace only on "+fmt(missing.work||0)+", and both on "+fmt(missing.both||0)+".";
      if(transferComparison||expanded){
        const change=el("regional-incoming-comparison"),old=new URL(location.href);
        const earlier=expanded.previousOutcomes,prior=(earlier.direct||0)+(earlier.transfer||0);
        const earlierKey=transferComparison?.version??expanded.comparison;
        if(!release.test(earlierKey))throw Error("Invalid earlier transit comparison.");
        el("regional-incoming-change").textContent=transferComparison?
          fmt(transferComparison.retained)+" earlier itineraries stay fixed on the same network and clock.":
          "The expanded map and timetable match "+fmt(outcomes.direct+outcomes.transfer)+
            " trips on the same weekday. The earlier coverage matches "+fmt(prior)+".";
        old.searchParams.set("incomingTransit",earlierKey);
        old.hash="regional-incoming-transit";
        const link=el("regional-incoming-earlier");
        link.href=old;
        if(transferComparison)link.textContent="Replay with up to one transfer";
        change.hidden=false;
      }
      const tbody=el("regional-incoming-stations");
      for(const [label,hours] of [["07:00–09:00",[7,8]],["16:00–18:00",[16,17]]]){
        const row=tbody.insertRow();
        const counts=[rail.matched,rail.observed].flatMap(table=>[0,1].map(d=>hours.reduce((n,h)=>n+table[h][d],0)));
        for(const value of [label,...counts.map(fmt)])row.insertCell().textContent=value;
      }
      const scheduled=incomingPlayback(root,base,expanded?.timetable,service,json,places,refresh,e=>{status.textContent=e.message;});
      for(const [id,direction] of [["regional-incoming-work","towardWork"],["regional-incoming-home","fromWork"]]){
        const button=el(id),example=examples[direction];
        if(!example)continue;
        button.hidden=false;
        button.onclick=()=>follow(example.slice(0,3),{workerRelease:report.workerRelease,scheduled})
          .catch(e=>{status.textContent=e.message;});
      }
      el("regional-incoming-evidence").hidden=false;
    }).catch(e=>{pending=null;status.textContent=e.message;});
  };
  panel.hidden=false;
  if(requested!==null)panel.open=true;
  if(panel.open)panel.ontoggle();
}
