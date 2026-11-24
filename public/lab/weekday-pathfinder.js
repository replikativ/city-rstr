import {distance} from "./vancouver-network.js";

export const routeKey=(mode,a,b,duration,speed,prefer,hour)=>
  [mode,a[0],a[1],b[0],b[1],duration,speed,prefer].join("/")+(hour===undefined?"":"/"+hour);

const segmentKey=(a,b)=>`${a[0]},${a[1]}/${b[0]},${b[1]}`;

export const affectedSegments=segments=>new Set(segments.map(([a,b])=>segmentKey(a,b)));

// This profile only increases costs. An unaffected shortest path stays optimal,
// and a previously infeasible route cannot become feasible.
export function reusableFreeFlow(route,affected){
  return !route||!route.path.some((b,i,path)=>i>1&&i<path.length-1&&affected.has(segmentKey(path[i-1],b)));
}

export function findRoute(graph,mode,a,b,duration,speed,prefer,departure){
  if(!graph)return null;
  if(mode===2&&graph.driveSpeed)return graph.driveRoute(a,b,duration,departure);
  const path=graph.route(a,b,mode,duration*speed,prefer);
  if(!path)return null;
  const offsets=[0];
  for(let i=1;i<path.length;i++)offsets.push(offsets[i-1]+distance(path[i-1],path[i])/speed);
  return {path,offsets,minutes:offsets.at(-1)};
}
