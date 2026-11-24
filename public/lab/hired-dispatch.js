import {track} from "../js/vancouver/route-timeline.js";
import {hiredLabel} from "./hired-rides.js";

const el=id=>document.getElementById(id);
const releaseId=/^[a-f0-9]{20}$/;
const number=new Intl.NumberFormat("en-CA",{maximumFractionDigits:0});
const money=new Intl.NumberFormat("en-CA",{style:"currency",currency:"CAD"});
const minutes=seconds=>seconds===null?"—":(seconds/60).toFixed(1)+" min";
const percentage=value=>value===null?"—":(value*100).toFixed(1)+"%";
const hours=seconds=>(seconds/3600).toFixed(1)+" h";

function position(leg,elapsed){
  if(!leg)return null;
  const along=leg.duration?elapsed*leg.offsets.at(-1)/leg.duration:leg.offsets.at(-1);
  return track(leg.path,leg.offsets,along,0).position;
}

function bearing(leg,elapsed){
  const a=position(leg,Math.max(0,elapsed-1)),b=position(leg,Math.min(leg.duration,elapsed+1));
  return Math.atan2(b[0]-a[0],a[1]-b[1])*180/Math.PI;
}

export function pickupFrame(journey,start,due,seconds){
  if(seconds<start||seconds>=due||journey.miss)return {message:"",vehicle:null,passenger:null};
  const {access,egress,approach,origin,destination,depart,curb,loaded,board,drop,arrive}=journey;
  const roadStart=loaded.path[0],roadEnd=loaded.path.at(-1);
  const passenger=seconds<start+access.duration?position(access,seconds-start):
    seconds<board?roadStart:seconds<drop?null:seconds<arrive?position(egress,seconds-drop):destination;
  const vehicle=seconds<depart?null:
    seconds<curb?position(approach,seconds-depart):seconds<board?roadStart:
    seconds<drop?position(loaded,seconds-board):null;
  const heading=vehicle?(seconds<curb?bearing(approach,seconds-depart):bearing(loaded,Math.max(0,seconds-board))):0;
  const message=seconds<depart?"The passenger has requested a ride. The vehicle is finishing its previous trip.":
    seconds<curb?"The empty vehicle is driving to the pickup.":seconds<board?"The vehicle is waiting at the curb.":
    seconds<drop?"The passenger is on board.":seconds<arrive?"The passenger is going from the curb to the destination.":
    "The passenger has arrived.";
  return {message,vehicle,passenger,heading,occupied:seconds>=board&&seconds<drop};
}

async function releaseFor(root,hire,json){
  const family=root+"hired-dispatch/",requested=new URLSearchParams(location.search).get("dispatchRun");
  const version=requested??(await json(family+hire.version+".json")).version;
  if(!releaseId.test(version))throw Error("Invalid dispatch release.");
  const result=await json(family+version+"/dispatch.json");
  if(result.rides!==hire.version||result.driveProfileDigest!==hire.report.driveProfileDigest||
     Object.entries(hire.report.versions).some(([key,value])=>result.versions[key]!==value))
    throw Error("The dispatch experiment and hired rides use different inputs.");
  const url=new URL(location.href);
  url.searchParams.set("dispatchRun",version);
  history.replaceState(null,"",url);
  return result;
}

