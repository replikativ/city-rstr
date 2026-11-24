import {distance} from "./vancouver-network.js";

export const routeKey=(mode,a,b,duration,speed,prefer,hour)=>
  [mode,a[0],a[1],b[0],b[1],duration,speed,prefer].join("/")+(hour===undefined?"":"/"+hour);

export function findRoute(graph,mode,a,b,duration,speed,prefer,departure){
  if(!graph)return null;
  if(mode===2&&graph.driveSpeed)return graph.driveRoute(a,b,duration,departure);
  const path=graph.route(a,b,mode,duration*speed,prefer);
  if(!path)return null;
  const offsets=[0];
  for(let i=1;i<path.length;i++)offsets.push(offsets[i-1]+distance(path[i-1],path[i])/speed);
  return {path,offsets,minutes:offsets.at(-1)};
}
