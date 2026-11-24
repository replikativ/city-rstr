import {createMap,overviewColors} from "../js/replay/replay.js";
import {Network, departureHour, distance, lngLat, xy, positionOn, roadMode, BIKE, CAR, WALK} from "./vancouver-network.js";
import {aimPlayer,eyeLevel,playerCamera,playerLink,playerSprite,startPlayer,stepPlayer,streetBodies,turnAround} from "./street-player.js";
import {WorkPolicy} from "./work-policy.js";
import {CampusVisitors} from "./campus-visitors.js";
import {CampusDay} from "./campus.js";
import {IncomingWorkers} from "./incoming-workers.js";
import {attachIncomingTransit,loadMunicipalIncoming} from "./incoming-transit.js";
import {DowntownTravel} from "./downtown-travel.js";
import {attachDowntownAudit} from "./downtown-audit.js";
import {attachBridgeTraffic,bridgeRoutingMetric} from "./bridge-traffic.js";
import {CityRiders} from "./city-riders.js";
import {RegionalTransit} from "./regional-transit.js";
import {TransitCommutes,commuteClockLink} from "./transit-commutes.js";
import {attachWorkTransit,loadWorkTransitClock} from "./work-transit.js";
import {attachPersonalTransit} from "./personal-transit.js";
import {attachRecreation} from "./recreation-loops.js";
import {loadGranville} from "./granville-visitors.js";
import {attachSchoolEscorts} from "./school-escorts.js";
import {attachAttendance} from "./weekday-attendance.js";
import {archivedRun,marketCatalogue,shoppingDemandPair} from "./market-release.js";
import {jointWeekday,attachDiaryFit,attachIncomeComparison,attachJointEvidence,showJointLink} from "./joint-weekday.js";
import {VehicleAccess,showVehicleAccess,vehicleRelease} from "./vehicle-access.js";
import {GroceryMarket} from "./cityday-market.js";
import {StorefrontStreet} from "./storefront-street.js";
import {storefrontSign} from "./storefront-access.js";
import {NearbyWalks} from "./nearby-walks.js";
import {isScenarioTrip,StreetScenarios} from "./street-scenarios.js";
import {activeStreetLeg,bicycleMetresPerMinute} from "./street-pedestrians.js";
import {affectedSegments,findRoute,routeKey} from "./weekday-pathfinder.js";
import {WeekdayRoutes} from "./weekday-routes.js";
import {corridorEvidence,loadCorridorTimes,workplaceDriveEvidence} from "./road-traffic.js";
import {HiredRides,hiredLabel,hiredRideControls,isHired,loadHiredRides} from "./hired-rides.js";
import {attachHiredDispatch} from "./hired-dispatch.js";
import {homePlacement} from "./home-placement.js";
import {attachTerrain} from "./terrain.js";
import {bridgeDeckLayer,loadBridgeDecks} from "./bridge-decks.js";
import {buildingProperties,loadBuildingHeights,sectionFeatures} from "./building-heights.js";
import {inspector} from "./day-inspector.js";
import {mountClock} from "../js/replay/replay.js";
import {loadOutboundRoadJobs} from "./outbound-road-jobs.js";
import {loadOutboundTransit} from "./outbound-transit.js";
import {track} from "../js/vancouver/route-timeline.js";

import {coverageControl,coverageParams,regional,regionalRelease,publishedWeekday,layersForNewDay} from "./coverage.js";

const el=id=>document.getElementById(id);
const root="data/vancouver/";
const fmt=n=>n.toLocaleString();
const clock=t=>String(Math.floor(t/60)%24).padStart(2,"0")+":"+String(Math.floor(t)%60).padStart(2,"0")+(t>=1440?" +1":"");
const feature=(geometry,properties={})=>({type:"Feature",geometry,properties});
const collection=features=>({type:"FeatureCollection",features});
const point=(p,props)=>feature({type:"Point",coordinates:lngLat(p)},props);
const line=points=>({type:"LineString",coordinates:points.map(lngLat)});
const empty=collection([]);
const qs=new URLSearchParams(location.search);
const streetClock=qs.get("roadClock")==="street";
const bridgeMetric=bridgeRoutingMetric(qs,regional);
let householdClock=qs.get("clock");
let departureClock=qs.get("departureClock");
let censusWorkplaces=!householdClock&&!departureClock&&!regional&&qs.get("workplaces")==="census";
let clockRun,workTransitClock,map,day,atlas,places,meta,extendedFrame,streetBase,dayBase,atlasBase,net,netPromise,cycleNet,cyclePromise,cycleVersion,selected,token=0;
const requestedMinute=Number(qs.get("minute"));
let t=requestedMinute>=240&&requestedMinute<1680?requestedMinute:480;
let playing=false,lastTime=0,follow=false,vehicle=null,lastPaint=-1;
let updateClock;
const tiles=new Map(),keys=new Set(),routeCache=new Map();
let tileWindow="",tileRequest=0,market,buildingHeights,streetShops;
let nearby,streetRequest=0,nearbyPaint=0;
let parkedStreet,streetPaint=0,previousFrame=0;
let granville,granvilleGuest=null,granvilleFrame=[],granvilleDrawn=false;
let eyeHandlers,eyeGround=0,streetNeedsPaint=false,streetCameraHeight,bridgeDecks,deckLayer,freeElevation=false;
const deckTrails=new WeakMap();
let streetActors=[];
const streetInput={accelerator:new Set(),brake:new Set()};
let incomingTrip,bridgeClock,overviewRoutes;
let driveNetwork,bridgeDriveProfileUrl,driveDigest,benchmarkDrive,roadTrafficClock;
let hiredRides,hiredDispatchClock,dispatchResident;
let cycleUrl,refreshCycleCounts,bikeways,bikewayVersion,cycleTours;
let shortWalks,mobility,transit,transitCommutes,workTransit,campus,visitors,policy,cityRiders,downtown,outbound,outings,easternOutings,recreation,schools,attendance,voting;
let personalTransit;
let jointRun,jointOccupancy,vehicleAccess,lunchWalks,outboundRoad,outboundTransit,shoppingClock;
const walksByPerson=new Map();
const shortWalkToggle=()=>el(regional?"regional-short-walks":"short-walks");
const shopWalkers=new Set();
const streetShopLayers=["street-shop-markers","street-shop-signs"];
async function json(url){const r=await fetch(url);if(!r.ok)throw Error("Unable to load "+url);return r.json();}
function message(s){el("instruction").textContent=s;}
function source(name,data=empty){map.addSource(name,{type:"geojson",data});}
function layer(id,source,type,paint){map.addLayer({id,source,type,paint});}
function data(name,value){map.getSource(name).setData(value);}
async function network(){
  if(!netPromise)netPromise=json(streetBase+"network.json").then(v=>net=new Network(v)).catch(e=>{netPromise=null;throw e;});
  return netPromise;
}
function timedNetwork({profileDigest:digest}){
  if(driveNetwork&&digest!==driveDigest)return Promise.reject(Error("These crossings use a different road speed profile."));
  driveDigest=digest;
  if(!driveNetwork)driveNetwork=Promise.all([json(streetBase+"network.json"),fetch(bridgeDriveProfileUrl)]).then(async([network,response])=>{
    if(!response.ok)throw Error("The road speed profile is unavailable.");
    const bytes=await response.arrayBuffer();
    const sha=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)),x=>x.toString(16).padStart(2,"0")).join("");
    if(sha!==digest)throw Error("The road speed profile differs from the counted routes.");
    return new Network(network,null,JSON.parse(new TextDecoder().decode(bytes)));
  }).catch(error=>{driveNetwork=null;throw error;});
  return driveNetwork;
}
function cycleNetwork(){
  if(!cyclePromise)cyclePromise=json(cycleUrl)
    .then(data=>cycleNet=new Network(data,bikeways)).catch(e=>{cyclePromise=null;throw e;});
  return cyclePromise;
}
function part(template){
  return template.parts.find(([s,n])=>s<=t && t<s+n);
}
function streetPath(mode,from,to,budget=Infinity,shortest=false){
  if(mode===BIKE&&cycleUrl&&!cyclePromise)cycleNetwork().then(render).catch(e=>message(e.message));
  const graph=mode===BIKE?cycleNet:net;
  if(!mode||!graph)return null;
  const limit=mode===BIKE&&bikeways?budget:Infinity;
  const key=mode+"/"+from+"/"+to+"/"+limit+(shortest?"/shortest":"");
  if(!routeCache.has(key)){
    let route=from===to?[places[from],places[to]]:graph.route(places[from],places[to],mode,limit,shortest?false:undefined);
    // Keep the over-budget geometry for inspection when the diary has no feasible trip.
    if(!route&&Number.isFinite(limit))route=graph.route(places[from],places[to],mode);
    routeCache.set(key,route);
  }
  return routeCache.get(key);
}
function state(tpl,plans,exact=false,overrides,walks,replacement,diary,bicycleSpeed=bicycleMetresPerMinute,shortest=false){
  const inferred=walks?.find(([, ,s,n])=>s<=t&&t<s+n);
  const current=inferred?[inferred[2],inferred[3],"walk",inferred[4],inferred[5]]:part(tpl);
  const [start,dur,recorded,i,j]=current,mode=replacement??recorded,from=overrides?.get(i)??plans[i],to=overrides?.get(j)??plans[j];
  const a=places[from],b=places[to];
  if(mode==="stop")return {p:a,mode,kind:tpl.slots[i],a};
  if(!a||!b)return {mode};
  const bicycle=mode==="bike"&&exact&&(diary||replacement==="bike");
  const trip=bicycle&&{mode,kind:tpl.slots[j],a,b,start,dur};
  if(bicycle&&!replacement&&diary.episodes.some(([s,n,,m])=>s<start+dur&&s+n>start&&m!=="bike"))
    return {...trip,positionNote:"mixed-mode trip · transfer location unresolved"};
  const road=roadMode(mode);
  const street=exact&&road!==2&&streetPath(road,from,to,dur*bicycleSpeed,shortest),routed=!!street;
  if(bicycle){
    if(!street)return {...trip,positionNote:cycleNet?"no connected bicycle route":cycleUrl?"loading bicycle route":"bicycle network unavailable"};
    const metres=street.reduce((sum,p,k)=>sum+(k?distance(street[k-1],p):0),0);
    if(metres>dur*bicycleSpeed)
      return {...trip,routed,path:street,positionNote:"diary time exceeded · position unresolved"};
  }
  const path=street||[a,b];
  const f=(t-start)/dur;
  const p=routed?positionOn(path,f):[a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f];
  return {p,mode,kind:tpl.slots[j],a,b,path,routed,inferred:!!inferred,start,dur};
}
function workplaceState(d,i,tpl,plan,exact){
  if(!outbound)return null;
  const current=part(day.templates[tpl]);
  const comparison=outbound.state(d,i,tpl,current);
  if(comparison?.external&&outboundTransit){
    const transit=outboundTransit.state(day.das[d],i,current,t);
    if(transit)return transit;
  }
  if(comparison?.external&&outboundRoad){
    const assigned=outboundRoad.state(day.das[d],i,current,t,selected?.daIndex===d&&selected?.i===i);
    if(assigned)return assigned;
  }
  if(!comparison?.replaceMode&&!comparison?.overrides)return comparison;
  const shopping=market?.slots(d,i);
  const overrides=comparison.overrides&&shopping?new Map([...comparison.overrides,...shopping]):comparison.overrides||shopping;
  const trip=state(day.templates[tpl],plan,exact,overrides,null,comparison.replaceMode,
    exact&&!comparison.replaceMode&&selected?.diary,outbound.report.neighbourhoodFit?.activeSpeeds?.Bicycle);
  trip.method=comparison.method;
  if(exact&&trip.a&&trip.b&&!trip.positionNote){
    const modeIndex=outbound.report.modeKeys.indexOf(trip.mode);
    const leg=part(day.templates[tpl]);
    const shopWalk=trip.mode==="walk"&&(shopping?.has(leg[3])||shopping?.has(leg[4]));
    const speed=shopWalk?market.payload.speed:outbound.report.neighbourhoodFit?.activeSpeeds?.[outbound.report.modes[modeIndex]];
    if(speed){
      const metres=trip.routed?trip.path.reduce((sum,p,i)=>sum+(i?distance(trip.path[i-1],p):0),0):distance(trip.a,trip.b);
      const minutes=Math.ceil(metres/speed);
      trip.method+=" · "+trip.dur+" min in diary, "+minutes+" min "+(trip.routed?"via streets":"in a straight line")+" at model speed";
      const hasGraph=trip.mode==="walk"?net:cycleNet;
      if(minutes>trip.dur||(hasGraph&&!trip.routed)){
        trip.p=null;
        trip.positionNote=minutes>trip.dur?"diary time exceeded · position unresolved":"no connected route · position unresolved";
        if(!trip.routed)trip.path=null;
      }
    }
  }
  return trip;
}
function locationName(p,kind){
  if(!p)return "Unresolved";
  const name=p[3]||kind.replaceAll("-"," "),area=day.areas[p[2]];
  return name+(area?" · "+area:"");
}
function mappedMotion(s,diary,{assigned=false,shopping=false,local=false,trail=false,driveMetric,bridgeChoice,exact=false,priority=false}={}){
  if(s.mode==="stop"||s.routed||s.scheduled)return s;
  const mode=roadMode(s.mode);
  if(!mode||!s.a||!s.b||!(s.dur>0)||!overviewRoutes)return {...s,p:null};
  if(diary&&!assigned&&!s.inferred&&!s.outing&&diary.episodes.some(([start,n,,m])=>
    start<s.start+s.dur&&start+n>s.start&&m!==s.mode))return {...s,p:null};
  const fitted=outbound?.report.neighbourhoodFit?.activeSpeeds;
  const speed=s.metresPerMinute??(mode===2?380:mode===BIKE?(s.outing?outings.report.cycleProfile.metresPerMinute:
    assigned?fitted?.Bicycle??bicycleMetresPerMinute:bicycleMetresPerMinute):
    s.outing?outings.report.walkMetresPerMinute:local?80:s.inferred?80:assigned?fitted?.Walking??75:150);
  let route;
  const chosen=bridgeChoice&&mode===CAR&&s.start===bridgeChoice.start&&s.dur===bridgeChoice.duration&&
    (!bridgeChoice.elapsed||bridgeChoice.from===s.a&&bridgeChoice.to===s.b);
  if(chosen){
    route=bridgeChoice.route;
  }else if(s.outing&&exact&&mode===1&&net){
    const key="outing/"+routeKey(mode,s.a,s.b,s.dur,speed,false);
    if(!routeCache.has(key))routeCache.set(key,findRoute(net,mode,s.a,s.b,s.dur,speed,false));
    route=routeCache.get(key);
  }else if(driveMetric&&mode===2&&!s.outing){
    const graph=driveMetric==="distance"?net:benchmarkDrive;
    if(graph){
      const hour=driveMetric==="highway1"?departureHour(s.start):undefined;
      const key="bridge/"+driveMetric+"/"+routeKey(mode,s.a,s.b,s.dur,speed,false,hour);
      if(!routeCache.has(key))routeCache.set(key,findRoute(graph,mode,s.a,s.b,s.dur,speed,false,s.start));
      route=routeCache.get(key);
    }
  }else route=overviewRoutes.get(mode,s.a,s.b,s.dur,speed,mode===BIKE&&!!bikeways&&!shopping,s.outing?undefined:s.start,priority);
  if(!route)return {...s,p:null,path:null,positionNote:route===undefined&&!overviewRoutes.error?
    "finding street route":"street route unresolved"};
  const timed=mode===CAR&&!s.outing&&(chosen?bridgeChoice.elapsed:streetClock);
  const scale=timed?1:route.minutes/s.dur;
  const motion=track(route.path,route.offsets,(t-s.start)*scale,trail?1.5*scale:0);
  return {...s,p:motion.position,path:route.path,trail:motion.trail,routed:true,routeMinutes:route.minutes,
    waitingAtDestination:timed&&t-s.start>=route.minutes,
    method:chosen?bridgeChoice.name:s.method};
}
const driveTiming=(minutes,duration)=>`${minutes.toFixed(1)} min modeled · ${duration} min in diary`;

function elevationMode(elevated){
  if(freeElevation===elevated)return;
  freeElevation=elevated;
  map.setCenterClampedToGround(!elevated);
}

const terrainAt=p=>map.queryTerrainElevation(lngLat(p))??0;
const aboveTerrain=(p,height)=>Math.max(0,height-terrainAt(p));

function selectedPosition(p,path,mode){
  const shown=follow&&!vehicle&&p,deck=shown&&mode&&map.getPitch()>=15&&bridgeDecks?.route(p,path);
  data("selected",p?collection([point(p,{elevated:!!deck})]):empty);
  data("deck-follower",deck?collection(streetBodies([[...p.slice(0,2),{mode,heading:deck.heading,
    surfaceOffset:aboveTerrain(p,deck.height),scenario:true}]])):empty);
  if(!vehicle)elevationMode(!!deck);
  if(shown)map.jumpTo({center:lngLat(p),...(deck?{elevation:deck.height}:{})});
}

function selectedRoute(path,routed){
  let split;
  if(path&&routed&&deckLayer&&map.getPitch()>=15&&!vehicle){
    if(!deckTrails.has(path))deckTrails.set(path,bridgeDecks.sections(path));
    split=deckTrails.get(path);
  }
  deckLayer?.setTrail(split?.deck??[]);
  const visible=split?.ground??(path?[path]:[]);
  data("route",collection(visible.map(points=>feature(line(points),{routed}))));
}

