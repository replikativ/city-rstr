import test from "node:test";
import assert from "node:assert/strict";
import {Network,roadMode} from "../scripts/vancouver-network.js";

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
