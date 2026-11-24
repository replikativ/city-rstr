import {BIKE,CAR,distance} from "./vancouver-network.js";

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