export function attachHiredDispatch(root,hire,{json,focus,jump,street,draw,clock,time}){
  const panel=el("hired-dispatch"),service=el("dispatch-service"),fleet=el("dispatch-fleet");
  const replay=el("dispatch-example"),pickup=el("dispatch-pickup"),curb=el("dispatch-curb"),clear=el("dispatch-clear");
  let report,loading,active=false,lastHour=null;

  function render(minute){
    if(!panel.open||!report)return;
    const hour=Math.floor(minute/60),label=clock(hour*60);
    if(lastHour!==hour){
      const {reference,reduced}=report.summaries[service.value];
      const line=data=>{
        const {served,diary,dispatch}=data.calls[hour-4];
        return number.format(served)+" served out of "+number.format(served+diary+dispatch);
      };
      el("dispatch-hour").textContent=label+" requests · Reference "+line(reference)+" · Reduced "+line(reduced);
      lastHour=hour;
    }
    if(!active)return;
    const example=report.examples[service.value],journey=example[fleet.value];
    const seconds=Math.round(minute*60*1e6)/1e6;
    const current=pickupFrame(journey,example.start*60,(example.start+example.duration)*60,seconds);
    el("dispatch-phase").textContent=current.message||"Use the replay clock to return to this request.";
    draw(current,service.value);
  }

  function showExample(){
    const example=report.examples[service.value],journey=example[fleet.value];
    if(!journey)return;
    active=true;
    pickup.hidden=curb.hidden=clear.hidden=false;
    const paths=[journey.approach?.path,journey.loaded.path].filter(Boolean);
    el("dispatch-example-info").textContent=hiredLabel(service.value)+" request at "+clock(example.start)+
      " · "+minutes(journey.curb-example.start*60)+" to pickup · "+clock(journey.arrive/60)+" arrival";
    focus(paths,example.start,[example.d,example.i]);
  }

  function clearExample(){
    active=false;
    pickup.hidden=curb.hidden=clear.hidden=true;
    el("dispatch-phase").textContent="";
    el("dispatch-example-info").textContent="";
    draw(null);
  }

  function showService(){
    const {reference:ref,reduced}=report.summaries[service.value],observed=report.evidence.waitSeconds[service.value];
    const rows=[
      ["Vehicles available",number.format(ref.capacity),number.format(reduced.capacity),"—"],
      ["Requests served",number.format(ref.served),number.format(reduced.served),"—"],
      ["Diary too short",number.format(ref.diary),number.format(reduced.diary),"—"],
      ["No vehicle in time",number.format(ref.dispatch),number.format(reduced.dispatch),"—"],
      ["Median wait for served trips",minutes(ref.median),minutes(reduced.median),minutes(observed)],
      ["90th-percentile served wait",minutes(ref.p90),minutes(reduced.p90),"—"],
      ["Driving to pickups",hours(ref.emptyMovingSeconds),hours(reduced.emptyMovingSeconds),"—"],
      ["Time with passengers",percentage(ref.occupancy),percentage(reduced.occupancy),percentage(report.evidence.occupancy[service.value])],
    ].map(([heading,...values])=>{
      const row=document.createElement("tr"),name=document.createElement("th");
      name.scope="row";name.textContent=heading;row.append(name);
      for(const value of values)row.insertCell().textContent=value;
      return row;
    });
    el("dispatch-metrics").replaceChildren(...rows);
    if(report.reference){
      const original=report.reference.results[service.value];
      const wait=seconds=>seconds===null?"—":Math.round(seconds)+" s";
      el("dispatch-clock-comparison").hidden=false;
      el("dispatch-clock-change").textContent="With the same reference fleet and staging locations, spreading departures changes completed trips from "+
        number.format(original.served)+" to "+number.format(ref.served)+" and median wait among served trips from "+
        wait(original.median)+" to "+wait(ref.median)+".";
      const url=new URL(location.href);
      url.searchParams.delete("departureClock");
      url.searchParams.set("hiredRides",report.reference.rides);
      url.searchParams.set("dispatchRun",report.reference.dispatch);
      url.hash="hired-dispatch";
      el("dispatch-original-clock").href=url;
    }
    const [low,high]=report.evidence.fare5km[service.value];
    el("dispatch-fare").textContent="Monthly median fares for 5 km ranged from "+money.format(low)+" to "+money.format(high)+" in 2024.";
    replay.hidden=!report.examples[service.value];
    lastHour=null;
    if(active){
      if(replay.hidden)clearExample();else showExample();
    }
    render(time());
  }

  panel.ontoggle=async()=>{
    if(!panel.open){clearExample();return;}
    if(report){render(time());return;}
    if(loading)return;
    loading=true;
    try{
      report=await releaseFor(root,hire,json);
      el("dispatch-controls").hidden=false;
      el("dispatch-status").textContent="Requests use Vancouver residents’ fitted hired trips and their original diary deadlines.";
      el("dispatch-wait-source").href=report.evidence.waitSeconds.url;
      el("dispatch-occupancy-source").href=report.evidence.occupancy.url;
      el("dispatch-fare-source").href=report.evidence.fare5km.url;
      showService();
    }catch(error){
      el("dispatch-status").textContent="Dispatch evidence is unavailable for this hired-ride release.";
    }finally{loading=false;}
  };
  service.onchange=showService;
  fleet.onchange=()=>{if(active)showExample();};
  replay.onclick=showExample;
  clear.onclick=clearExample;
  pickup.onclick=()=>jump(report.examples[service.value][fleet.value].board/60);
  curb.onclick=()=>{
    const example=report.examples[service.value],journey=example[fleet.value];
    const target=journey.loaded.path[0],lead=Math.min(8,(journey.curb-journey.depart)/2);
    const incoming=position(journey.approach,journey.curb-journey.depart-lead);
    const heading=incoming?Math.atan2(incoming[0]-target[0],target[1]-incoming[1])*180/Math.PI:
      bearing(journey.loaded,0);
    street(target,(journey.curb-lead)/60,heading);
  };
  return render;
}
