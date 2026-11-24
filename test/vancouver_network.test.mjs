import test from "node:test";
import assert from "node:assert/strict";
import {Network,driveTimesTo,roadMode} from "../public/lab/vancouver-network.js";
import {affectedSegments,reusableFreeFlow} from "../public/lab/weekday-pathfinder.js";
import {WeekdayRoutes} from "../public/lab/weekday-routes.js";

test("the selected resident's route runs ahead of the overview batch",()=>{
  const router=new WeekdayRoutes({},()=>{});
  let queued;
  router.worker={postMessage:({requests})=>{queued=requests;}};
  router.ready=true;
  router.begin(480);
  const origin=[0,0],destination=[200,0];
  for(let i=0;i<40;i++)router.get(2,origin,[i+1,0],10,380);
  router.get(2,origin,destination,10,380,false,480,true);
  router.flush();
  assert.equal(queued.length,1);
  assert.deepEqual(queued[0][3],destination);
});

test("curb search shares a directed frontier and respects changing budgets",()=>{
  const nodes=[[0,0],[100,0],[200,0],[100,120]];
  const graph=new Network({nodes,names:[""],ways:[[2,0,[0,1,2]],[6,0,[1,3,2]]]},null,
    {kmh:[[36,0],[72,54]],connectorKmh:22.8,connectorMetres:500});
  const run=driveTimesTo(graph);
  assert.equal(run(0,2,.3),Infinity);
  assert.ok(Math.abs(run(0,2,.35)-graph.driveRoute(nodes[0],nodes[2]).minutes)<1e-12);
  assert.equal(run(0,2,.3),Infinity);
  assert.ok(Math.abs(run(1,2,.17)-100/600)<1e-12);
  assert.equal(run(2,0,2),Infinity);
  assert.ok(Math.abs(run(2,1,1)-graph.driveRoute(nodes[2],nodes[1]).minutes)<1e-12);
});

test("street entry projects onto the nearest legal directed segment",()=>{
  const graph=new Network({nodes:[[0,0],[100,0],[0,15],[100,15]],names:["One way","Two way"],
    ways:[[2,0,[0,1]],[6,1,[2,3]]]});
  const mode=roadMode("car-driver");
  const oneWay=graph.streetStart([39,1],mode,-90);
  assert.deepEqual(oneWay.p,[39,0]);
  assert.equal(oneWay.heading,90);
  assert.equal(oneWay.edge.name,"One way");
  const twoWay=graph.streetStart([39,14],mode,-90);
  assert.deepEqual(twoWay.p,[39,15]);
  assert.equal(twoWay.heading,-90);
});

test("a venue equally close to several walkable nodes uses the lowest network ID",()=>{
  const graph=new Network({nodes:[[-1,0],[0,-1],[1,0],[10,0]],names:[""],ways:[[1,0,[0,3,1,2]]]});
  assert.equal(graph.snap([0,0],roadMode("walk")),0);
});

test("different offsets with identical squared distances retain the same tie rule",()=>{
  const graph=new Network({nodes:[[1866,3456],[1859,3459],[1700,3320]],names:[""],ways:[[1,0,[0,2,1]]]});
  assert.equal(graph.snap([1885,3510],roadMode("walk")),0);
});

test("bounded pedestrian routing includes both access legs and preserves the replay's choice on ties",()=>{
  const nodes=[[0,0],[3,4],[3,-4],[6,0],[16,0],[40,0],[42,0]];
  const graph=new Network({nodes,names:[""],ways:[[1,0,[0,1,3,4]],[1,0,[0,2,3]],[1,0,[5,6]]]});
  const a=[-1,0],b=[7,0],mode=roadMode("walk"),full=graph.route(a,b,mode);
  assert.equal(full.length,5);
  assert.deepEqual(graph.route(a,b,mode,12),full);
  assert.equal(graph.route(a,b,mode,11.999),null);
  assert.equal(graph.route(a,nodes[5],mode,200),null);
});