function drawGranville(){
  if(!granvilleFrame.length&&!granvilleDrawn)return;
  granvilleDrawn=granvilleFrame.length>0;
  const eye=eyeLevel(vehicle);
  const points=[],bodies=[];
  for(const {index,p,segment,mode} of granvilleFrame){
    if(index===granvilleGuest)continue;
    if(!eye){points.push(point(p,{guest:index}));continue;}
    if(!segment||distance(p,vehicle.p)>160)continue;
    const heading=Math.atan2(segment[1][0]-segment[0][0],segment[0][1]-segment[1][1])*180/Math.PI;
    const deck=bridgeDecks?.surface(p,segment);
    bodies.push([...p,{guest:index,mode,heading,visitor:true,surfaceOffset:deck?aboveTerrain(p,deck.height):0}]);
  }
  data("granville-guests",collection(points));
  data("granville-bodies",collection(streetBodies(bodies)));
}

function followGranville(index,minute){
  if(!granville?.report.visits[index])return;
  if(!granville.active)granville.enable(true);
  token++;streetRequest++;
  play(false);parkStreet();
  incomingTrip=null;selected=null;granvilleGuest=index;follow=true;
  el("granville-guest").selectedIndex=index;
  el("follow").textContent="Stop following";
  map.jumpTo({zoom:16.7,pitch:52});
  const url=new URL(location.href);
  granville.pin(url);
  url.searchParams.set("granvilleGuest",String(index));
  history.replaceState(null,"",url);
  setTime(minute);
}

function stopGranvilleFollow(){
  if(granvilleGuest===null)return;
  granvilleGuest=null;
  const url=new URL(location.href);
  url.searchParams.delete("granvilleGuest");
  history.replaceState(null,"",url);
  if(!selected){
    selectedPosition(null);selectedRoute(null,true);
    for(const id of ["who","activity","location"])el(id).textContent="";
  }
}

function renderIncoming(){
  const {label,home,work,start,workStart,workEnd,homeEnd,shifts,there,back,scheduled,graph,roadClock}=incomingTrip;
  const minute=start+(t-start+1440)%1440;
  const outward=minute<workStart,returning=minute>=workEnd&&minute<homeEnd;
  const travelling=outward||returning,route=outward?there:returning?back:null;
  const duration=outward?workStart-start:homeEnd-workEnd;
  const elapsed=minute-(outward?start:workEnd);
  const fraction=elapsed/duration;
  const duringShift=!outward&&minute<workEnd;
  const atWork=duringShift&&shifts.some(([a,b])=>minute>=workStart+a&&minute<workStart+b);
  let path=route?.path??route,description,mode=CAR,reached=false;
  let p=atWork?work:duringShift?null:home;
  if(travelling&&scheduled){
    const state=route&&(route[12]?scheduled.transferPosition(route,minute,graph):scheduled.position(route,minute,graph,true));
    ({path,p}=state||{});
    if(state?.description?.startsWith("Walking ")&&!state.routed){p=null;path=null;}
    description=state?.description??"Transit · schedule unresolved";
    mode=description.startsWith("Walking ")?WALK:null;
  }else if(travelling){
    const travelMinutes=route?.offsets&&(roadClock?Math.min(elapsed,route.minutes):fraction*route.minutes);
    p=path&&(route.offsets?track(path,route.offsets,travelMinutes,0).position:positionOn(path,fraction));
    description=route?.offsets?"Car driver · "+driveTiming(route.minutes,duration):path?"Car driver · street route":"Car driver · route unresolved";
    reached=!!(roadClock&&route?.offsets&&elapsed>=route.minutes);
    if(reached){
      p=outward?work:home;
      description=outward?locationName(work,"workplace"):"Home outside the resident roster";
      mode=null;
    }
  }
  el("who").textContent=label;
  el("activity").textContent=reached?(outward?"Waiting for work":"At home"):travelling ? (scheduled?(outward?"Transit to work":"Transit home"):
    (outward?"Driving to work":"Driving home")) :
    atWork?"Paid work":duringShift?"Between work activities":"At home";
  el("location").textContent=travelling ? description :
    atWork?locationName(work,"workplace"):duringShift?"Location unresolved":"Home outside the resident roster";
  el("atlas").hidden=true;
  selectedPosition(p,path,mode);
  selectedRoute(path,true);
  el("follow").disabled=!p;
}
async function followIncoming(root,[group,i,minute],{workerRelease,collection="incoming-workers",speed=380,routing,scheduled,driver}){
  const revision=++token,scene=streetRequest;
  const base=root+collection+"/"+workerRelease+"/";
  const timed=!!(routing||driver);
  const [report,cohort,roadGraph,transitTrip]=await Promise.all([json(base+"commuters.json"),json(base+group+".json"),
    scheduled?null:driver?.graph??(timed?timedNetwork(routing):network()),scheduled?.(group,i)]);
  if(revision!==token||scene!==streetRequest)return;
  const graph=roadGraph??transitTrip?.walking??await network();
  if(revision!==token||scene!==streetRequest)return;
  const [h,j,,,,start,duration,span,attending,template]=cohort.people[i];
  if(!attending)throw Error("This worker is away from the workplace on this weekday.");
  const home=driver?.home??cohort.homePoints?.[h]??transitTrip?.home,work=places[j],info=report.groups[group];
  if(!home)throw Error("The incoming worker's home is unresolved.");
  const workStart=start+duration,workEnd=workStart+span;
  const there=transitTrip?transitTrip.legs.find(row=>row[5]===j):
    timed?graph.driveRoute(home,work,duration,start):graph.route(home,work,2,duration*speed);
  const back=transitTrip?transitTrip.legs.find(row=>row[4]===j):
    timed?graph.driveRoute(work,home,duration,workEnd):graph.route(work,home,2,duration*speed);
  if(transitTrip&&(there&&there[2]+there[3]!==workStart||back&&back[2]!==workEnd))
    throw Error("The commuter itinerary and paid shift have different times.");
  const homeStart=transitTrip&&there?there[2]:start;
  const homeEnd=workEnd+(transitTrip&&back?back[3]:duration);
  stopGranvilleFollow();
  incomingTrip={label:info.name+" → "+(info.destination??"Vancouver")+" · incoming worker "+(i+1),
    home,work,start:homeStart,workStart,workEnd,homeEnd,shifts:report.workSpans[template],there,back,
    scheduled:transitTrip?.passengers,graph,roadClock:!!driver};
  streetRequest++;
  play(false);parkStreet();follow=true;el("follow").textContent="Stop following";
  map.jumpTo({zoom:16.7,pitch:52});setTime(minute);
}
function render(){
  if(!day || !map?.getSource("residents"))return;
  const minute=Math.floor(t),counts=day.occupancy[minute-240],areaCount=day.areas.length;
  const transitAtWork=outboundTransit?.atWork(minute)??0;
  const roadAtWork=outboundRoad?.atWork(minute,transitAtWork)??0;
  const externalAtWork=roadAtWork+transitAtWork,timing=outboundTransit?.occupancyDelta(minute);
  bridgeClock?.(minute);
  roadTrafficClock?.(minute);
  hiredDispatchClock?.(t);
  const votingDelta=voting?.delta(minute);
  const include=shortWalks&&shortWalkToggle().checked;
  schools?.checkLayers(outings,clockRun??workTransitClock,recreation);
  attendance?.checkLayers(outings,clockRun??workTransitClock,recreation,schools,workTransit);
  personalTransit?.checkLayers(workTransit,outings,attendance);
  recreation?.checkLayers(outings,workTransitClock,include,(schools?.adultTrips()??0)+(attendance?.adultTrips()??0));
  nearby?.refreshScenarios();
  const added=(include?shortWalks.occupancyDelta[minute-240][areaCount]:0)+(outings?.delta(minute)?.[areaCount]??0)
    +(easternOutings?.delta(minute)?.[areaCount]??0)
    +(recreation?.delta(minute)?.[areaCount]??0)+(schools?.delta(minute)?.[areaCount]??0)
    +(attendance?.delta(minute)?.[areaCount]??0);
  updateClock({text:clock(t),minute});
  const combined=jointOccupancy?.[minute-240];
  const unresolved=(combined?.[areaCount+1]??(counts[areaCount+1]-(outbound?.report.relocated[minute-240][areaCount]||0)))+
    (market?.effects?.occupancyAt(minute-240,areaCount)||0)-externalAtWork+(timing?.[areaCount+1]??0);
  const movingTotal=(combined?.[areaCount]??(counts[areaCount]+added))+(lunchWalks?.delta(minute)?.[areaCount]??0)+
    (timing?.[areaCount]??0)+(votingDelta?.[areaCount]??0)+(shoppingClock?.delta(minute)?.[areaCount]??0);
  el("moving").textContent=fmt(movingTotal);el("missing").textContent=fmt(unresolved);
  el("placed").textContent=fmt(day.population-movingTotal-unresolved);
  if(outbound){
    el("outside-now").textContent=fmt(outbound.report.externalByMinute[minute-240])+" residents are at workplaces outside Vancouver."+
      (externalAtWork?" "+fmt(externalAtWork)+" have mapped workplaces.":"");
    outbound.occupancy(minute-240,counts,market?.effects,timing,votingDelta);
  }
  cycleTours?.atMinute(t);market?.atMinute(t);streetShops?.refresh();downtown?.render(t,market,cycleTours);transit?.render(t);campus?.render(t);visitors?.render(t);policy?.render(t,selected);
  if(granville){granvilleFrame=granville.render(t);drawGranville();}
  voting?.atMinute(t);
  workTransit?.compareOutings(outings);
  const customers=[],walking=cityRiders?.renderWalks(t,net,selected)||new Set();
  const groceryWalks=market?.active?market.walks:null;
  const showTrails=!vehicle&&el("route-trails").checked;
  const dots=[],trails=[];
  if(!vehicle)for(const visit of groceryWalks?.proposals??[]){
    const {d,i}=visit;
    if((selected?.daIndex===d&&selected.i===i)||groceryWalks.visit(d,i,t)!==visit)continue;
    const s=groceryWalks.resolve(visit,t,showTrails);
    if(!s.routed)continue;
    walking.add(d+"/"+i);
    customers.push(point(s.p,{d,i}));
    if(s.trail?.length>1)trails.push(feature(line(s.trail),{mode:WALK}));
  }
  shopWalkers.clear();
  if(market?.active)for(const leg of market.walkers||[]){
    if(t<leg.start||t>=leg.end)continue;
    const path=streetPath(roadMode(leg.mode),leg.from,leg.to,(leg.end-leg.start)*bicycleMetresPerMinute,leg.mode==="bike");
    if(!path)continue;
    shopWalkers.add(leg.d+"/"+leg.i);
    walking.add(leg.d+"/"+leg.i);
    if(selected?.daIndex===leg.d&&selected.i===leg.i)continue;
    customers.push(point(positionOn(path,(t-leg.start)/(leg.end-leg.start)),{d:leg.d,i:leg.i}));
  }
  if(market?.active)data("shop-walkers",collection(customers));
  let onPaths=0,travelling=0;
  overviewRoutes?.begin(t);
  if(lunchWalks?.active&&!vehicle)for(const [d,i] of lunchWalks.rows){
    let state=lunchWalks.state(d,i,t);
    if(!state)continue;
    walking.add(d+"/"+i);
    if(selected?.daIndex===d&&selected.i===i)continue;
    if(state.mode==="walk")state=mappedMotion(state,null,{assigned:true,trail:showTrails});
    if(state.p)dots.push(point(state.p,{d,resident:i,moving:state.mode==="walk",mode:roadMode(state.mode)}));
    if(state.trail?.length>1)trails.push(feature(line(state.trail),{mode:roadMode(state.mode)}));
  }
  for(let i=0;i<day.sample.length;i++){
    const [d,index,tpl,p]=day.sample[i];
    if((selected?.daIndex===d&&selected.i===index)||(dispatchResident?.[0]===d&&dispatchResident[1]===index)||
       (walking.size&&walking.has(d+"/"+index)))continue;
    const grocery=groceryWalks?.state(d,index,t,showTrails);
    if(grocery){
      const moving=grocery.mode==="walk",mode=moving?WALK:0;
      if(moving){
        if(vehicle)continue;
        travelling++;
        if(grocery.routed)onPaths++;
      }
      if(grocery.p)dots.push(point(grocery.p,{i,moving,mode,hired:false}));
      if(grocery.trail?.length>1)trails.push(feature(line(grocery.trail),{mode,hired:false}));
      continue;
    }
    const riding=!!cycleTours?.riding(d,index,t);
    const shopping=!!market?.cycleLeg(d,index,part(day.templates[tpl])[0]);
    const local=market?.walkLegs?.has(d+"/"+index+"/"+part(day.templates[tpl])[0]);
    const work=workplaceState(d,index,tpl,p,false);
    const da=day.das[d];
    const scheduled=transitCommutes?.passenger(da,index,t,net)||workTransit?.passenger(da,index,t,net)||
      (personalTransit?.enabled?personalTransit.passenger(da,index,t,net):null)||campus?.passenger(da,index,t,null)||
      (cityRiders?.pinned?cityRiders.passenger(da,index,t,net,false):null);
    const replacement=vehicleAccess?.state(d,index,t,false);
    const poll=voting?.state(d,index,t,net);
    const shifted=shoppingClock?.state(d,index,t);
    let s=replacement||(poll?.detour&&poll)||(jointRun&&scheduled)||lunchWalks?.state(d,index,t)||work||scheduled||poll||shifted||outings?.state(d,index,t,net)||easternOutings?.state(d,index,t)||recreation?.state(d,index,t,showTrails)||schools?.state(d,index,t,showTrails)||
      attendance?.state(d,index,t,net,showTrails)||
      state(day.templates[tpl],p,false,market?.slots(d,index),include?walksByPerson.get(d+"/"+index):null,local?"walk":riding||shopping?"bike":null);
    if(hiredRides&&!market?.slots(d,index)?.size)s=hiredRides.apply(s,d,index);
    const moving=s.mode!=="stop";
    if(moving){
      if(vehicle)continue;
      travelling++;
      s=replacement?{...replacement,trail:showTrails?replacement.path:null}:scheduled?{...scheduled,scheduled:true}:mappedMotion(s,atlas.templates[tpl],
        {assigned:!!work||riding||shopping||!!local||s.hired||!!shifted,shopping,local,trail:showTrails});
      if(s.p)onPaths++;
    }
    const mode=scheduled||s.scheduled?8:moving?roadMode(s.mode):0;
    const hired=isHired(s.mode);
    if(s.p)dots.push(point(s.p,{i,moving,mode,hired}));
    if(s.trail?.length>1)trails.push(feature(line(s.trail),{mode,hired}));
  }
  data("residents",collection(dots));
  data("travel-trails",collection(trails));
  const routeStatus=el("route-status");
  routeStatus.hidden=!!vehicle;
  const routeText=overviewRoutes?.error||fmt(onPaths)+" of "+fmt(travelling)+" sampled trips on mapped paths"+
    (overviewRoutes?.requests.size||overviewRoutes?.inFlight.size?" · finding routes":"");
  if(routeStatus.textContent!==routeText)routeStatus.textContent=routeText;
  if(granvilleGuest!==null){
    const frame=granville.state(granvilleGuest,t);
    el("who").textContent="Tourist "+(granvilleGuest+1)+" · "+frame.origin;
    el("activity").textContent=frame.activity;
    el("location").textContent=frame.path?"Mapped "+(frame.mode===BIKE?"bicycle":"walking")+" route":frame.visible?"Public Market":frame.origin;
    el("atlas").hidden=true;
    selectedPosition(frame.p,frame.path,frame.mode);
    selectedRoute(frame.path,true);
    el("follow").disabled=false;
    overviewRoutes?.flush();
    return;
  }
  if(incomingTrip||!selected){
    if(regional)data("outing-vehicle",empty);
    overviewRoutes?.flush();
    if(incomingTrip)renderIncoming();
    return;
  }
  if(el("who").textContent!==selected.label)el("who").textContent=selected.label;
  el("atlas").hidden=false;
  const {d,i,p,tpl,diary}=selected,riding=!!cycleTours?.riding(selected.daIndex,i,t);
  const local=market?.walkLegs?.has(selected.daIndex+"/"+i+"/"+part(day.templates[tpl])[0]);
  const shopping=!!market?.cycleLeg(selected.daIndex,i,part(day.templates[tpl])[0]);
  const exact=!selected.overview;
  const work=workplaceState(selected.daIndex,i,tpl,p,exact);
  const timedTrip=transitCommutes?.passenger(d,i,t,net);
  const busLoad=transitCommutes?.busOccupancy(timedTrip,t)||"";
  if(follow&&!netPromise&&timedTrip&&!timedTrip.routed&&timedTrip.description?.startsWith("Walking "))
    network().then(render).catch(e=>message(e.message));
  const workRide=workTransit?.passenger(d,i,t,net,true);
  const personalRide=personalTransit?.enabled?personalTransit.passenger(d,i,t,net,true):null;
  const scheduled=timedTrip||workRide||personalRide||campus?.passenger(d,i,t,net)||cityRiders?.passenger(d,i,t,net);
  const replacement=vehicleAccess?.state(selected.daIndex,i,t);
  const poll=voting?.state(selected.daIndex,i,t,net);
  const shifted=shoppingClock?.state(selected.daIndex,i,t);
  const grocery=groceryWalks?.state(selected.daIndex,i,t);
  let s=grocery||replacement||(poll?.detour&&poll)||(jointRun&&scheduled)||lunchWalks?.state(selected.daIndex,i,t)||work||scheduled||poll||shifted||outings?.state(selected.daIndex,i,t,net)||easternOutings?.state(selected.daIndex,i,t)||recreation?.state(selected.daIndex,i,t,false,true)||
    schools?.state(selected.daIndex,i,t,false,true)||attendance?.state(selected.daIndex,i,t,net,false,true)||
    state(day.templates[tpl],p,exact,market?.slots(selected.daIndex,i),
    include?walksByPerson.get(selected.daIndex+"/"+i):null,local?"walk":riding||shopping?"bike":null,diary,bicycleMetresPerMinute,shopping);
  if(hiredRides&&!market?.slots(selected.daIndex,i)?.size)s=hiredRides.apply(s,selected.daIndex,i);
  if(!grocery&&!replacement&&!scheduled&&(selected.overview||roadMode(s.mode)===2||s.outing||shifted))
    s=mappedMotion(s,diary,{assigned:!!work||riding||shopping||!!local||s.hired||!!shifted,shopping,local,
      driveMetric:selected.driveMetric,bridgeChoice:selected.bridgeChoice,exact,priority:true});
  if(s.mode!=="stop"&&!scheduled&&!s.scheduled&&!s.routed&&!s.positionNote&&s.p)
    s={...s,p:null,path:null,positionNote:"street route unresolved"};
  overviewRoutes?.flush();
  if(!grocery&&local)s.method="local grocery walk · originally car driver";
  if(!grocery&&riding)s.method="cycling outing · originally car driver";
  const episode=diary.episodes.find(([start,dur])=>start<=t&&t<start+dur);
  const access=cycleTours?.access(selected.daIndex,i);
  el("tour-person-access").textContent=cycleTours?.mode()==="access"&&access?
    (access===2?"Bicycle access assigned":"No bicycle access assigned")+" in the survey-based scenario.":"";
  const activity=s.outing||s.recreation||s.school||s.attendance;
  el("activity").textContent=s.activityLabel??(activity?clock(s.start)+"–"+clock(s.start+s.dur)+" · "+activity:
    s.inferred?clock(s.start)+"–"+clock(s.start+s.dur)+" · inferred short walk":
    clock(episode[0])+"–"+clock(episode[0]+episode[1])+" · "+episode[2].replaceAll("-"," "));
  const streetDetail=roadMode(s.mode)===2&&s.routeMinutes!==undefined?
    s.outing||s.attendance?Math.ceil(s.routeMinutes)+" min modeled drive":driveTiming(s.routeMinutes,s.dur):"street route";
  el("location").textContent=s.description?s.description+busLoad:s.waitingAtDestination?
    "At "+locationName(s.b,s.kind||"destination")+" · diary stop starts at "+clock(s.start+s.dur):
    (s.mode==="stop"?locationName(s.a,s.kind)+(s.method?" · "+s.method:""):
    (isHired(s.mode)?hiredLabel(s.mode):s.mode.replaceAll("-"," "))+" → "+locationName(s.b,s.kind||"destination")+
    (s.positionNote?" · "+s.positionNote:s.p?(s.routed?" · "+streetDetail:" · interpolated"):" · endpoint unresolved")+(s.method?" · "+s.method:""));
  selectedPosition(s.p,s.path,roadMode(s.mode));
  if(regional)data("outing-vehicle",(s.outing||s.attendance||s===workRide||s===personalRide)&&s.vehicle?collection([point(s.p,{})]):empty);
  selectedRoute(s.path,s.routed);
  el("follow").disabled=!s.p;
  const params=new URLSearchParams({...coverageParams,area:atlas.das[d].area||Object.keys(atlas.areas).find(n=>atlas.areas[n].das.includes(d)),da:d,resident:String(i+1),minute:t});
  if(qs.has("marketRun"))params.set("marketRun",qs.get("marketRun"));
  if(clockRun?.kind==="spread-departures"){
    params.set("departureClock",clockRun.version);
    if(qs.has("workplaceRun"))params.set("workplaceRun",qs.get("workplaceRun"));
    if(qs.has("workplaceBasis"))params.set("workplaceBasis",qs.get("workplaceBasis"));
  }else if(clockRun)params.set("clock",clockRun.version);
  if(workTransitClock){
    params.set("clock",workTransitClock.version);
    if(outings?.active)params.set("outingsRun",outings.version);
  }
  if(personalRide){
    params.set("workplaceRun",personalTransit.report.workplaceRun);
    params.set("personalTransit",personalTransit.version);
    params.set("follow","1");
  }
  if(recreation?.active||s.recreation){
    if(recreation.report.workplaceRun)params.set("workplaceRun",recreation.report.workplaceRun);
    if(recreation.active)params.set("recreationRun",recreation.version);
    else params.set("recreation","1");
  }
  if(schools?.active){
    params.set("workplaceRun",schools.report.workplaceRun);
    params.set("schoolRun",schools.version);
    if(include)params.set("walks","fit");
  }
  if(attendance?.active){
    params.set("workplaceRun",attendance.report.workplaceRun);
    params.set("attendanceRun",attendance.version);
    if(include)params.set("walks","fit");
    if(outings?.active)params.set("outingsRun",outings.version);
  }
  if(easternOutings?.active){
    params.set("workplaceRun",easternOutings.report.workplaceRun);
    params.set("easternOutingRun",easternOutings.version);
  }
  if(voting?.active){
    params.set("votingRun",voting.version);params.set("votingLayout",voting.layout);
    if(voting.date)params.set("votingDate",voting.date);
    if(voting.schedule!=="recorded")params.set("votingSchedule",voting.schedule);
    if(voting.site)params.set("votingSite",voting.site.id);
  }
  if(transitCommutes)params.set("scheduled","1");
  if(bikewayVersion)params.set("bikeRoutes",bikewayVersion);
  if(cycleTours?.mode()&&cycleTours.mode()!=="diary"){
    params.set("cycleTours",cycleTours.mode());params.set("tourZone",el("tour-zone").value);
    params.set("tourPurpose",el("tour-purpose").value);
  }
  el("atlas").textContent=riding||s.outing||s.school||s.attendance||(s.recreation&&s.added)?"Inspect household and original diary":"Inspect household and diary";
  if(el("cycle-check").open){
    params.set("cycleCheck",el("cycle-site").value);
    if(follow)params.set("follow","1");
  }
  if(!regional&&!clockRun){
    if(!outbound&&(shortWalks?!include:qs.get("walks")==="diary"))params.set("walks","diary");
    const site=el("pedestrian-site");
    if(el("pedestrian-check").open&&site.dataset.version){
      params.set("crossing",site.value);params.set("crossingRun",site.dataset.version);
      if(el("pedestrian-transit").checked&&site.dataset.riders)params.set("transitWalks",site.dataset.riders);
    }
    if(el("transit-panel").open&&transit?.route){
      params.set("service",transit.route.name);
      if(cityRiders?.version)params.set("riderRun",cityRiders.version);
    }
  }
  if(outbound)params.set("workplaces","census");
  if(outbound&&outbound.commuteRule()!=="diary")params.set("commute",outbound.commuteRule());
  if(market?.active&&market.payload){
    if(market.catalog?.localWalk)params.set("localWalk","1");
    if(market.catalog?.purchase)params.set("grocery",market.catalog.purchase.key);
    if(el("market-basket").value&&el("market-basket").validity.valid)params.set("basket",el("market-basket").value);
    params.set("shop",market.site?.id||"baseline");params.set("hours",market.hours);
    market.openingParams(params);
  }
  el("atlas").href="population.html?"+params;
}
function play(set){
  playing=set;updateClock({playing});lastTime=0;
}
function setTime(value){
  t=value>=240&&value<1680?value:240+((value-240)%1440+1440)%1440;render();
  const url=new URL(location.href);url.searchParams.set("minute",String(t));history.replaceState(null,"",url);
}
async function choose(d,i,overview=true,driveMetric=null){
  const revision=++token;
  const [roster,locations]=await Promise.all([json(atlasBase+d+".json"),json(dayBase+d+".json"),outboundRoad?.loadResident(d),
    outboundTransit?.loadResident(d,i)]);
  if(revision!==token)return;
  i=Math.max(0,Math.min(Math.trunc(i)||0,roster.people.length-1));
  (clockRun??workTransitClock)?.applyRoster(d,roster);
  const tpl=roster.people[i][7];
  const label=d+"-P"+(i+1)+" · age "+(atlas.ages[roster.people[i][0]-1]||"unavailable");
  incomingTrip=null;stopGranvilleFollow();
  selected={d,label,overview,driveMetric,home:locations.home[i],labour:roster.people[i][2],occupation:roster.people[i][5],daIndex:day.das.indexOf(d),i,p:locations.plans[i],tpl,diary:atlas.templates[tpl]};
  workTransit?.loadResident(d).catch(e=>message(e.message));
  personalTransit?.loadResident(d).catch(e=>message(e.message));
  recreation?.loadResident(d).catch(e=>message(e.message));
  schools?.loadResident(d).catch(e=>message(e.message));
  attendance?.loadResident(d).catch(e=>message(e.message));
  el("da").value=d;el("person").value=i+1;el("person").max=roster.people.length;
  const url=new URL(location.href);url.searchParams.set("da",d);url.searchParams.set("person",i+1);history.replaceState(null,"",url);
  render();
}
async function showTiles(){
  const c=vehicle?.p??xy(map.getCenter().toArray()),x=Math.floor(c[0]/meta.tileSize),y=Math.floor(c[1]/meta.tileSize);
  const detail=map.getZoom()>=15;
  const heights=buildingHeights?.enabled?buildingHeights:null;
  const sections=heights?.sections;
  const group=detail?x+","+y+"/"+(heights?.version??"tags")+(sections?"/sections":""):"";
  if(group===tileWindow)return;
  tileWindow=group;const revision=++tileRequest;
  if(!detail){data("buildings",empty);data("streets",empty);return;}
  const pending=[],estimates=[],shapes=[];
  const reportError=error=>{el("building-heights-status").textContent=error.message;return [];};
  for(let a=x-1;a<=x+1;a++)for(let b=y-1;b<=y+1;b++){
    const key=a+"_"+b;if(!keys.has(key))continue;
    if(!tiles.has(key))tiles.set(key,json(streetBase+key+".json").catch(e=>{tiles.delete(key);throw e;}));
    pending.push(tiles.get(key));
    const request=heights?.tile(key);
    if(request)estimates.push(request.catch(reportError));
    const shape=sections&&heights.sectionTile(key);
    if(shape)shapes.push(shape.catch(reportError));
  }
  const [loaded,measured,profiled]=await Promise.all([Promise.all(pending),Promise.all(estimates),Promise.all(shapes)]);
  if(revision!==tileRequest)return;
  const buildings=new Map(),roads=new Map(),roofs=new Map(measured.flat().map(row=>[row[0],row])),profiles=new Map(profiled.flat());
  for(const tile of loaded){
    for(const [id,height,basis,ring,detail] of tile.buildings){
      if(buildings.has(id))continue;
      const parts=profiles.get(id),year=heights?.report.year;
      if(parts)buildings.set(id,sectionFeatures(id,detail,parts,year));
      else buildings.set(id,[{...feature({type:"Polygon",coordinates:[ring,...(detail?.holes||[])].map(r=>r.map(lngLat))},
        buildingProperties(height,basis,detail,roofs.get(id),year)),id}]);
    }
    for(const [id,car,pts] of tile.roads)if(!roads.has(id))roads.set(id,feature(line(pts),{car,deck:bridgeDecks?.ways.has(id)??false}));
  }
  data("buildings",collection([...buildings.values()].flat()));data("streets",collection([...roads.values()]));
}

