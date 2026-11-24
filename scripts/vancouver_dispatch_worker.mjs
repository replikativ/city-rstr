import {readFileSync} from "node:fs";
import {parentPort,workerData} from "node:worker_threads";
import {simulate} from "../public/js/vancouver/hired-dispatch.js";
import {Network,distance,driveTimesTo} from "../public/lab/vancouver-network.js";

const {network,speeds,group,staged,patience}=workerData;
const read=path=>JSON.parse(readFileSync(path));
const graph=new Network(read(network),null,read(speeds));
const driveMinutes=driveTimesTo(graph);
const lower=(a,b)=>Math.floor(60*distance(graph.nodes[a],graph.nodes[b])/graph.maxDriveSpeed);
function travel(a,b,limit){
  const cost=Math.ceil(driveMinutes(a,b,(limit+1e-7)/60)*60-1e-7);
  return cost<=limit?cost:undefined;
}

parentPort.postMessage(simulate(group,staged,patience,lower,travel));