test("bikeway preference respects direction, physical detour budgets and both access legs",()=>{
  const nodes=[[0,0],[50,20],[100,0]];
  const graph=new Network({nodes,names:["Road"],ways:[[24,0,[0,2]],[24,0,[0,1,2]]]},
                          {offBikewayCost:1.25,arcs:[[0,1],[1,2]]});
  const a=[-5,0],b=[105,0],mode=roadMode("bike");
  assert.ok(graph.route(a,b,mode,120).includes(nodes[1]));
  assert.ok(!graph.route(a,b,mode,110).includes(nodes[1]));
  assert.equal(graph.route(a,b,mode,109.99),null);
  assert.ok(!graph.route(b,a,mode,120).includes(nodes[1]));
});

test("uphill cost can change the route in one direction within the same distance budget",()=>{
  const nodes=[[0,0],[50,32],[100,0]];
  const ways=[[24,0,[0,2]],[24,0,[0,1,2]]];
  const arcs=[[0,2],[2,0],[0,1],[1,2],[2,1],[1,0]];
  const graph=new Network({nodes,ways,names:[""]},
    {offBikewayCost:1.25,arcs,uphillArcs:[[0,2,3]],uphillCosts:[0,.32,.79,1.45]});
  assert.ok(graph.route(nodes[0],nodes[2],4,120).includes(nodes[1]));
  assert.ok(!graph.route(nodes[0],nodes[2],4,110).includes(nodes[1]));
  assert.ok(!graph.route(nodes[2],nodes[0],4,120).includes(nodes[1]));
  assert.equal(graph.route(nodes[0],nodes[2],4,99),null);
});

test("driving minimizes time and uses a longer fast road when it fits the clock",()=>{
  const nodes=[[0,0],[1000,0],[0,400],[1000,400]];
  const graph=new Network({nodes,names:["Local","Main road"],
    ways:[[6,0,[0,1]],[6,1,[0,2,3,1]]]},
    null,{kmh:[[20,20],[80,40]],connectorKmh:22.8,connectorMetres:500});
  const [a,b]=nodes;
  assert.equal(graph.route(a,b,2).some(p=>p===nodes[2]),false);
  const fast=graph.driveRoute(a,b,1.5);
  assert.ok(fast.path.includes(nodes[2]));
  assert.ok(Math.abs(fast.minutes-1.35)<1e-10);
  assert.equal(graph.driveRoute(a,b,1),null);
  assert.ok(Math.abs(graph.driveRoute(b,a,3).minutes-2.7)<1e-10);
  assert.equal(graph.driveRoute([-600,0],b,20),null);
  assert.equal(fast.offsets.at(-1),fast.minutes);
});

test("observed travel times change route choice by departure hour and direction",()=>{
  const nodes=[[0,0],[0,500],[300,0],[300,500]], [a,b]=nodes;
  const ways=[[6,0,[0,1]],[6,1,[0,2,3,1]]];
  const graph=new Network({nodes,ways,names:["Local","Fast"]},null,
    {kmh:[[15,15],[90,90]],connectorKmh:22.8,connectorMetres:500,
     hourly:{hours:[16],corridors:[{arcs:[[2,3]],factors:[6]}]}});
  assert.ok(graph.driveRoute(a,b,3,959).path.includes(nodes[2]));
  assert.ok(!graph.driveRoute(a,b,3,960).path.includes(nodes[2]));
  assert.ok(graph.driveRoute(b,a,3,960).path.includes(nodes[2]));
  assert.equal(graph.driveRoute(a,b,1,960),null);
});

test("the observed profile reuses only free-flow routes whose directed streets are unaffected",()=>{
  const a=[10,0],b=[20,0],c=[30,0],from=[0,0],to=[40,0];
  const affected=affectedSegments([[a,b],[c,to]]);
  assert.equal(reusableFreeFlow({path:[from,a,b,c,to]},affected),false);
  assert.equal(reusableFreeFlow({path:[to,c,b,a,from]},affected),true);
  assert.equal(reusableFreeFlow({path:[from,a,c,to]},affected),true);
  assert.equal(reusableFreeFlow(null,affected),true);
});