function configureBuildingHeights(streets){
  const panel=el("building-heights-panel"),toggle=el("lidar-heights"),status=el("building-heights-status");
  const sectionToggle=el("lidar-sections");
  return loadBuildingHeights(root+"building-heights/",streets,qs.get("buildingHeights"),json).then(model=>{
    if(!model)return;
    buildingHeights=model;
    const {report,roofSections}=model,source=el("building-heights-source");
    const estimates=Object.values(report.replacements).reduce((sum,n)=>sum+n,0);
    status.textContent=fmt(estimates)+" footprints have a height estimated from "+report.year+" LiDAR."+
      (roofSections?" "+fmt(roofSections.buildings)+" buildings have fitted roof sections.":"");
    source.href=report.source;source.hidden=false;
    const apply=()=>{
      model.enabled=toggle.checked;
      model.sections=!!roofSections&&sectionToggle.checked;
      sectionToggle.disabled=!model.enabled;
      const url=new URL(location.href);
      url.searchParams.set("buildingHeights",model.enabled?model.version:"tags");
      if(roofSections){
        if(model.sections)url.searchParams.delete("roofSections");else url.searchParams.set("roofSections","flat");
      }
      history.replaceState(null,"",url);
      showTiles().catch(error=>message(error.message));
    };
    toggle.checked=model.enabled;toggle.onchange=sectionToggle.onchange=apply;
    el("lidar-sections-label").hidden=!roofSections;sectionToggle.checked=qs.get("roofSections")!=="flat";
    panel.hidden=false;apply();
  }).catch(error=>{
    toggle.disabled=true;panel.hidden=false;status.textContent=error.message;
  });
}
function overview(){
  streetRequest++;
  incomingTrip=null;stopGranvilleFollow();
  follow=false;parkStreet();el("follow").textContent="Follow resident";
  el("region-place").value="";
  const url=new URL(location.href);url.searchParams.delete("place");history.replaceState(null,"",url);
  message("");
  const bounds=regional?(extendedFrame??[[-123.30,49.199],[-122.943,49.386]]):
    [[-123.253,49.193],[-123.013,49.323]];
  map.fitBounds(bounds,{padding:20,bearing:0,pitch:0,duration:0});
  render();
}
const bookmarks={
  downtown:[-123.1209,49.2831,"Downtown"],
  commercial:[-123.0697,49.274,"Grandview-Woodland"],
  ubc:[-123.2502,49.2664,"UBC Vancouver campus"],
  lonsdale:[-123.0804,49.3106,"City of North Vancouver"],
  lynn:[-123.0395,49.3373,"District of North Vancouver"],
  ambleside:[-123.1559,49.3283,"West Vancouver"],
  horseshoe:[-123.2741,49.3739,"West Vancouver"]
};
async function goToPlace(key,keepResident=false){
  const view=bookmarks[key];if(!view||!regional&&key!=="downtown"&&key!=="commercial")return;
  streetRequest++;
  const [lon,lat,name]=view,centre=xy(view),das=new Set(atlas.areas[name].das);
  follow=false;parkStreet();el("follow").textContent="Follow resident";
  el("region-place").value=key;
  map.jumpTo({center:[lon,lat],zoom:16.2,pitch:47,bearing:0});
  const url=new URL(location.href);url.searchParams.set("place",key);history.replaceState(null,"",url);
  const nearby=day.sample.filter(([d])=>das.has(day.das[d])).map(row=>{
    const s=state(day.templates[row[2]],row[3]);return [s.p?distance(centre,s.p):Infinity,row];
  }).sort((a,b)=>a[0]-b[0])[0];
  if(!keepResident&&nearby&&Number.isFinite(nearby[0]))await choose(day.das[nearby[1][0]],nearby[1][1]);
  message(name);
}
function releaseStreetInput(){
  streetInput.accelerator.clear();streetInput.brake.clear();
}
function parkStreet(){
  if(vehicle)parkedStreet={...vehicle,velocity:0};
  vehicle=null;releaseStreetInput();
  streetViewChanged();
  el("resume-street").hidden=!parkedStreet;
  document.querySelector(".street-pad").hidden=true;
  if(map?.getSource("street-player")){
    data("street-player",empty);data("deck-player",empty);
  }
  streetShops?.refresh();
}
function readStreet(){
  el("street-location").textContent=vehicle.street||bridgeDecks?.player(vehicle)?.name||
    ({[WALK]:"Walking",[CAR]:"Driving",[BIKE]:"Cycling"}[vehicle.mode]);
  el("street-speed").textContent=Math.round(vehicle.velocity*3.6)+" km/h";
  el("street-turn").hidden=!vehicle.turn;
  el("street-turn").textContent=vehicle.turn<0?"Left at next turn":"Right at next turn";
}
const groundUnderPlayer=()=>bridgeDecks?.player(vehicle)?.height??terrainAt(vehicle.p);
function paintStreet(seconds){
  streetNeedsPaint=false;
  const eye=eyeLevel(vehicle),deck=bridgeDecks?.player(vehicle);
  eyeGround=eye?(deck?.height??terrainAt(vehicle.p)):0;
  const elevated=!eye&&!vehicle.overhead&&deck;
  elevationMode(eye||!!elevated);
  const camera=playerCamera(vehicle,seconds,map,eyeGround);
  if(elevated)camera.elevation=deck.height;
  streetCameraHeight=camera.elevation;
  map.jumpTo(camera);
  const properties={mode:vehicle.mode,heading:vehicle.heading,elevated:!!elevated};
  data("street-player",eye?empty:point(vehicle.p,properties));
  data("deck-player",elevated?collection(streetBodies([[...vehicle.p,{...properties,scenario:true,
    surfaceOffset:aboveTerrain(vehicle.p,deck.height)}]])):empty);
  readStreet();
  drawGranville();
}
function streetViewChanged(){
  const eye=eyeLevel(vehicle);
  if(eye&&!eyeHandlers){
    eyeHandlers=[map.dragPan,map.dragRotate,map.scrollZoom,map.doubleClickZoom,map.touchZoomRotate,map.touchPitch,map.boxZoom]
      .filter(handler=>handler?.isEnabled());
    for(const handler of eyeHandlers)handler.disable();
    map.setMaxPitch(94);
  }else if(!eye&&eyeHandlers){
    for(const handler of eyeHandlers)handler.enable();
    eyeHandlers=null;
    map.setMaxPitch(82);
  }
  if(!vehicle)elevationMode(false);
  el("map").classList.toggle("street-eye-view",eye);
  if(map?.getSource("street-bodies")){
    for(const id of ["street-bodies","street-road-surface","street-footways"])
      map.setLayoutProperty(id,"visibility",eye?"visible":"none");
    for(const id of ["nearby-walkers","nearby-drivers","residents","streets"])
      map.setLayoutProperty(id,"visibility",eye?"none":"visible");
    data("street-bodies",eye?collection(streetBodies(streetActors)):empty);
  }
  if(map?.getLayer(streetShopLayers[0])){
    map.setLayoutProperty(streetShopLayers[0],"visibility",eye?"none":"visible");
    map.setLayoutProperty(streetShopLayers[1],"visibility",eye?"visible":"none");
  }
  el("street-eye").setAttribute("aria-pressed",String(eye));
  el("street-camera").setAttribute("aria-pressed",String(!!vehicle?.overhead));
  el("street-camera").textContent=vehicle?.overhead?"Street camera":"Overhead";
  hiredDispatchClock?.(t);
}
function resetOrTurnView(yaw){
  if(!eyeLevel(vehicle))return;
  if(yaw)aimPlayer(vehicle,yaw);
  else vehicle.lookYaw=vehicle.lookPitch=0;
  paintStreet(1);
}
function enterStreet(player){
  const leavingIncoming=!!incomingTrip;
  incomingTrip=null;stopGranvilleFollow();follow=false;el("follow").textContent="Follow resident";
  vehicle=player;parkedStreet=null;releaseStreetInput();
  data("deck-follower",empty);
  deckLayer?.setTrail([]);
  el("resume-street").hidden=true;
  document.querySelector(".street-pad").hidden=false;
  el("forward").textContent=player.mode===CAR?"Accelerate":player.mode===BIKE?"Pedal":"Walk";
  streetViewChanged();
  paintStreet(1);
  streetShops?.refresh();
  if(leavingIncoming)render();
  message("Hold W or ↑ to move. A or D queues a turn and S brakes. In Eye level, drag to look around, or press Q and E. C centres the view.");
}
async function street(mode,segment,overhead=false,eye=false,look=[]){
  const request=++streetRequest;
  const seed=vehicle?.p??xy(map.getCenter().toArray()),heading=vehicle?.heading??map.getBearing();
  const graph=await (mode===BIKE?cycleNetwork():network());
  if(request!==streetRequest)return;
  const start=(segment&&graph.resumeEdge(seed,mode,segment))||graph.streetStart(seed,mode,heading);
  if(!start){message("No accessible street near the map centre. Move the map onto land.");return;}
  enterStreet(startPlayer(graph,mode,start.node,start.heading,start,overhead,eye,look));
}
async function visitStorefront(site){
  const request=++streetRequest;
  const graph=await network();
  if(request!==streetRequest||market?.site!==site||!market.active)return;
  const access=streetShops.access(market)?.locate(site,graph,WALK);
  if(!access)throw Error("This address has no close match on a named walking street. Use View storefront for its parcel location.");
  const turn=Math.atan2(site.point[0]-access.p[0],access.p[1]-site.point[1])*180/Math.PI;
  const look=((turn-access.heading+540)%360)-180;
  enterStreet(startPlayer(graph,WALK,access.node,access.heading,access,false,true,[look,0]));
}
function resumeStreet(){
  if(!parkedStreet)return;
  streetRequest++;
  enterStreet(parkedStreet);
}
function leaveStreet(){
  if(!vehicle)return;
  streetRequest++;parkStreet();
  map.jumpTo({center:lngLat(parkedStreet.p),zoom:17.1,pitch:0,bearing:0});message("");
}
function turn(dir){
  if(!vehicle)return;
  vehicle.turn=vehicle.turn===dir*90?0:dir*90;readStreet();
}
function reverseStreet(){
  if(!vehicle)return;
  releaseStreetInput();
  if(turnAround(vehicle)){paintStreet(1);message("Turned around.");}
  else message("Turnaround unavailable on this directed segment.");
}
function toggleStreetCamera(){
  if(!vehicle)return;
  vehicle.overhead=!vehicle.overhead;
  streetViewChanged();
  paintStreet(1);
}
function toggleEyeCamera(){
  if(!vehicle)return;
  vehicle.eye=!eyeLevel(vehicle);
  vehicle.overhead=false;
  streetViewChanged();
  paintStreet(1);
}
function tick(now){
  const seconds=previousFrame?Math.min(.1,(now-previousFrame)/1000):0;
  if(vehicle&&seconds){
    const moving=stepPlayer(vehicle,seconds,streetInput.accelerator.size,streetInput.brake.size);
    if((moving||streetNeedsPaint||Math.abs(Math.sin((vehicle.heading-vehicle.cameraHeading)*Math.PI/360))>.002)&&now-streetPaint>=28){
      paintStreet(Math.min(.1,(now-streetPaint)/1000));streetPaint=now;
    }
  }
  previousFrame=now;
  if(playing && lastTime){
    t=240+(t-240+Math.min(1,(now-lastTime)/1000)*Number(el("speed").value)/60)%1440;
    if(now-lastPaint>220){render();lastPaint=now;}
  }
  if(nearby&&nearby.on!==!!vehicle){
    nearby.setActive(!!vehicle);
    if(vehicle)map.keyboard.disable();else map.keyboard.enable();
    map.setFilter("residents",vehicle?["==",["get","moving"],false]:null);
    if(!vehicle&&new URLSearchParams(location.search).has("street")){
      const url=new URL(location.href);for(const k of ["street","at","edge","camera","look"])url.searchParams.delete(k);history.replaceState(null,"",url);
    }
  }
  if(vehicle&&nearby&&now-nearbyPaint>=220){
    nearbyPaint=now;
    streetShops?.refresh();
    nearby.view(t,vehicle.p,[outbound?.commuteRule()??"city",market?.revision??0,cycleTours?.mode()??"diary",!!hiredRides?.enabled].join("/"),!!outbound&&!jointRun&&outbound.commuteRule()!=="diary");
    const link=new URL(location.href);
    granville?.pin(link);
    if(market?.active&&market.hash)link.searchParams.set("marketRun",market.hash);
    if(bridgeDecks?.player(vehicle))link.searchParams.set("decks",bridgeDecks.version);
    nearby.scenarios?.pin(link.searchParams);
    if(workTransitClock)link.searchParams.set("workTransit",workTransitClock.version);
    else if(workTransit)link.searchParams.set("workTransit","recorded-"+workTransit.version);
    if(personalTransit?.enabled)link.searchParams.set("personalTransit",personalTransit.version);
    el("street-link").href=playerLink(vehicle,link,t);
  }
  lastTime=now;requestAnimationFrame(tick);
}
async function followAt(d,i,start,view={zoom:16.7,pitch:52},bridgeChoice=null){
  streetRequest++;
  play(false);await choose(d,i,false);if(selected?.d!==d||selected.i!==i)return;
  await vehicleAccess?.loadResident(d);
  if(selected?.d!==d||selected.i!==i)return;
  selected.bridgeChoice=bridgeChoice;
  parkStreet();follow=true;
  el("follow").textContent="Stop following";map.jumpTo(view);setTime(start);
  if(!net){await network();render();}
}
async function followRoadResident([da,index,minute,start,duration,from,to],graph){
  if(outboundRoad&&Math.max(from,to)>=outboundRoad.report.basePlaces){
    await followAt(da,index,minute);
    return;
  }
  const a=places[from],b=places[to],route=graph.driveRoute(a,b,duration,start);
  if(!route)throw Error("The resident’s drive no longer fits the published road graph.");
  await followAt(da,index,minute,undefined,{start,duration,from:a,to:b,route,elapsed:true,name:"Free-flow road crossing"});
}
function viewPlace(position,zoom,pitch){
  streetRequest++;
  follow=false;parkStreet();
  el("follow").textContent="Follow resident";map.jumpTo({center:lngLat(position),zoom,pitch});
}
function renderMobility(){
  if(!mobility)return;
  const a=mobility,include=shortWalks&&el("short-walks").checked;
  const extra=include?shortWalks.adultWalks:0;
  const shops=!regional&&outings?.active&&outings.report.cityScope?outings.report:null;
  const shoppingWalks=2*(shops?.attendance??0);
  const loops=recreation?.mode==="bike"&&recreation.active?recreation.totals.added:0;
  const trips=a.main.trips+extra+loops+shoppingWalks;
  el("mobility-rate").textContent=(trips/a.main.people).toFixed(2)+" simulated trips per adult weekday · "+a.survey.rate.toFixed(1)+" in the City survey.";
  const rows=Object.entries({...a.survey.shares,"Other / unspecified":null}).map(([name,observed])=>{
    const changed=outbound?0:cycleTours?.added()??0,local=market?.walkTrips??0;
    const row=document.createElement("tr"),n=(a.main.modes[name]||0)+(jointRun?.activeModeDelta[name]??0)+
      (vehicleAccess?.modeChanges.get(name)??0)+
      (name==="Walking"?extra+local+shoppingWalks:name==="Cycling"?changed+loops:name==="Auto driver"?-changed-local:0);
    for(const cell of [name,(100*n/trips).toFixed(1)+"%",observed===null?"—":observed.toFixed(1)+"%"])row.insertCell().textContent=cell;
    return row;
  });
  el("mobility-modes").replaceChildren(...rows);
  const age45=(a.age45to49.trips+(include?shortWalks.age45Walks:0)+2*(shops?.age45Attendance??0))/a.age45to49.people;
  const age20=(a.age20plus.trips+(include?shortWalks.age20Walks:0)+shoppingWalks)/a.age20plus.people;
  el("mobility-age").textContent="At ages 45–49, the model produces "+age45.toFixed(2)+
    " trips per resident versus "+a.survey.age45to49.toFixed(1)+" observed. The model rate for ages 20+ is "+
    age20.toFixed(2)+". "+fmt(a.unknownPrivateAge)+" private-household residents have masked ages and are excluded.";
}
async function loadShortWalks(pointer,street,baseRoot=root){
  const prefix=regional?"regional-":"",counts=el(prefix+"walk-counts");
  const response=await fetch(jointRun?jointRun.path+"short-walks.json":baseRoot+"short-walks/"+pointer.version+"_"+street+".json");
  if(!response.ok){counts.textContent="Short-walk reconstruction is unavailable for this build.";return;}
  const result=await response.json();
  if(result.day!==pointer.version||result.atlas!==pointer.atlas||result.streets!==street)throw Error("Mismatched short-walk data.");
  shortWalks=result;
  for(const row of result.walks){
    const key=row[0]+"/"+row[1];
    if(!walksByPerson.has(key))walksByPerson.set(key,[]);
    walksByPerson.get(key).push(row);
  }
  const toggle=shortWalkToggle(),button=el(prefix+"walk-example");
  toggle.checked=jointRun?true:regional?qs.get("walks")==="fit":qs.get("walks")!=="diary";toggle.disabled=!!jointRun;
  if(regional)el("regional-walk-controls").hidden=false;
  else counts.textContent=fmt(result.gaps.resolved)+" of "+fmt(Object.values(result.gaps).reduce((a,b)=>a+b,0))+
    " place changes with no diary trip fit a street walk of up to "+result.minutes+" minutes between the assigned places.";
  toggle.onchange=()=>{
    const url=new URL(location.href);
    if(regional&&toggle.checked)url.searchParams.set("walks","fit");
    else if(!regional&&!toggle.checked)url.searchParams.set("walks","diary");
    else url.searchParams.delete("walks");
    history.replaceState(null,"",url);button.disabled=!toggle.checked;market?.evidenceRender?.();renderMobility();render();
  };
  const north=regional?new Set(Object.entries(atlas.areas).filter(([name])=>name.includes("North Vancouver")||name==="West Vancouver")
    .flatMap(([,area])=>area.das)):null;
  const examples=north?result.walks.filter(([d])=>north.has(day.das[d])):result.walks;
  const example=examples.find(([, ,s,n])=>s>=480&&n>=4)||examples[0];
  if(example){
    button.hidden=false;button.disabled=!toggle.checked;
    button.onclick=()=>followAt(day.das[example[0]],example[1],example[2]+Math.floor(example[3]/2)).catch(e=>message(e.message));
  }
  market?.evidenceRender?.();renderMobility();render();
}

