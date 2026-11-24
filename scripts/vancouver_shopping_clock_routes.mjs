import {readFileSync,writeFileSync} from "node:fs";
import {BIKE,Network} from "../public/lab/vancouver-network.js";
import {bicycleMetresPerMinute} from "../public/lab/street-pedestrians.js";

const [, , networkFile, placesFile, requestsFile, output]=process.argv;
const read=file=>JSON.parse(readFileSync(file,"utf8"));
const graph=new Network(read(networkFile)),places=read(placesFile);
const cache=new Map();
function fits(a,b,minutes){
  const key=[a,b,minutes].join("/");
  if(!cache.has(key))cache.set(key,!!graph.route(places[a],places[b],BIKE,minutes*bicycleMetresPerMinute,false));
  return cache.get(key);
}
const result=read(requestsFile).map(([a,b,c,out,back])=>fits(a,b,out)&&fits(b,c,back));
writeFileSync(output,JSON.stringify({speed:bicycleMetresPerMinute,result}));
