import {BIKE,CAR,departureHour,distance,positionOnSegment} from "./vancouver-network.js";

export const radius=250;
export const bicycleMetresPerMinute=220;

export function* streetLegs(chunk,day){
  for(let offset=0;offset<chunk.byteLength;offset+=16){
    const d=chunk.getUint16(offset),i=chunk.getUint16(offset+2),tpl=chunk.getUint16(offset+4);
    const part=day.templates[tpl].parts[chunk.getUint16(offset+6)];
    yield [d,i,tpl,part,chunk.getInt32(offset+8),chunk.getInt32(offset+12)];
  }
}

export function activeStreetMode(work,part,commuteOnly){
  return work?.replaceMode??work?.assignedMode??(commuteOnly?null:part[2]);
}

export function activeStreetLeg(work,part,from,to,commuteOnly,speeds,shopping,shopSpeed){
  const mode=activeStreetMode(work,part,commuteOnly);
  if(work?.external||!["walk","bike","car-driver"].includes(mode))return null;
  const a=part[3],b=part[4];
  const origin=shopping?.get(a)??work?.overrides?.get(a)??from,dest=shopping?.get(b)??work?.overrides?.get(b)??to;
  let speed=mode==="walk"?150:bicycleMetresPerMinute;
  if(mode!=="car-driver"&&(work?.replaceMode||work?.overrides))speed=speeds?.[mode==="walk"?"Walking":"Bicycle"]??speed;
  if(mode==="walk"&&(shopping?.has(a)||shopping?.has(b)))speed=shopSpeed;
  return origin>=0&&dest>=0?[origin,dest,speed,mode==="bike"?BIKE:mode==="car-driver"?CAR:1]:null;
}

// Inspect the directed route in replay order. Keep separate failed search budgets
// because a longer diary leg between the same places may admit a route.
export function budgetRoute(graph,places,paths,a,b,mode,limit,shortest=false){
  const key=a+"/"+b+(graph.bikeways?shortest?"/shortest":"/"+limit:"");
  let entry=paths.get(key);
  if(!entry||(!entry.points&&entry.limit<limit)){
    const points=graph.route(places[a],places[b],mode,limit,shortest?false:undefined);
    const metres=points?.reduce((n,p,k)=>n+(k?distance(points[k-1],p):0),0)??Infinity;
    entry={points,limit,metres};
    if(paths.size>=8192)paths.delete(paths.keys().next().value);
    paths.set(key,entry);
  }
  return entry.metres>0&&entry.metres<=limit?entry:null;
}

export function nearbyPositions(graph,places,paths,rows,minute,centre,mode=1,segments=false){
  const found=[];
  for(const [d,i,start,duration,a,b,speed,shortest,tag] of rows){
    const elapsed=minute-start,remaining=duration-elapsed;
    if(elapsed<0||remaining<=0||a===b)continue;
    const origin=places[a],destination=places[b],limit=duration*speed;
    if(origin[0]===destination[0]&&origin[1]===destination[1])continue;
    if(distance(origin,centre)>radius+elapsed*speed||distance(destination,centre)>radius+remaining*speed)continue;
    const entry=budgetRoute(graph,places,paths,a,b,mode,limit,shortest);
    if(!entry)continue;
    const {point:p,segment}=positionOnSegment(entry.points,elapsed/duration),away=distance(p,centre);
    if(away<=radius)found.push(segments?[d,i,...p,away,tag,segment]:tag?[d,i,...p,away,tag]:[d,i,...p,away]);
  }
  return found.sort((a,b)=>a[4]-b[4]||a[0]-b[0]||a[1]-b[1]);
}

export const driverSampleDenominator=8;
export const sampleDriver=(da,person)=>(Math.imul(da,17)+Math.imul(person,31))%driverSampleDenominator===0;

function driveKey(graph,a,b,start){
  const hour=graph.trafficHours?.has(departureHour(start))?departureHour(start):"default";
  return [a,b,hour].join("/");
}

function timedDrive(graph,places,paths,key,a,b,duration,start){
  let entry=paths.get(key);
  if(!entry||!entry.route&&entry.limit<duration){
    if(!entry&&paths.size>=16000)paths.delete(paths.keys().next().value);
    entry={limit:duration,route:graph.driveRoute(places[a],places[b],duration,start)};
    paths.set(key,entry);
  }
  return entry.route?.minutes<=duration?entry.route:null;
}

export function* scanDrivers(graph,places,paths,rows,minute,centre,segments=false){
  const candidates=[];
  for(const [d,i,start,duration,a,b,,,tag,useObserved,service] of rows){
    const elapsed=minute-start,remaining=duration-elapsed;
    if(elapsed<0||remaining<=0||a===b)continue;
    const origin=places[a],destination=places[b],fraction=elapsed/duration;
    if(distance(origin,centre)>radius+elapsed*graph.maxDriveSpeed||
       distance(destination,centre)>radius+remaining*graph.maxDriveSpeed)continue;
    const departure=useObserved===false?undefined:start;
    const key=driveKey(graph,a,b,departure);
    const known=paths.get(key);
    const rank=known&&(known.route||known.limit>=duration)?-1:
      distance([origin[0]+fraction*(destination[0]-origin[0]),origin[1]+fraction*(destination[1]-origin[1])],centre);
    candidates.push({d,i,departure,duration,a,b,fraction,key,rank,tag,service});
  }
  candidates.sort((a,b)=>a.rank-b.rank);
  for(const {d,i,departure,duration,a,b,fraction,key,tag,service} of candidates){
    const route=timedDrive(graph,places,paths,key,a,b,duration,departure);
    if(!route){yield null;continue;}
    const {path,offsets,minutes}=route,at=fraction*minutes;
    // Access and egress connect diary addresses to the network. Show vehicles
    // only while on a mapped road segment.
    if(at<offsets[1]||at>=offsets.at(-2)){yield null;continue;}
    let lo=1,hi=path.length-2;
    while(lo+1<hi){
      const mid=(lo+hi)>>1;
      if(offsets[mid]<=at)lo=mid;else hi=mid;
    }
    const [x,y]=path[lo],[u,v]=path[hi],onEdge=(at-offsets[lo])/(offsets[hi]-offsets[lo]);
    const p=[x+onEdge*(u-x),y+onEdge*(v-y)],away=distance(p,centre);
    if(away>radius){yield null;continue;}
    const row=[d,i,...p,away,CAR,Math.atan2(u-x,y-v)*180/Math.PI];
    if(segments){
      const actor=[...row,tag,null,[path[lo],path[hi]]];
      if(service)actor.push(service);
      yield actor;
    }else yield tag?[...row,tag]:row;
  }
}

export function nearbyDrivers(graph,places,paths,rows,minute,centre){
  return [...scanDrivers(graph,places,paths,rows,minute,centre)].filter(Boolean)
    .sort((a,b)=>a[4]-b[4]||a[0]-b[0]||a[1]-b[1]);
}