async function departureClockEvidence(root,pointer,active){
  const family=root+"departure-clock/";
  const response=await fetch(family+pointer.atlas+"_"+pointer.version+".json");
  if(!response.ok&&!active)return;
  const version=active?.version??(await response.json()).version;
  if(!/^[a-f0-9]{20}$/.test(version))throw Error("Invalid departure timing release.");
  const report=await json(family+version+"/report.json");
  if(report.atlas!==pointer.atlas||report.day!==pointer.version||report.kind!=="spread-departures")
    throw Error("The departure timing comparison and weekday differ.");
  el("spread-departures").hidden=false;
  el("departure-clock-count").textContent=fmt(report.changedTrips)+" trips across "+fmt(report.changedResidents)+
    " residents change minute. "+(active?"The map uses spread departures.":"The map uses the original diary times.");
  const link=el("departure-clock-replay");
  link.textContent=active?"Replay the original diary times":"Replay the spread departures";
  const update=()=>{
    const url=new URL(location.href);
    for(const key of ["clock","scheduled","workTransit","personalTransit","dispatchRun","marketRun","workplaces","commute",
      "crossing","crossingRun","bridgeChoice","cycleTours","grocery","localWalk"])url.searchParams.delete(key);
    if(active)url.searchParams.delete("departureClock");else url.searchParams.set("departureClock",version);
    if(recreation?.mode==="bike"&&recreation.active){
      url.searchParams.delete("recreationRun");
      url.searchParams.set("recreation","on");
    }
    if(url.searchParams.has("hiredRides"))url.searchParams.set("hiredRides","fit");
    if(follow&&!vehicle)url.searchParams.set("follow","1");
    url.searchParams.set("minute",Math.floor(t)); url.hash="spread-departures";
    link.href=url;
  };
  update();
  for(const event of ["pointerdown","focus"])link.addEventListener(event,update);
}

async function init(){
  coverageControl(()=>t);
  const {select:showPanel,show:showInspector,openAnchor}=inspector();
  updateClock=mountClock({
    play:()=>play(!playing),
    seek:minute=>{play(false);setTime(minute);},
    step:direction=>{play(false);setTime(Math.floor(t)+15*direction);}
  });
  updateClock({text:clock(t),minute:Math.floor(t)});
  const inspectResident=(d,i,minute)=>followAt(d,i,minute).then(showInspector);
  let pointer,streetPointer;
  let workPair, workBasis, vehicleLoad;
  const requestedVehicle=qs.get("vehicleRun");
  const baseRoot=root+(regional?"region/":"");
  const replay=!regional&&qs.has("marketRun")?await archivedRun(baseRoot,qs.get("marketRun"),json):null;
  const published=await publishedWeekday(json,replay);
  const requestedJoint=qs.get("jointRun")??replay?.jointRun??(!replay?published?.jointRun:null);
  if(replay?.jointRun&&replay.jointRun!==requestedJoint)
    throw Error("The saved shopping market uses a different combined weekday.");
  const pinnedIncoming=qs.get("incomingTransit")??(published?.jointRun===requestedJoint?published?.incomingTransit:null);
  if(!regional&&requestedJoint){
    jointRun=await jointWeekday(baseRoot,requestedJoint,json);
    coverageParams.jointRun=jointRun.id;
    if(pinnedIncoming)coverageParams.incomingTransit=pinnedIncoming;
    if(householdClock||departureClock)throw Error("The combined weekday has its own published diary clock.");
    vehicleLoad=vehicleRelease(jointRun,requestedVehicle,json).catch(e=>{
      if(requestedVehicle){el("vehicle-access").hidden=false;el("vehicle-access").open=true;el("vehicle-access-status").textContent=e.message;}
      return null;
    });
    attachIncomeComparison(jointRun,json,requestedVehicle?vehicleLoad:null).catch(e=>{el("income-trip-status").textContent=e.message;});
  }
  const marketOutings=replay?.shoppingOutings;
  const spreadMarket=replay?.clockKind==="spread-departures";
  if(jointRun){
    const {atlas,day,streets}=jointRun.versions;
    if((published&&[atlas,day,streets].some((v,i)=>v!==[published.atlas,published.day,published.streets][i]))||
       (replay&&([atlas,day,streets].some((v,i)=>v!==[replay.atlas,replay.day,replay.streets][i])||
          replay.clock||(replay.shoppingOutings&&replay.shoppingOutings!==jointRun.outings)||
          Object.entries(jointRun.workplaces).some(([key,value])=>replay.workplaceRuns?.[key]!==value))))
      throw Error("The requested replay and combined weekday have different source versions.");
    const url=new URL(location.href);
    url.searchParams.set("jointRun",jointRun.id);
    if(pinnedIncoming)url.searchParams.set("incomingTransit",pinnedIncoming);
    history.replaceState(null,"",url);
    pointer={atlas,version:day,workplaceRuns:jointRun.workplaces,commuteRule:jointRun.commuteRule};
    streetPointer={version:streets};censusWorkplaces=true;
    jointOccupancy=await json(jointRun.path+"occupancy.json");
  }else if(replay){
    pointer={atlas:replay.atlas,version:replay.day,workplaceRuns:replay.workplaceRuns};
    streetPointer={version:replay.streets};householdClock=spreadMarket?null:replay.clock;censusWorkplaces=!!replay.workplaceRuns;
    if(spreadMarket)departureClock=replay.clock;
  }else if(published||regional){
    let version=published??await regionalRelease(baseRoot,householdClock,json);
    if(regional&&!householdClock&&qs.has("workplaceRun")){
      const id=qs.get("workplaceRun");
      if(!/^[a-f0-9]{20}$/.test(id))throw Error("Invalid regional workplace release.");
      const pair=await json(baseRoot+"regional-workplaces/"+id+"/report.json");
      const parents=pair.versions;
      const keys=["atlas","day","streets","transit"];
      if(![pair.day,...keys.map(key=>parents?.[key])].every(v=>/^[a-f0-9]{20}$/.test(v))||
        (published&&keys.some(key=>parents[key]!==published[key])))
        throw Error("The workplace calibration uses a different published weekday.");
      workPair={id,...pair};
      workBasis=qs.get("workplaceBasis")==="original"?"original":"census";
      version={...parents,day:workBasis==="census"?pair.day:parents.day};
    }
    pointer={version:version.day,atlas:version.atlas,transit:version.transit};streetPointer={version:version.streets};
  }else [pointer,streetPointer]=await Promise.all([json(root+"cityday/current.json"),json(root+"streets/current.json")]);
  dayBase=baseRoot+"cityday/"+pointer.version+"/";atlasBase=baseRoot+"atlas/"+pointer.atlas+"/";streetBase=baseRoot+"streets/"+streetPointer.version+"/";
  const css=document.createElement("link");css.rel="stylesheet";css.href=streetBase+"maplibre-gl.css";document.head.append(css);
  const library=new Promise((resolve,reject)=>{const js=document.createElement("script");js.src=streetBase+"maplibre-gl.js";js.onload=resolve;js.onerror=()=>reject(Error("Offline map library unavailable"));document.head.append(js);});
  let base,parks;
  const mapBase=workPair?.extendedMap?baseRoot+"cityday/"+workPair.day+"/":atlasBase;
  [day,atlas,places,meta,base,parks]=await Promise.all([json(dayBase+"day.json"),json(atlasBase+"atlas.json"),json(dayBase+"places.json"),
    json(streetBase+"streets.json"),json(mapBase+"basemap.json"),json(root+"parks.geojson"),library]);
  if(!regional)attachDiaryFit(baseRoot,{atlas:pointer.atlas,day:pointer.version,streets:streetPointer.version},day,json,()=>t)
    .catch(error=>{if(day.diaryFit||location.hash==="#diary-fit")message(error.message);});
  if(workPair?.extendedMap){
    const [west,south,east,north]=base.frame;
    extendedFrame=[[west,south],[east,north]];
  }
  if(departureClock&&(householdClock||replay&&!spreadMarket))throw Error("This comparison requires the original weekday as its parent.");
  if(householdClock||departureClock){
    const {loadClock}=await import("../js/vancouver/departures.js");
    clockRun=await (departureClock?loadClock(baseRoot,pointer.atlas,pointer.version,departureClock,json,"departure-clock","spread"):
      loadClock(baseRoot,pointer.atlas,pointer.version,householdClock,json));
    clockRun.applyDay(day);
    const url=new URL(location.href);url.searchParams.set(departureClock?"departureClock":"clock",clockRun.version);
    history.replaceState(null,"",url);
    el("mobility-check").hidden=true;
  }
  const spreadClock=clockRun?.kind==="spread-departures";
  if(departureClock&&!spreadClock)throw Error("The requested run is not a departure timing comparison.");
  if(spreadClock)clockRun.applyDiaries(atlas);
  const vehicleComparison=await vehicleLoad;
  if(vehicleComparison&&requestedVehicle){
    vehicleAccess=await new VehicleAccess(vehicleComparison,baseRoot,day,places,json,()=>{render();nearby?.refreshScenarios();}).init();
    coverageParams.vehicleRun=vehicleAccess.version;
  }
  const workTransitParents={atlas:pointer.atlas,day:pointer.version,streets:streetPointer.version};
  if(!regional&&!jointRun&&!clockRun&&!replay)
    showJointLink(baseRoot,workTransitParents,qs,!!day.diaryFit).catch(e=>message(e.message));
  if(regional&&!clockRun){
    workTransitClock=await loadWorkTransitClock(baseRoot,workTransitParents,qs.get("workTransit"),json);
    workTransitClock?.applyDay(day);
    workTransitClock?.applyDiaries(atlas);
  }
  const scheduledClock=clockRun?.kind==="scheduled-transit";
  if(scheduledClock){
    if(!regional||clockRun.streets!==streetPointer.version)throw Error("This transit commute replay uses a different street network.");
    clockRun.applyDiaries(atlas);
    const url=new URL(location.href);url.searchParams.set("scheduled","1");history.replaceState(null,"",url);
  }
  meta.tiles.forEach(k=>keys.add(k));
  if(censusWorkplaces){
    const {loadWorkers}=await import("../js/vancouver/workplaces.js");
    outbound=await loadWorkers(baseRoot,pointer,day,json);
    if(jointRun&&!qs.has("vehicleRun")){
      const roads=loadOutboundRoadJobs(baseRoot,jointRun,places,json,published?.outboundRoad).catch(error=>{
        if(qs.has("outboundRoad")||published?.outboundRoad)throw error;
        return null;
      });
      const transitJobs=loadOutboundTransit(baseRoot,jointRun,pinnedIncoming,places,json,render,followAt,published?.outboundTransit)
        .catch(error=>{
          if(qs.has("outboundTransit")||published?.outboundTransit)throw error;
          return null;
        });
      [outboundRoad,outboundTransit]=await Promise.all([roads,transitJobs]);
      if(outboundRoad){
        const [context]=await Promise.all([outboundRoad.mapContext(),outboundRoad.loadRoad()]);
        base={...context,roads:{...context.roads,street:base.roads.street}};
      }
    }
    el("outside-now").hidden=false;
    el("walk-counts").textContent="This citywide survey comparison uses the original diary modes. The outbound workplace panel compares modes for direct commutes.";
    outbound.show(async(d,i,start,track)=>{
      if(track)return followAt(d,i,start);
      play(false);overview();await choose(d,i);setTime(start);
    },()=>{market?.selectRun();refreshCycleCounts?.();render();});
  }
  cycleVersion=replay?.cycling??outbound?.report.neighbourhoodFit?.cycling;
  if(!cycleVersion){
    const response=await fetch(baseRoot+"cycling/"+streetPointer.version+".json");
    if(response.ok)cycleVersion=(await response.json()).version;
  }
  if(cycleVersion){
    cycleUrl=baseRoot+"cycling/"+cycleVersion+"/network.json";el("bike").hidden=false;
  }
  const shoppingClockRoot=baseRoot+"shopping-clock/";
  if(qs.has("shoppingClock")){
    if(!jointRun||!cycleVersion)throw Error("The bicycle shopping clock requires a combined weekday and cycle network.");
    const {loadShoppingClock}=await import("./shopping-clock.js");
    shoppingClock=await loadShoppingClock(shoppingClockRoot,jointRun,cycleVersion,places,json,qs.get("shoppingClock"));
    coverageParams.shoppingClock=shoppingClock.version;
  }
  let tourVersion=replay?.tours;
  const tourRoot=baseRoot+"cycle-tours/";
  if(!regional&&!clockRun&&!replay&&cycleVersion){
    const response=await fetch(tourRoot+[pointer.atlas,pointer.version,streetPointer.version,cycleVersion].join("_")+".json");
    if(response.ok)tourVersion=(await response.json()).version;
  }
  const marketTourVersion=outbound?null:tourVersion;
  if(!regional&&cycleUrl){
    const requested=qs.get("bikeRoutes");
    if(requested&&!["bikeways","hills"].includes(requested)&&!/^[a-f0-9]{20}$/.test(requested))throw Error("Unknown bicycle route profile.");
    const available=await Promise.all(["","-hills"].map(async suffix=>{
      const response=await fetch(baseRoot+"bikeways/"+cycleVersion+suffix+".json");
      return response.ok?(await response.json()).version:null;
    }));
    const [current,hills]=available, choices={bikeways:current,hills};
    if(requested){
      bikewayVersion=Object.hasOwn(choices,requested)?choices[requested]:requested;
      if(!bikewayVersion)throw Error("The bikeway profile is unavailable for this graph.");
      bikeways=await json(baseRoot+"bikeways/"+bikewayVersion+"/profile.json");
      if(bikeways.cycling!==cycleVersion)throw Error("The bikeways and cycling graph have different releases.");
      const url=new URL(location.href);url.searchParams.set("bikeRoutes",bikewayVersion);history.replaceState(null,"",url);
    }
    if(current||bikeways){
      const choice=el("cycle-routing");
      choice.parentElement.hidden=false;
      choice.querySelector('[value="hills"]').hidden=!(hills||bikeways?.parentBikeways);
      choice.value=bikeways?.parentBikeways?"hills":bikeways?"bikeways":"shortest";
      choice.onchange=()=>{
        const url=new URL(vehicle&&el("street-link").href?el("street-link").href:location.href);
        if(choices[choice.value])url.searchParams.set("bikeRoutes",choices[choice.value]);
        else url.searchParams.delete("bikeRoutes");
        url.searchParams.set("cycleCheck",el("cycle-site").value||"arbutus");
        if(follow&&!vehicle)url.searchParams.set("follow","1");else url.searchParams.delete("follow");
        url.searchParams.set("minute",String(t));
        if(selected){url.searchParams.set("da",selected.d);url.searchParams.set("person",String(selected.i+1));}
        location.assign(url);
      };
    }
  }
  const colors=overviewColors();
  map=createMap(window.maplibregl.Map,window.maplibregl.NavigationControl,{container:"map",maxPitch:82,center:[-123.114,49.262],zoom:11,
    style:{version:8,sources:{},sky:{"sky-color":"#7c9eaf","horizon-color":"#ccd4cd","sky-horizon-blend":.45},
      layers:[{id:"outside",type:"background",paint:{"background-color":colors.land}}]},
    attributionControl:false,canvasContextAttributes:{antialias:true}});
  el("camera").onclick=()=>map.easeTo({pitch:map.getPitch()>1?0:45});
  map.on("pitchend",()=>el("camera").setAttribute("aria-pressed",String(map.getPitch()>1)));
  map.addControl(new window.maplibregl.AttributionControl({compact:true,customAttribution:'Statistics Canada · City of Vancouver · '+(regional?'UBC Campus &amp; Community Planning · ':'')+'<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a> · <a href="https://lidar.gov.bc.ca/">LidarBC, Province of British Columbia</a>'}));
  await new Promise(resolve=>map.once("load",resolve));
  try{bridgeDecks=await loadBridgeDecks(root+"bridge-decks/",json,qs.get("decks"));}
  catch(error){message(error.message);}
  const [w,s,e,n]=base.frame;
  source("water",feature({type:"Polygon",coordinates:[[[w,s],[e,s],[e,n],[w,n],[w,s]]]}));
  layer("water","water","fill",{"fill-color":colors.water});
  source("land",feature(base.land));layer("land","land","fill",{"fill-color":colors.land});
  source("parks",parks);layer("parks","parks","fill",{"fill-color":colors.park});
  const streets=Object.entries(base.roads).flatMap(([kind,lines])=>lines.map(coordinates=>{
    const deck=kind==="bridge"&&!!bridgeDecks?.sections(coordinates.map(p=>xy(p).map(Math.round))).deck.length;
    return feature({type:"LineString",coordinates},{kind,deck});
  }));
  source("overview",collection(streets));layer("base-roads","overview","line",{"line-color":["match",["get","kind"],"bridge",colors.bridge,colors.road],"line-opacity":.47,"line-width":["match",["get","kind"],"street",.5,1.3]});
  source("streets");
  map.addLayer({id:"street-road-surface",source:"streets",type:"line",filter:["all",["==",["get","car"],1],["!=",["get","deck"],true]],
    layout:{visibility:"none","line-cap":"round","line-join":"round"},paint:{"line-color":"#2b3a42",
      "line-width":["interpolate",["exponential",2],["zoom"],16,2.7,22,173]}});
  map.addLayer({id:"street-footways",source:"streets",type:"line",filter:["all",["!=",["get","car"],1],["!=",["get","deck"],true]],
    layout:{visibility:"none","line-cap":"round","line-join":"round"},paint:{"line-color":"#54665a",
      "line-width":["interpolate",["exponential",2],["zoom"],16,.5,22,32]}});
  layer("streets","streets","line",{"line-color":["case",["==",["get","car"],1],"#a4a28f","#779281"],"line-width":["interpolate",["linear"],["zoom"],15,1.2,19,9]});
  if(bikeways){
    const toggle=el("cycle-network-map");
    toggle.parentElement.hidden=false;
    source("bikeways");layer("bikeways","bikeways","line",{"line-color":"#68c5bf","line-opacity":.8,
      "line-width":["interpolate",["linear"],["zoom"],10,1.3,17,4]});
    let drawn=false;
    toggle.onchange=async()=>{
      map.setLayoutProperty("bikeways","visibility",toggle.checked?"visible":"none");
      if(drawn||!toggle.checked)return;
      try{
        const graph=await cycleNetwork(),n=graph.nodes.length;
        const lines=bikeways.arcs.filter(([a,b])=>a<b||!graph.bikeways.has(b*n+a))
          .map(([a,b])=>[lngLat(graph.nodes[a]),lngLat(graph.nodes[b])]);
        data("bikeways",feature({type:"MultiLineString",coordinates:lines}));drawn=true;
      }catch(e){toggle.checked=false;message(e.message);}
    };
  }
  source("buildings");layer("buildings","buildings","fill-extrusion",{"fill-extrusion-color":["match",["get","basis"],"height","#b9b9a9","lidar","#b2b9af","levels","#a9b8b1","#909b94"],"fill-extrusion-height":["get","height"],"fill-extrusion-opacity":.94});
  if(bridgeDecks){
    try{
      const layer=bridgeDeckLayer(bridgeDecks,window.maplibregl,regional);
      map.addLayer(layer);deckLayer=layer;
    }catch(error){bridgeDecks=null;message(error.message);}
  }
  source("route");layer("route","route","line",{"line-color":"#f5c96c","line-width":3,"line-opacity":["case",["get","routed"],.95,.45]});
  const modeColor=["case",["get","hired"],"#cbb5ff",["match",["get","mode"],1,"#92e0bc",2,"#ffce78",BIKE,"#f6abfa",8,"#a7caff","#79a898"]];
  source("travel-trails");layer("travel-trails","travel-trails","line",{"line-color":modeColor,"line-width":1.3,"line-opacity":.62});
  source("residents");layer("residents","residents","circle",{"circle-color":modeColor,"circle-radius":["interpolate",["linear"],["zoom"],10,1.1,18,4],"circle-opacity":.82});
  const hasHighwayTimes=bridgeMetric==="highway1";
  const trafficRequest=qs.get("roadTraffic");
  const traffic=await loadCorridorTimes(baseRoot,streetPointer.version,trafficRequest,json).catch(error=>{
    if(trafficRequest)throw error;
    return null;
  });
  const driveTract=(jointRun?.workplaces??replay?.workplaceRuns)?.["tract-workplaces"];
  if(driveTract)workplaceDriveEvidence(baseRoot,driveTract,{atlas:pointer.atlas,day:pointer.version,streets:streetPointer.version},json)
    .then(()=>{if(location.hash==="#workplace-driving")openAnchor();})
    .catch(error=>{if(location.hash==="#workplace-driving")message(error.message);});
  bridgeDriveProfileUrl=baseRoot+"drive-profile/"+streetPointer.version+(hasHighwayTimes?"_highway1":"")+".json";
  const driveProfileUrl=traffic?.active?traffic.driving:bridgeDriveProfileUrl;
  const hourlyDriving=hasHighwayTimes||!!traffic?.active;
  overviewRoutes=new WeekdayRoutes({network:streetBase+"network.json",cycling:cycleUrl,bikeways,driving:driveProfileUrl,hourlyDriving,
    affected:traffic?.active&&traffic.report.affected?affectedSegments(traffic.report.affected):null,
    baselineDigest:traffic?.report.baselineDigest,
    cache:baseRoot+"overview-routes/"+[pointer.atlas,pointer.version,streetPointer.version].join("_")+".json"},render);
  if(traffic){
    source("observed-road");layer("observed-road","observed-road","line",{"line-color":"#fdab70","line-width":4,"line-opacity":.72});
    roadTrafficClock=corridorEvidence(traffic,qs.get("roadSection"),site=>{
      const coordinates=site.directions.map(direction=>direction.line);
      data("observed-road",feature({type:"MultiLineString",coordinates}));
      const bounds=new window.maplibregl.LngLatBounds();
      for(const path of coordinates)for(const position of path)bounds.extend(position);
      streetRequest++;follow=false;parkStreet();
      el("follow").textContent="Follow resident";
      map.fitBounds(bounds,{padding:85,maxZoom:16.3,pitch:0,bearing:0,duration:0});
    },()=>t,()=>{
      const url=new URL(vehicle&&el("street-link").href?el("street-link").href:location.href);
      url.searchParams.set("inspector","evidence");
      url.searchParams.set("minute",String(Math.floor(t)));
      if(selected){url.searchParams.set("da",selected.d);url.searchParams.set("person",String(selected.i+1));}
      if(follow&&!vehicle)url.searchParams.set("follow","1");else url.searchParams.delete("follow");
      url.hash="road-traffic";
      return url;
    });
  }
  source("shop-walkers");layer("shop-walkers","shop-walkers","circle",{"circle-color":"#63cfff","circle-radius":["interpolate",["linear"],["zoom"],10,3,18,6],"circle-stroke-color":"#17374c","circle-stroke-width":1.5});
  source("selected");layer("selected","selected","circle",{"circle-color":"#ff9b4c","circle-radius":6,"circle-stroke-color":"#fff3dc","circle-stroke-width":2});
  map.setFilter("selected",["!=",["get","elevated"],true]);
  const bodyPaint={"fill-extrusion-color":["get","color"],"fill-extrusion-base":["get","base"],"fill-extrusion-height":["get","height"]};
  source("deck-follower");layer("deck-follower","deck-follower","fill-extrusion",bodyPaint);
  if(regional){
    source("outing-vehicle");layer("outing-vehicle","outing-vehicle","circle",
      {"circle-color":"#2c94d9","circle-radius":5,"circle-stroke-color":"white","circle-stroke-width":1.5});
  }
  source("nearby-walkers");
  map.addLayer({id:"nearby-walkers",source:"nearby-walkers",type:"circle",paint:{
    "circle-color":["case",["==",["get","mode"],BIKE],"#f6abfa","#b6e5cc"],"circle-radius":["case",["==",["get","mode"],BIKE],5,4],
    "circle-stroke-color":["case",["boolean",["get","scenario"],false],"#d4f3ff","#173c31"],
    "circle-stroke-width":1.5}},"shop-walkers");
  map.addImage("local-car",playerSprite(CAR,false));
  map.addImage("scenario-car",playerSprite(CAR,"scenario"));
  for(const service of ["taxi","ridehail"])map.addImage(service,playerSprite(CAR,service));
  for(const mode of [WALK,CAR,BIKE])map.addImage("player-"+mode,playerSprite(mode,true));
  source("nearby-drivers");source("street-player");
  const icon={"icon-rotate":["get","heading"],"icon-rotation-alignment":"map","icon-allow-overlap":true,
    "icon-ignore-placement":true};
  map.addLayer({id:"nearby-drivers",source:"nearby-drivers",type:"symbol",
    layout:{...icon,"icon-image":["match",["get","service"],"taxi","taxi","ridehail","ridehail",
      ["case",["boolean",["get","scenario"],false],"scenario-car","local-car"]],"icon-size":1.25}});
  source("street-bodies");
  map.addLayer({id:"street-bodies",source:"street-bodies",type:"fill-extrusion",layout:{visibility:"none"},
    paint:bodyPaint});
  source("granville-guests");layer("granville-guests","granville-guests","circle",{
    "circle-radius":4,"circle-color":"#83e5d7","circle-stroke-color":"#243849","circle-stroke-width":1});
  source("granville-bodies");layer("granville-bodies","granville-bodies","fill-extrusion",bodyPaint);
  source("deck-player");layer("deck-player","deck-player","fill-extrusion",bodyPaint);
  map.addLayer({id:"street-player",source:"street-player",type:"symbol",
    filter:["!=",["get","elevated"],true],layout:{...icon,"icon-image":["concat","player-",["to-string",["get","mode"]]],"icon-size":1.8}});
  const streetScenarios=new StreetScenarios({root:baseRoot+"street-scenarios/",
    versions:{atlas:pointer.atlas,day:pointer.version,streets:streetPointer.version},day,json,
    layers:()=>({recreation,schools:schools?.active&&!schools.differentLayers?schools:null,
      attendance:attendance?.enabled?attendance:null,outings:outings?.active?outings:null,
      lunch:lunchWalks?.active?lunchWalks:null,
      outingShops:market?.catalog?.shoppingDemand?market.outingPlaces:undefined,
      easternOutings:easternOutings?.active?easternOutings:null,voting:voting?.active?voting:null,workTransit,
      personalTransit:personalTransit?.enabled?personalTransit:null,
      cityTransit:cityRiders?.departures?cityRiders:null,vehicleAccess,
      shortWalks:shortWalks&&shortWalkToggle().checked?shortWalks:null}),
    graph:()=>{
      if(!net&&!netPromise)network().then(()=>nearby.refreshScenarios()).catch(error=>message(error.message));
      return net;
    },refresh:()=>nearby?.refreshScenarios()});
  nearby=new NearbyWalks({root:baseRoot+"street-walks/",versions:{atlas:pointer.atlas,day:pointer.version,clock:scheduledClock?null:clockRun?.version},
    network:streetBase+"network.json",cycling:cycleUrl,bikeways,driving:driveProfileUrl,day,places,json,clock,follow:inspectResident,
    scenarios:streetScenarios,groceryWalks:()=>market?.active?market.walks:null,
    extraWalkers:hour=>market?.walkHours?.[hour],
    extraHired:hour=>hiredRides?.streetRows(hour,(d,i)=>market?.slots(d,i)),
    extraCyclists:hour=>[...(cycleTours?.rows(hour)?.map(row=>{
      const ends=market?.cycleLeg(row[0],row[1],row[2]);return ends?[...row.slice(0,4),...ends,row[6],true]:row;
    })??[]),...(shoppingClock?.rows(hour)??[])],
    resolve:(d,i,tpl,part,from,to,commuteOnly)=>{
      if(shoppingClock?.replaces(d,i,part[0]))return null;
      if(voting?.replacesLeg(d,i,part[0]))return null;
      if(vehicleAccess?.hasTrip(d,i,part[0]))return null;
      if(cityRiders?.hasTrip(d,i,part[0]))return null;
      if(part[2]==="car-driver"&&cycleTours?.riding(d,i,part[0]))return null;
      const ends=market?.cycleLeg(d,i,part[0]);
      if(part[2]==="car-driver"&&market?.walkLegs?.has(d+"/"+i+"/"+part[0]))return null;
      return ends?[...ends,bicycleMetresPerMinute,BIKE,true]:activeStreetLeg(outbound?.state(d,i,tpl,part),part,from,to,commuteOnly,
        outbound?.report.neighbourhoodFit?.activeSpeeds,market?.slots(d,i),market?.payload?.speed);
    },
    draw:(dots,minute)=>{
      const walking=[],driving=[];
      streetActors=[];
      for(const [d,i,x,y,,mode,heading,tag,count,segment,service] of dots){
        if((selected?.daIndex===d&&selected.i===i)||(dispatchResident?.[0]===d&&dispatchResident[1]===i)||
           shopWalkers.has(d+"/"+i))continue;
        const features=mode===CAR?driving:walking;
        const scenario=isScenarioTrip(tag);
        const properties={d,i,minute,mode,tag:tag??"",count:count??1,scenario,...(mode===CAR?{heading,service:service??""}:{})};
        const deck=bridgeDecks?.surface([x,y],segment);
        features.push(point([x,y],properties));
        streetActors.push([x,y,deck?{...properties,surfaceOffset:aboveTerrain([x,y],deck.height)}:properties]);
      }
      data("nearby-walkers",collection(walking));data("nearby-drivers",collection(driving));
      if(eyeLevel(vehicle))data("street-bodies",collection(streetBodies(streetActors)));
    }});
  const requestedHire=qs.get("hiredRides");
  let hire;
  if((!clockRun||spreadClock)&&!workTransitClock&&!outbound){
    const hireParents=spreadClock?{...workTransitParents,clock:clockRun.version}:workTransitParents;
    hire=await loadHiredRides(baseRoot,hireParents,requestedHire,json).catch(error=>{
      if(requestedHire)throw error;
      return null;
    });
    if(hire)hiredRides=new HiredRides(hire.report,places,hire.enabled);
  }else if(requestedHire){
    message("Hired-ride assignments use the original diary clock and endpoints.");
  }
  source("vacancies");layer("vacancies","vacancies","circle",{"circle-color":"#d5b0df","circle-radius":3.5,"circle-stroke-width":1,"circle-stroke-color":"#463744"});
  source("opening");layer("opening","opening","circle",{"circle-color":"#eee1a6","circle-radius":9,"circle-opacity":.25,"circle-stroke-width":2,"circle-stroke-color":"#ffe88d"});
  source(streetShopLayers[0]);layer(streetShopLayers[0],streetShopLayers[0],"circle",{
    "circle-color":["match",["get","state"],"open","#80d9ae","selected","#ffe49b","#d8bbec"],
    "circle-radius":5,"circle-stroke-color":"#25313d","circle-stroke-width":1.5});
  source(streetShopLayers[1]);layer(streetShopLayers[1],streetShopLayers[1],"fill-extrusion",bodyPaint);
  streetShops=new StorefrontStreet({player:()=>vehicle,market:()=>market,reveal:()=>showPanel("scenarios",{remember:true}),
    draw:rows=>{
      const unique=new Map();
      for(const row of rows){
        const key=row.access.p.join("/");
        if(!unique.has(key)||row.site.id===market?.site?.id)unique.set(key,row);
      }
      const marks=[...unique.values()];
      data(streetShopLayers[0],collection(marks.map(({site,access,state})=>point(access.p,{id:site.id,state}))));
      data(streetShopLayers[1],collection(marks.flatMap(row=>storefrontSign(row,row.state))));
    }});
  let mountJointEvidence;
  if(!regional&&!clockRun){
    source("count-site");layer("count-site","count-site","line",{"line-color":"#83d9ff","line-width":2});
    const markSite=(center,radius,focus)=>{
      if(!center){data("count-site",empty);return;}
      const ring=Array.from({length:65},(_,i)=>{
        const angle=i*Math.PI/32;
        return [center[0]+radius*Math.cos(angle),center[1]+radius*Math.sin(angle)];
      });
      data("count-site",collection([feature(line(ring))]));
      if(focus)viewPlace(center,16.5,0);
    };
    if(jointRun){
      const fit=day.diaryFit;
      let referenceRun=qs.get("dayRun");
      if(!referenceRun&&fit){
        const pair=await json(baseRoot+"diary-fit/"+fit.baselineAtlas+"_"+fit.baselineDay+".json");
        referenceRun=fit.kind==="income-and-home-zone"?pair.zoneRun:pair.fittedRun;
        if(!/^[a-f0-9]{64}$/.test(referenceRun))
          throw Error("The fitted weekday reference is unavailable.");
      }
      mountJointEvidence=()=>attachJointEvidence(jointRun,json,followAt,markSite,()=>cityRiders.followTransfer(),fit?referenceRun:null,pinnedIncoming);
      showVehicleAccess(vehicleComparison,vehicleAccess,day,followAt);
    }
    else import("../js/vancouver/pedestrians.js").then(evidence=>evidence.init(
      root+"pedestrians/",pointer,streetPointer.version,outbound?.marketParent,json,markSite)).catch(error=>{
      if(qs.has("crossing")){el("pedestrian-check").hidden=false;el("pedestrian-check").open=true;}
      el("pedestrian-status").textContent=error.message;
    });
  }
  const spreadCatalogue=spreadClock&&!regional&&!spreadMarket?
    await fetch(baseRoot+"market/"+clockRun.version+"_"+streetPointer.version+".json",{method:"HEAD"})
      .then(response=>response.ok).catch(()=>false):false;
  if(spreadClock&&!spreadMarket&&!spreadCatalogue)el("market").hidden=true;
  let demandPairRequest;
  const loadDemandPair=()=>demandPairRequest??=shoppingDemandPair(baseRoot,workTransitParents,jointRun);
  if(!clockRun&&(jointRun||regional||(!outbound&&(!replay||marketOutings)))){
    if(!regional)el("outing-heading").textContent="Add walks to shops";
    const refreshOutings=()=>{if(!regional)renderMobility();render();};
    const loadOutings=async()=>{
      const view=await import("./discretionary-outings.js");
      const option=await view.attachOutings(baseRoot+"discretionary-outings/",workTransitParents,day,places,json,
        refreshOutings,followAt,cycleVersion,network,{pinned:jointRun?.outings??marketOutings,shopFor:(d,i)=>market?.outingPlace(d,i)});
      if(!option)return;
      const {panel,load,activate}=option;
      let pending;
      const open=()=>pending??=load().then(async loaded=>{
        outings=loaded;
        if(activate)await outings.enable(true);
        if(!regional&&!marketOutings)loadDemandPair().then(pair=>{
          if(pair?.outings!==loaded.version)return;
          const url=new URL("cityday.html",location.href);
          url.searchParams.set("marketRun",pair.market);
          url.searchParams.set("shop","baseline");
          url.hash="market";
          el("outing-market-link").href=url;
          el("outing-market").hidden=false;
        }).catch(()=>{});
      }).catch(e=>{pending=null;throw e;});
      if(activate||panel.open){panel.open=true;await open();}
      else panel.ontoggle=()=>{if(panel.open)open().catch(e=>{el("outing-status").textContent=e.message;});};
    };
    if(marketOutings||jointRun)await loadOutings();
    else loadOutings().catch(e=>{el("discretionary-outings").hidden=false;el("outing-status").textContent=e.message;});
  }
  if(!regional&&(!spreadClock||spreadMarket||spreadCatalogue))market=new GroceryMarket({
    time:()=>t,
    walkingGraph:()=>net,
    reveal:()=>showPanel("scenarios",{remember:true}),
    inferredWalks:()=>!!shortWalks&&el("short-walks").checked,
    loadShoppingEvidence:()=>json(root+"market/evidence-"+marketTourVersion+".json"),
    loadPurchaseChoices:local=>json(root+"market/choices-"+marketTourVersion+"_"+streetPointer.version+(local?"_walk":"")+".json"),
    loadSiteSensitivity:published?.jointRun?async site=>{
      const url=root+"market/sensitivity/"+site+"-"+published.release+".json";
      const response=await fetch(url);
      if(response.status===404)return null;
      if(!response.ok)throw Error("Storefront comparison unavailable.");
      const report=await response.json();
      if(report.schema!==1||report.release!==published.release||report.jointRun!==published.jointRun||report.site.id!==site)
        throw Error("Storefront comparison belongs to a different weekday.");
      return {report,url};
    }:null,
    loadDemandPair,shoppingOutings:marketOutings,fixedCommute:!!jointRun,
    clock:clockRun?.version,
    workplaces:outbound?.marketParent,tours:marketTourVersion,cycling:cycleVersion,rule:()=>outbound?.commuteRule()??cycleTours?.mode()??"diary",
    loadHouseholds:()=>json(root+"household-market/"+pointer.atlas+"_"+pointer.version+"_"+streetPointer.version+".json"),
    housingFolder:root+"household-market/housing/",json,
    load:()=>marketCatalogue(replay?replay.path+"market.json":root+"market/"+(marketTourVersion||clockRun?.version||outbound?.marketParent||pointer.version)+"_"+streetPointer.version+
      (marketTourVersion&&qs.get("grocery")==="bc2010"?"_bc2010":"")+(marketTourVersion&&qs.has("localWalk")?"_walk":"")+".json",replay?.market,
      marketTourVersion&&!replay&&!qs.has("localWalk")&&qs.get("grocery")!=="bc2010"?root+"market/"+pointer.version+"_"+streetPointer.version+".json":null),
    archive:hash=>archivedRun(root,hash,json),places,day,neighbourhoods:atlas.areas,
    versions:{day:pointer.version,atlas:pointer.atlas,streets:streetPointer.version},refresh:()=>{renderMobility();render();},
    showSites:(sites,site,opened=[])=>{
      if(!site&&!opened.length)data("shop-walkers",empty);
      data("vacancies",collection(sites.map(s=>point(s.point,{id:s.id}))));
      const marked=site?[...opened.filter(s=>s.id!==site.id),site]:opened;
      data("opening",collection(marked.map(s=>point(s.point,{id:s.id}))));
    },
    locate:position=>viewPlace(position,17.5,53),
    visit:visitStorefront,
    follow:followAt
  });
  overview();
  attachTerrain(map,el("terrain"),root+"terrain/",json).catch(()=>{
    if(qs.get("terrain")==="on")message("Elevation tiles are unavailable for this build.");
  });
  if(regional){
    if(scheduledClock){
      transit=new RegionalTransit(map,json,()=>t,clockRun.transit,null,"Vancouver, UBC and the North Shore");
      const [report,rides]=await Promise.all([json(clockRun.path+"report.json"),json(clockRun.path+"rides.json"),transit.init()]);
      if(report.atlas!==pointer.atlas||report.day!==pointer.version||report.transit!==clockRun.transit||report.streets!==streetPointer.version)
        throw Error("The timed transit trips use different simulation inputs.");
      transitCommutes=new TransitCommutes(report,rides,transit,places,render,
        (d,i,minute)=>followAt(d,i,minute,{zoom:14.8,pitch:0}),clock);
    }else if(!clockRun||spreadClock){
      transit=new RegionalTransit(map,json,()=>t,workPair?.timetable??pointer.transit);
      if(workPair&&!spreadClock)attachIncomingTransit(baseRoot,{...workTransitParents,transit:workPair.timetable},
        transit,json,places,render,(example,config)=>followIncoming(baseRoot,example,config)).catch(e=>message(e.message));
      if(!spreadClock)attachWorkTransit(baseRoot,workTransitParents,json,places,network,render,followAt,workTransitClock).then(async rides=>{
        if(!rides)return;
        workTransit=rides;
        if(selected)await rides.loadResident(selected.d);
        render();
        attachPersonalTransit(baseRoot,workTransitParents,rides,json,places,network,render,followAt).then(async journeys=>{
          if(!journeys)return;
          personalTransit=journeys;
          if(selected)await journeys.loadResident(selected.d);
          render();
        }).catch(e=>{
          el("personal-transit").hidden=false;el("personal-transit-status").textContent=e.message;
        });
      }).catch(e=>{
        el("work-transit").hidden=false;el("work-transit-status").textContent=e.message;
      });
      commuteClockLink(baseRoot,pointer.atlas,pointer.version).then(href=>{
        if(!href)return;
        const panel=el("transit-commutes"), link=el("transit-commutes-link"), evidence=el("bridge-schedule-transit-clock");
        panel.hidden=false;
        for(const anchor of [link,evidence])anchor.href=href;
        evidence.hidden=false;
        link.textContent="Replay commutes timed to transit";
      }).catch(e=>{el("transit-commutes-status").textContent=e.message;});
    }
    el("overview").textContent="Regional view";
    el("city-name").textContent="Vancouver, UBC & North Shore";
    el("market").hidden=true;
    el("mobility-check").hidden=true;
  }
  if(!regional)el("regional-places").remove();
  el("region-place").hidden=false;
  el("region-place").onchange=()=>goToPlace(el("region-place").value).catch(e=>message(e.message));
  if(!regional&&(!clockRun||spreadClock)){
    const workplaces=el("workplaces");
    workplaces.value=outbound?"census":"city";
    workplaces.disabled=!!jointRun;
    workplaces.onchange=()=>{
      const url=new URL(location.href);
      url.searchParams.delete("marketRun");
      if(workplaces.value==="census")url.searchParams.set("workplaces","census");
      else {url.searchParams.delete("workplaces");url.searchParams.delete("commute");}
      url.searchParams.set("downtown",el("downtown-window").value);location.assign(url);
    };
    let released;
    const riderRoot=baseRoot+"transit-riders/",pinned=qs.get("riderRun")||qs.get("transitWalks");
    const release=()=>released??=(jointRun?Promise.resolve({riders:jointRun.riders,transit:jointRun.transit}):
      /^[a-f0-9]{20}$/.test(pinned)?
      json(riderRoot+pinned+"/riders.json").then(({versions,transfers,capacityComparison})=>{
        if(versions.day!==pointer.version||versions.atlas!==pointer.atlas||versions.streets!==streetPointer.version)
          throw Error("The linked rider uses a different population or street network.");
        return {riders:pinned,transit:versions.transit,fittedRiders:!!day.diaryFit&&!!(transfers?.sourceRelease||capacityComparison?.sourceRelease)};
      }):json(riderRoot+pointer.atlas+"_"+pointer.version+"_"+streetPointer.version+".json"))
      .catch(e=>{released=null;throw e;});
    const fittedRiders=day.diaryFit&&!outbound&&/^[a-f0-9]{20}$/.test(pinned)&&
      (await release()).fittedRiders;
    if(fittedRiders)coverageParams.riderRun=pinned;
    const incoming=new IncomingWorkers(baseRoot,pointer,json,places,atlas.ages,()=>t,position=>viewPlace(position,17,45),day.areas,jointRun?.commuters);
    if(!spreadClock)downtown=new DowntownTravel(day.areas,async()=>vehicleAccess?vehicleAccess.downtown():
      json(baseRoot+"transit-riders/"+(await release()).riders+"/downtown.json"),()=>t,incoming,outbound,!!jointRun?.transfers,
      jointRun?.transfers&&!vehicleAccess?()=>loadMunicipalIncoming(baseRoot,jointRun,json,places,render,
        (example,config)=>followIncoming(baseRoot,example,config),pinnedIncoming,followRoadResident,outboundRoad):null,outboundTransit);
    if(downtown&&published?.outboundRoad&&published.outboundTransit)attachDowntownAudit(baseRoot,published.release,openAnchor);
    transit=new RegionalTransit(map,json,()=>t,null,release);
    if(!outbound||jointRun)cityRiders=new CityRiders(transit,json,release,
      jointRun?{...workTransitParents,workplaces:jointRun.workplaces["tract-workplaces"]}:workTransitParents,
      places,render,followAt,day.das,!!jointRun||fittedRiders);
    if(jointRun||fittedRiders){
      await transit.init();
      await cityRiders.init();
      if(jointRun)el("zone-model").disabled=true;
    }
  }
  const refinementFor=async pair=>{
    const key=[pointer.atlas,pair.day,streetPointer.version].join("_");
    const reply=await fetch(baseRoot+"regional-workplaces/"+key+".json");
    return reply.ok?(await reply.json()).version:null;
  };
  if(regional&&!clockRun){
    source("bridge-queue");layer("bridge-queue","bridge-queue","circle",{
      "circle-color":"#ecac4b","circle-opacity":.78,
      "circle-radius":["interpolate",["linear"],["get","waiting"],1,7,100,17,500,28],
      "circle-stroke-color":"#fff1be","circle-stroke-width":1.5});
  }
  if(!clockRun)bridgeClock=attachBridgeTraffic({
    root:baseRoot+"bridge-traffic/",versions:{day:pointer.version,atlas:pointer.atlas,streets:streetPointer.version},regional,json,
    time:()=>t,
    timetable:regional?workPair?.timetable:null,
    activeLayers:()=>({"discretionary-outings":outings?.active?outings.version:null,
      "eastern-outings":easternOutings?.active?easternOutings.version:null,
      "school-escorts":schools?.active&&!schools.differentLayers?schools.version:null,
      "weekday-attendance":attendance?.enabled?attendance.version:null}),
    followLayer:([da,i,minute])=>followAt(da,i,minute).catch(e=>message(e.message)),
    followChoice:(leg,route,name)=>followAt(leg.da,leg.person,route.minute,undefined,
      {start:leg.start,duration:leg.duration,route,name}).catch(e=>message(e.message)),
    showBus:(route,minute,point)=>{
      play(false);viewPlace(point,16.7,38);setTime(minute);
      el("transit-panel").open=true;
      transit.init().then(()=>transit.select(route)).catch(e=>message(e.message));
    },
    focusQueue:(position,minute)=>{play(false);viewPlace(position,15.7,45);setTime(minute);},
    drawQueue:(position,waiting)=>data("bridge-queue",position&&waiting?collection([point(position,{waiting})]):empty),
    onRouting:routing=>{
      if(routing&&qs.get("follow")==="1")
        timedNetwork(routing).then(graph=>{benchmarkDrive=graph;render();}).catch(e=>message(e.message));
    },
    workplace:regional?async(metric)=>{
      const releases=baseRoot+"regional-workplaces/";
      let pair=workPair;
      if(!pair){
        const key=[pointer.atlas,pointer.version,streetPointer.version].join("_");
        const response=await fetch(releases+key+".json");
        if(response.status===404)return null;
        if(!response.ok)throw Error("Workplace comparison is unavailable.");
        const {version:id}=await response.json();
        pair={id,...await json(releases+id+"/report.json")};
        const parents=pair.versions;
        if(parents.atlas!==pointer.atlas||parents.day!==pointer.version||parents.streets!==streetPointer.version||
            parents.transit!==pointer.transit)throw Error("The workplace comparison uses a different weekday.");
      }
      const basis=workBasis??"original";
      const otherDay=basis==="census"?pair.versions.day:pair.day;
      const folder=baseRoot+"bridge-traffic/";
      const key=[pointer.atlas,otherDay,streetPointer.version].join("_")+(metric?"_"+metric:"");
      const response=await fetch(folder+key+".json");
      if(response.status===404)return null;
      if(!response.ok)throw Error("The paired bridge counts are unavailable.");
      const {version}=await response.json();
      const other=await json(folder+version+"/counts.json");
      if(other.versions.day!==otherDay||other.versions.atlas!==pointer.atlas||other.versions.streets!==streetPointer.version)
        throw Error("The paired bridge counts use a different weekday.");
      const refinement=await refinementFor(pair);
      return {...pair,basis,other,refinement};
    }:null,
    external:regional?async(metric)=>{
      const day=workPair?.incomingDay??workPair?.versions.day??pointer.version;
      const base=baseRoot+"incoming-bridges/";
      const key=[pointer.atlas,day,streetPointer.version].join("_")+(metric?"_"+metric:"");
      const response=await fetch(base+key+".json");
      if(response.status===404)return null;
      if(!response.ok)throw Error("Regional incoming bridge counts are unavailable.");
      const {version}=await response.json();
      const report=await json(base+version+"/counts.json");
      if(report.versions.atlas!==pointer.atlas||report.versions.day!==day||report.versions.streets!==streetPointer.version)
        throw Error("Incoming bridge counts use different geography.");
      return report;
    }:null,
    followExternal:(example,report)=>followIncoming(baseRoot,example,report).catch(e=>message(e.message)),
    locate:point=>viewPlace(point,16.7,38),
    follow:([da,i,minute],rule)=>{
      const source=new URL(location.href),url=new URL("cityday.html",location.href);
      for(const key of ["coverage","dayRun","workplaceRun","workplaceBasis","bridge","bridgeDirection","bridgeWindow","bridgeScenario","bridgeMetric","bridgeCommute","decks"])
        if(source.searchParams.has(key))url.searchParams.set(key,source.searchParams.get(key));
      for(const [key,value] of Object.entries({da,person:i+1,minute,follow:1}))url.searchParams.set(key,value);
      if(rule){url.searchParams.set("workplaces","census");url.searchParams.set("commute","tracts");}
      if(rule===2)url.searchParams.set("cycleTours","access");
      location.assign(url);
    }
  });
  map.on("moveend",()=>showTiles().catch(e=>message(e.message)));
  configureBuildingHeights(streetPointer.version);
  if(cycleUrl){
    const parents={atlas:pointer.atlas,day:pointer.version,streets:streetPointer.version,cycling:cycleVersion,
      clock:clockRun?.version??null,workplaces:outbound?.marketParent??null,bikeways:bikewayVersion??null,
      parentBikeways:bikeways?.parentBikeways??null,offBikewayCost:bikeways?.offBikewayCost};
    if(tourVersion){
        parents.tours=tourVersion;
        const view=await import("../js/vancouver/cycle-tours.js");
        cycleTours=view.init(tourRoot,parents.tours,parents,day,json,
          (da,i,m)=>followAt(da,i,m).catch(e=>message(e.message)),()=>{market?.selectRun();renderMobility();refreshCycleCounts?.();render();},places,market.homeIndex);
    }
    import("../js/vancouver/cycle-counts.js").then(mod=>{
      refreshCycleCounts=mod.init(baseRoot+"cycle-counts/",parents,json,()=>outbound?.commuteRule()??"city",()=>cycleTours?.mode(),
        (d,i,minute)=>followAt(d,i,minute).catch(e=>message(e.message)),
        p=>{viewPlace(p,17.5,45);street(BIKE).catch(e=>message(e.message));});
    }).catch(e=>{el("cycle-check").hidden=false;el("cycle-status").textContent=e.message;});
  }
  map.on("click","residents",e=>{
    const layers=[...streetShopLayers,"vacancies","shop-walkers","nearby-walkers","nearby-drivers","granville-guests",...(cityRiders?["rider-walkers"]:[])];
    if(map.queryRenderedFeatures(e.point,{layers}).length)return;
    const {d,resident,i}=e.features[0].properties;
    if(resident!==undefined)inspectResident(day.das[d],resident,t).catch(err=>message(err.message));
    else if(day.sample[i]){
      const [area,person]=day.sample[i];
      choose(day.das[area],person,true).then(showInspector).catch(err=>message(err.message));
    }
  });
  for(const id of ["granville-guests","granville-bodies"])map.on("click",id,e=>{
    followGranville(Number(e.features[0].properties.guest),t);
    showInspector();
  });
  for(const actorLayer of ["nearby-walkers","nearby-drivers","street-bodies"])map.on("click",actorLayer,e=>{
    const layers=[...streetShopLayers,"shop-walkers","vacancies","granville-guests","granville-bodies",...(cityRiders?["rider-walkers"]:[])];
    if(actorLayer==="nearby-walkers")layers.push("nearby-drivers");
    if(map.queryRenderedFeatures(e.point,{layers}).length)return;
    const {d,i,minute}=e.features[0].properties;
    inspectResident(day.das[d],i,minute).catch(e=>message(e.message));
  });
  map.on("click","buildings",e=>{
    if(eyeLevel(vehicle)&&map.queryRenderedFeatures(e.point,{layers:[...streetShopLayers,"street-bodies"]}).length)return;
    const b=e.features[0].properties;
    const basis=b.roofSection?"roof section fitted to "+b.year+" LiDAR":b.basis==="lidar"?"estimated from "+b.year+" LiDAR over "+fmt(b.pixels)+" roof pixels":
      b.basis==="height"?"mapped height":b.basis==="levels"?"estimated from floors":"assumed height";
    message((b.name||"Building")+" · "+b.height+" m · "+basis);
  });
  map.on("click",streetShopLayers,e=>streetShops.inspectSite(e.features[0].properties.id));
  map.on("click","shop-walkers",e=>{
    const layers=[...streetShopLayers,...(cityRiders?["rider-walkers"]:[])];
    if(map.queryRenderedFeatures(e.point,{layers}).length)return;
    const {d,i}=e.features[0].properties;
    inspectResident(day.das[d],i,t).catch(e=>message(e.message));
  });
  map.on("click","vacancies",e=>{
    const layers=[...streetShopLayers,"shop-walkers","opening",...(cityRiders?["rider-walkers"]:[])];
    if(market?.active&&!map.queryRenderedFeatures(e.point,{layers}).length){
      market.selectSite(e.features[0].properties.id);
      showPanel("scenarios");
    }
  });
  map.on("click","opening",e=>{
    const layers=[...streetShopLayers,"shop-walkers",...(cityRiders?["rider-walkers"]:[])];
    if(market?.active&&!map.queryRenderedFeatures(e.point,{layers}).length){
      market.selectSite(e.features[0].properties.id);
      showPanel("scenarios");
    }
  });
  for(const id of day.das.filter(d=>atlas.das[d].population))el("da").add(new Option(id,id));
  const pick=()=>choose(el("da").value,Number(el("person").value)-1).catch(e=>message(e.message));
  el("da").onchange=()=>{el("person").value=1;pick();};el("person").onchange=pick;
  el("route-trails").onchange=render;
  el("overview").onclick=overview;el("leave").onclick=leaveStreet;
  el("resume-street").onclick=resumeStreet;el("street-camera").onclick=toggleStreetCamera;
  el("street-eye").onclick=toggleEyeCamera;
  el("follow").onclick=()=>{
    streetRequest++;
    follow=!follow;parkStreet();
    el("follow").textContent=follow?"Stop following":granvilleGuest!==null?"Follow visitor":incomingTrip?"Follow incoming worker":"Follow resident";
    if(follow){
      map.jumpTo({zoom:16.7,pitch:52});render();
      if(!selected?.overview&&!incomingTrip&&granvilleGuest===null)network().then(render).catch(e=>message(e.message));
    }
  };
  for(const [id,mode] of [["bike",BIKE],["drive",CAR],["walk",WALK]])
    el(id).onclick=()=>street(mode,null,false,true).catch(e=>message(e.message));
  const canvas=map.getCanvas();
  let lookDrag;
  canvas.addEventListener("pointerdown",e=>{
    if(!eyeLevel(vehicle)||e.button!==0||!e.isPrimary)return;
    lookDrag={id:e.pointerId,x:e.clientX,y:e.clientY};
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove",e=>{
    if(!eyeLevel(vehicle)||lookDrag?.id!==e.pointerId)return;
    aimPlayer(vehicle,(lookDrag.x-e.clientX)*.32,(e.clientY-lookDrag.y)*.18);
    lookDrag.x=e.clientX;lookDrag.y=e.clientY;
    streetNeedsPaint=true;
  });
  canvas.addEventListener("lostpointercapture",()=>{lookDrag=null;});
  const refreshStreet=()=>{if(vehicle)streetNeedsPaint=true;};
  map.on("resize",refreshStreet);
  if(deckLayer)map.on("pitchend",()=>{
    const filter=map.getPitch()>=15?["!=",["get","deck"],true]:null;
    for(const layer of ["base-roads","streets"])map.setFilter(layer,filter);
    if(!vehicle&&selected)render();
  });
  map.on("terrain",()=>{
    refreshStreet();
    if(follow&&!vehicle)requestAnimationFrame(render);
  });
  map.on("render",()=>{
    if(vehicle&&(streetCameraHeight!==undefined&&Math.abs(map.getCenterElevation()-streetCameraHeight)>.04||
       eyeLevel(vehicle)&&Math.abs(groundUnderPlayer()-eyeGround)>.04))streetNeedsPaint=true;
  });
  el("left").onclick=()=>turn(-1);el("right").onclick=()=>turn(1);el("reverse").onclick=reverseStreet;
  for(const [id,input] of [["forward",streetInput.accelerator],["brake",streetInput.brake]]){
    const button=el(id);
    button.onpointerdown=e=>{
      if(e.button!==0)return;
      button.setPointerCapture(e.pointerId);input.add(e.pointerId);
    };
    button.onlostpointercapture=e=>input.delete(e.pointerId);
    button.onkeydown=e=>{
      if(!vehicle||![" ","Enter"].includes(e.key))return;
      e.preventDefault();input.add(id);
    };
    button.onkeyup=()=>input.delete(id);
    button.onblur=()=>input.delete(id);
  }
  window.addEventListener("blur",releaseStreetInput);
  window.addEventListener("keydown",e=>{
    if(!vehicle||e.altKey||e.metaKey||e.ctrlKey||e.target.isContentEditable||e.target.closest?.("dialog[open]")||
       /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName))return;
    const key=e.key.toLowerCase();
    if(["arrowup","w"].includes(key)){e.preventDefault();streetInput.accelerator.add(key);}
    else if(["arrowdown","s"].includes(key)){e.preventDefault();streetInput.brake.add(key);}
    else if(eyeLevel(vehicle)&&!e.repeat&&["q","e","c"].includes(key)){
      e.preventDefault();resetOrTurnView(key==="q"?-30:key==="e"?30:0);
    }
    else if(!e.repeat&&["arrowleft","a","arrowright","d","r","escape"].includes(key)){
      e.preventDefault();
      if(key==="escape")leaveStreet();
      else if(key==="r")reverseStreet();
      else turn(key==="arrowleft"||key==="a"?-1:1);
    }
  });
  window.addEventListener("keyup",e=>{
    streetInput.accelerator.delete(e.key.toLowerCase());streetInput.brake.delete(e.key.toLowerCase());
  });
  updateClock({available:true});
  for(const id of ["drive","walk","bike"])el(id).disabled=false;
  const example=day.sample.find(([, ,k,p])=>{
    const s=state(day.templates[k],p);return s.mode==="walk"&&s.p;
  })||day.sample[0];
  const hasDA=atlas.das[qs.get("da")]?.population>0;
  const evidenceRoute=qs.has("follow")&&(qs.has("bridge")&&!bridgeMetric||qs.has("departures"))||
    qs.has("crossing")||qs.has("service")||qs.has("visit")||(replay&&qs.get("shop")==="baseline"&&qs.get("follow")==="1");
  const driveMetric=hasDA&&qs.has("bridge")&&qs.get("follow")==="1"?(bridgeMetric??"distance"):null;
  await choose(hasDA?qs.get("da"):day.das[example[0]],hasDA?Number(qs.get("person")||1)-1:example[1],!evidenceRoute,driveMetric);
  mountJointEvidence?.();
  if(jointRun)import("./discretionary-outings.js").then(view=>
    view.attachLunchWalks(baseRoot+"workplace-lunch/",jointRun,day,places,json,followAt,render)).then(model=>{
      lunchWalks=model;
      if(model){if(location.hash==="#workplace-lunch")openAnchor();render();}
    }).catch(e=>{if(qs.has("lunch")||location.hash==="#workplace-lunch")message(e.message);});
  if(hasDA&&(qs.get("follow")==="1"||(!regional&&(qs.has("crossing")||qs.has("service")||(replay&&qs.has("visit")))))){
    follow=true;el("follow").textContent="Stop following";map.jumpTo({zoom:17.5,pitch:45});render();
  }
  if(!scheduledClock&&!spreadClock)import("../js/vancouver/departures.js").then(view=>view.init(baseRoot+"departures/",pointer.atlas,pointer.version,json,
    (da,i,minute)=>followAt(da,i,minute).catch(e=>message(e.message)),clockRun)).catch(e=>{
      el("departures").hidden=false;el("departure-reference").textContent=e.message;
    });
  el("mobility-check").ontoggle=async()=>{
    if(!el("mobility-check").open)return;
    try{mobility??=await json(dayBase+"mobility.json");renderMobility();}
    catch(e){el("mobility-rate").textContent=e.message;}
  };
  if(regional&&!clockRun){
    const panel=el("north-demand"), folder=baseRoot+"north-shore-demand/";
    fetch(folder+pointer.atlas+"_"+pointer.version+".json").then(async response=>{
      if(response.status===404)return;
      if(!response.ok)throw Error("North Shore trip comparison is unavailable.");
      const {version,gapStreetRelease}=await response.json();
      panel.hidden=false;
      if(gapStreetRelease===streetPointer.version)loadShortWalks(pointer,streetPointer.version,baseRoot).catch(e=>{
        el("regional-walk-controls").hidden=false;el("regional-short-walks").disabled=true;
        el("regional-walk-counts").textContent=e.message;
      });
      panel.ontoggle=async()=>{
        if(!panel.open)return;
        panel.ontoggle=null;
        try{
          const view=await import("../js/experiments/saved.js");
          await view.initNorthDemand(folder,version,pointer.atlas,pointer.version,json,
            (da,i,minute)=>followAt(da,i,minute).catch(e=>message(e.message)));
          const showingZonal=workPair?.zoneAllocation&&workBasis==="census";
          const alternate=workPair?.zoneAllocation?(showingZonal?workPair.originWorkplaceRun:workPair.id):
            workPair?.easternAllocations&&workBasis==="census"?await refinementFor(workPair):null;
          if(alternate){
            const link=el("north-commute-zone-link"), url=new URL(location.href);
            url.searchParams.delete("dayRun");
            url.searchParams.set("workplaceRun",alternate);
            url.searchParams.set("workplaceBasis","census");
            layersForNewDay(url.searchParams);
            if(!url.searchParams.has("bridgeMetric"))url.searchParams.set("bridgeMetric","highway1");
            url.searchParams.set("northWorkplace",el("north-commute-workplace").value);
            link.href=url;
            link.textContent=showingZonal?"Replay the Census workplace fit":"Replay the 2025 workplace fit";
            el("north-commute-zone-link-row").hidden=false;
          }
        }catch(e){el("north-demand-rate").textContent=e.message;}
      };
      if(qs.has("northDemand")||qs.has("northWorkplace"))panel.open=true;
      else if(panel.open)await panel.ontoggle();
    }).catch(e=>{panel.hidden=false;el("north-demand-rate").textContent=e.message;});
    attachRecreation(baseRoot,workTransitParents,day,json,followAt,render).then(async walks=>{
      if(!walks)return;
      recreation=walks;
      if(selected)await walks.loadResident(selected.d);
      render();
    }).catch(e=>{
      el("recreation-loops").hidden=false;el("recreation-status").textContent=e.message;
    });
    attachSchoolEscorts(baseRoot,workTransitParents,day,places,json,followAt,render).then(async model=>{
      if(!model)return;
      schools=model;
      if(selected)await model.loadResident(selected.d);
      render();
    }).catch(e=>{
      el("school-escorts").hidden=false;el("school-status").textContent=e.message;
    });
    attachAttendance(baseRoot,workTransitParents,day,places,json,followAt,render).then(async model=>{
      if(!model)return;
      attendance=model;
      if(selected)await model.loadResident(selected.d);
      render();
    }).catch(e=>{
      el("weekday-attendance").hidden=false;el("attendance-error").textContent=e.message;
    });
    if(workPair&&workBasis==="census")import("./eastern-outings.js").then(view=>view.attachEasternOutings({
      root:baseRoot+"eastern-outings/",versions:workTransitParents,workplaceRun:workPair.id,
      day,places,json,refresh:render,follow:followAt,onLoad:model=>{easternOutings=model;}
    })).catch(e=>{el("eastern-outings").hidden=false;el("eastern-outing-status").textContent=e.message;});
  }
  if(!regional&&!clockRun&&!replay&&(!outbound||jointRun&&!vehicleAccess)){
    source("voting-sites");layer("voting-sites","voting-sites","circle",{
      "circle-color":["case",[">",["get","waiting"],0],"#e2a65d","#9dbab5"],
      "circle-radius":["interpolate",["linear"],["get","waiting"],0,6,50,20],
      "circle-stroke-color":["case",["get","current"],"#fff0b5","#263733"],"circle-stroke-width":2});
    map.on("click","voting-sites",e=>voting?.selectSite(e.features[0].properties.id));
    import("./voting.js").then(view=>view.attachVoting({root:baseRoot,versions:workTransitParents,joint:jointRun?.id,
      day,places,json,refresh:render,follow:followAt,focus:position=>viewPlace(position,16.8,45),network,clock,
      draw:rows=>data("voting-sites",collection(rows.map(({id,point:position,waiting,current})=>point(position,{id,waiting,current})))),
      onLoad:model=>{voting=model;}
    })).catch(e=>{el("voting").hidden=false;el("voting-status").textContent=e.message;});
  }
  if(!regional&&!clockRun&&!outbound&&!replay){
    const panel=el("trip-demand");
    panel.hidden=false;
    let loading=false;
    panel.ontoggle=async()=>{
      if(!panel.open||loading)return;
      loading=true;
      try{
        const view=await import("../js/experiments/saved.js");
        await view.initDemand(baseRoot+"trip-demand/",pointer.atlas,pointer.version,json,
          (da,i,minute)=>followAt(da,i,minute).catch(e=>message(e.message)));
      }catch(e){el("demand-volume").textContent=e.message;}
    };
    if(qs.has("demand")){el("mobility-check").open=true;panel.open=true;}
  }
  if(jointRun){
    const panel=el("trip-timing"),timingRoot=baseRoot+"trip-timing/";
    const requested=qs.has("tripTiming")||qs.has("shoppingClock")||["#trip-timing","#shopping-clock-info"].includes(location.hash);
    const fail=e=>{el("timing-status").textContent=e.message;};
    fetch(timingRoot+jointRun.id+".json").then(async response=>{
      if(response.status===404&&!requested)return;
      panel.hidden=false;
      if(!response.ok)throw Error("The peak-period comparison is unavailable for this weekday.");
      const version=shoppingClock?.report.tripTiming??(await response.json()).version;
      if(!/^[a-f0-9]{20}$/.test(version))throw Error("Invalid peak-period comparison release.");
      const timingJSON=async url=>{
        const report=await json(url);
        if(shoppingClock)for(const period of report.periods)period.shoppingPeak=shoppingClock.report.tripPeaks[period.key].after;
        return report;
      };
      let pending;
      const open=()=>pending??=import("../js/experiments/saved.js")
        .then(view=>view.initTiming(timingRoot+version+"/report.json",jointRun,timingJSON,
          (da,i,minute)=>followAt(da,i,minute).catch(e=>message(e.message)),
          minute=>{play(false);setTime(minute);}))
        .then(()=>import("./shopping-clock.js"))
        .then(view=>view.showShoppingClock(shoppingClockRoot,jointRun,cycleVersion,shoppingClock,day,json,
          (da,i,minute)=>followAt(da,i,minute).catch(e=>message(e.message)),clock))
        .catch(fail);
      panel.ontoggle=()=>{if(panel.open)open();};
      if(requested){el("mobility-check").open=true;panel.open=true;}
      if(panel.open)await open();
    }).catch(fail);
    await loadShortWalks(pointer,streetPointer.version);
  }
  if(!regional&&!outbound&&(!clockRun||spreadClock)){
    if(!clockRun)await loadShortWalks(pointer,streetPointer.version).catch(e=>{el("walk-counts").textContent=e.message;});
    const recreationParents={atlas:pointer.atlas,day:pointer.version,streets:streetPointer.version,cycling:cycleVersion};
    if(spreadClock)recreationParents.clock=clockRun.version;
    if(cycleVersion)attachRecreation(baseRoot,recreationParents,
      day,json,followAt,()=>{renderMobility();render();}).then(async model=>{
        if(!model)return;
        recreation=model;
        if(selected)await model.loadResident(selected.d,false);
        renderMobility();render();
      }).catch(e=>{el("recreation-loops").hidden=false;el("recreation-status").textContent=e.message;});
  }
  if(!regional&&cycleVersion)loadGranville(baseRoot,{streets:streetPointer.version,cycling:cycleVersion},
    json,()=>{
      if(!granville.active&&granvilleGuest!==null){
        stopGranvilleFollow();follow=false;el("follow").textContent="Follow resident";
      }
      render();
    },followGranville,clock).then(model=>{
    if(!model)return;
    granville=model;
    if(qs.has("granvilleGuest")&&!qs.has("street"))followGranville(Number(qs.get("granvilleGuest")),t);
    render();
  }).catch(error=>{
    if(qs.has("granvilleRun")||qs.has("granville"))message(error.message);
  });
  el("status").textContent=fmt(day.population)+" residents · "+fmt(day.sample.length)+" sampled for display"+
    (scheduledClock?" · Commutes timed to transit":spreadClock?" · Spread departures":clockRun?" · Household commute times":
      jointRun?" · Combined weekday":workBasis==="census"?" · "+(workPair?.basisLabels?.census??"Census workplace destinations"):
      workPair?.basisLabels?.original?" · "+workPair.basisLabels.original:"")+
    (workTransitClock?" · Flexible home time":"")+
    (day.homePlacement?" · Census-block homes":"");
  if(regional&&pointer.transit&&!clockRun){
    const timetable=transit.version;
    const parents={...workTransitParents,transit:timetable};
    json(baseRoot+"campus/"+pointer.version+"_"+timetable+"_"+streetPointer.version+".json").then(report=>{
      if(Object.entries(parents).some(([key,value])=>report.versions[key]!==value))
        throw Error("Campus trips use a different weekday or timetable.");
      campus=new CampusDay(report,transit,places,async(d,i,start)=>{
        await followAt(d,i,start);network().then(render).catch(e=>message(e.message));
      },render,minute=>{play(false);setTime(minute);});
      if(qs.get("place")==="ubc")el("campus-panel").open=true;
      render();
    }).catch(e=>{el("campus-panel").hidden=false;el("campus-presence").textContent=e.message;});
  }
  if(qs.has("place"))await goToPlace(qs.get("place"),hasDA);
  if(regional&&!clockRun){
    visitors=new CampusVisitors(map,()=>json(baseRoot+"visitors/"+pointer.version+"_"+streetPointer.version+".json"),()=>t,position=>{
      follow=false;parkStreet();
      el("follow").textContent="Follow resident";map.jumpTo({center:lngLat(position),zoom:16.9,pitch:42});
    });
  }
  source("remote-home");layer("remote-home","remote-home","circle",{"circle-color":"#7dc6fc","circle-opacity":.28,"circle-radius":10,"circle-stroke-color":"#a6dbff","circle-stroke-width":3});
  if(!outbound&&!clockRun)policy=new WorkPolicy(day,()=>json(baseRoot+"raster/"+
    [pointer.atlas,pointer.version,workTransitClock?.version].filter(Boolean).join("_")+".json"),render,async ex=>{
    play(false);follow=false;parkStreet();
    el("follow").textContent="Follow resident";await choose(ex.da,ex.person);
    if(selected?.d!==ex.da||selected.i!==ex.person)return;
    setTime(Math.floor((ex.workStart+ex.workEnd)/2));
    const bounds=new window.maplibregl.LngLatBounds();
    bounds.extend(lngLat(places[ex.home]));bounds.extend(lngLat(places[ex.job]));
    map.fitBounds(bounds,{padding:50,maxZoom:16,pitch:0,bearing:0,duration:0});
  },home=>data("remote-home",home==null?empty:collection([point(places[home],{})])));
  if(!regional||follow&&evidenceRoute)network().then(render).catch(e=>message(e.message));
  let showingHomeBlocks=false;
  source("home-blocks");
  const homeColor=["case",["<",["get","homeDifference"],0],"#9cbbff",[">",["get","homeDifference"],0],"#f0a979","#acf0c7"];
  map.addLayer({id:"home-block-fill",source:"home-blocks",type:"fill",paint:{"fill-color":homeColor,"fill-opacity":.26}},"residents");
  layer("home-block-outline","home-blocks","line",{"line-color":homeColor,"line-width":2.4,"line-opacity":.9});
  try{
    await homePlacement({root:baseRoot,versions:pointer,day,atlas,json,showBlocks:()=>showingHomeBlocks,
      autoZoom:()=>location.hash==="#home-placement"&&!follow&&!vehicle,
      selectOnMap:(blocks,zoom)=>{
        showingHomeBlocks=!!blocks;data("home-blocks",blocks??empty);
        if(!zoom||!blocks?.features.length)return;
        const bounds=new window.maplibregl.LngLatBounds();
        for(const {geometry} of blocks.features){
          const points=geometry.coordinates.flat(geometry.type==="MultiPolygon"?2:1);
          for(const point of points)bounds.extend(point);
        }
        streetRequest++;follow=false;parkStreet();el("follow").textContent="Follow resident";
        map.fitBounds(bounds,{padding:50,maxZoom:17,pitch:0,bearing:0,duration:0});
      },replayUrl:(dayRun,da)=>{
        const url=new URL("cityday.html",location.href);
        const active=new URLSearchParams(location.search);
        for(const key of ["roadTraffic","bikeRoutes","terrain"])if(active.has(key))url.searchParams.set(key,active.get(key));
        for(const [key,value] of Object.entries({...(regional?{coverage:"region"}:{}),dayRun,homeBlock:da,minute:Math.floor(t)}))
          url.searchParams.set(key,value);
        if(selected){url.searchParams.set("da",selected.d);url.searchParams.set("person",String(selected.i+1));}
        if(follow&&!vehicle)url.searchParams.set("follow","1");
        url.hash="home-placement";
        return url;
      }});
  }catch(error){if(location.hash==="#home-placement")message(error.message);}
  if(hire){
    hiredRideControls(hire,hiredRides,render,(d,i,minute)=>followAt(day.das[d],i,minute).catch(e=>message(e.message)));
    source("dispatch-path");layer("dispatch-path","dispatch-path","line",{"line-color":["get","color"],"line-width":3});
    source("dispatch-approach");layer("dispatch-approach","dispatch-approach","line",
      {"line-color":"#e7b465","line-width":3,"line-dasharray":[2,1.4]});
    source("dispatch-actors");layer("dispatch-actors","dispatch-actors","circle",{
      "circle-radius":7,"circle-color":["get","color"],"circle-stroke-color":"#f8f4eb","circle-stroke-width":1.8});
    source("dispatch-bodies");layer("dispatch-bodies","dispatch-bodies","fill-extrusion",bodyPaint);
    hiredDispatchClock=attachHiredDispatch(baseRoot,hire,{
      json,clock,time:()=>t,jump:setTime,
      street:(curb,minute,heading)=>{
        viewPlace(lngLat(curb),17.5,0);map.jumpTo({bearing:heading});play(false);setTime(minute);
        street(WALK,undefined,false,true).then(render).catch(error=>message(error.message));
      },
      focus:(paths,minute,resident)=>{
        dispatchResident=resident;
        const occupied=paths.at(-1);
        data("dispatch-path",collection([feature(line(occupied),{color:"#cbb5ff"})]));
        data("dispatch-approach",paths.length>1?collection([feature(line(paths[0]))]):empty);
        const bounds=new window.maplibregl.LngLatBounds();
        for(const path of paths)for(const position of path)bounds.extend(lngLat(position));
        streetRequest++;follow=false;parkStreet();el("follow").textContent="Follow resident";
        map.fitBounds(bounds,{padding:90,maxZoom:17,pitch:0,bearing:0,duration:0});
        play(false);setTime(minute);
      },
      draw:(frame,service)=>{
        if(!frame){
          for(const id of ["dispatch-path","dispatch-approach","dispatch-actors","dispatch-bodies"])data(id,empty);
          if(dispatchResident){dispatchResident=null;render();}
          return;
        }
        const actors=[];
        if(frame.passenger)actors.push([...frame.passenger,{mode:WALK,color:"#6fd5ad"}]);
        if(frame.vehicle)actors.push([...frame.vehicle,{mode:CAR,service,heading:frame.heading,
          color:frame.occupied?"#cbb5ff":"#e7b465"}]);
        const eye=eyeLevel(vehicle);
        data("dispatch-actors",eye?empty:collection(actors.map(([x,y,info])=>point([x,y],{color:info.color}))));
        data("dispatch-bodies",eye?collection(streetBodies(actors)):empty);
      }});
    render();
  }
  if(spreadClock||!clockRun&&!workTransitClock&&!outbound&&!replay)
    await departureClockEvidence(baseRoot,pointer,spreadClock?clockRun:null).catch(error=>{if(spreadClock)message(error.message);});
  requestAnimationFrame(tick);
  if(qs.has("street")){
    const mode={walk:WALK,drive:CAR,bike:BIKE}[qs.get("street")];
    const [lon,lat,bearing]=(qs.get("at")||"").split(",").map(Number);
    if(!mode||(mode===BIKE&&!cycleVersion)||![lon,lat,bearing].every(Number.isFinite)||lon<w||lon>e||lat<s||lat>n)
      message("This street link needs a mapped location and travel mode for the selected study area.");
    else{
      map.jumpTo({center:[lon,lat],bearing});
      const camera=qs.get("camera"),look=qs.get("look")?.split(",").slice(0,2).map(Number);
      await street(mode,qs.get("edge")?.split(",").map(Number),camera==="overhead",camera==="eye",look);
    }
  }else if(qs.has("roadSection")&&!follow&&location.hash==="#road-traffic"){
    el("road-traffic-view").click();
  }
  openAnchor();
}
init().catch(error=>{
  console.error("Vancouver weekday initialization failed",error);
  el("status").textContent=error.message;
});
