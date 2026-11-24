import test from "node:test";
import assert from "node:assert/strict";
import {BIKE,CAR,Network,WALK,lngLat,xy} from "../public/lab/vancouver-network.js";
import {activeStreetLeg,nearbyDrivers,nearbyPositions,sampleDriver,scanDrivers} from "../public/lab/street-pedestrians.js";
import {aimPlayer,playerCamera,playerLink,playerSprite,startPlayer,stepPlayer,streetBodies,turnAround} from "../public/lab/street-player.js";
import {mergeStreetActors} from "../public/lab/nearby-walks.js";
import {nearbyScenarioRecords,scenarioActor,streetOutings} from "../public/lab/street-scenarios.js";
import {HiredRides} from "../public/lab/hired-rides.js";
import {shiftedShopping} from "../public/lab/shopping-clock.js";

test("a polling detour uses the original away location and returns to the resident's home",()=>{
  const tour=[3,8,5,6,"Voting","walk",480,7,9,12,4];
  const legs=streetOutings([tour],{walkMetresPerMinute:80},"voting")[WALK][4];
  assert.deepEqual(legs.map(row=>row.slice(0,6)),[[3,8,480,487,4,6],[3,8,496,508,6,5]]);
});

test("a hired ride keeps its resident, mapped endpoints and diary window through street playback",()=>{
  const nodes=[[0,0],[600,0]];
  const graph=new Network({nodes,names:["Main"],ways:[[6,0,[0,1]]]},
    null,{kmh:[[45,45]],connectorMetres:250,connectorKmh:22.8});
  const model=new HiredRides({rows:[[0,7,479,4,0,1,"ridehail",true],[0,9,479,4,0,1,"taxi",false]]},nodes,false);
  const original={mode:"car-passenger",start:479,dur:4,a:nodes[0],b:nodes[1]};
  assert.equal(model.apply(original,0,7),original);
  assert.deepEqual(model.streetRows(7).map(row=>row[10]),["taxi"]);
  model.enabled=true;
  assert.equal(model.apply(original,0,7).mode,"ridehail");
  assert.equal(model.apply({...original,b:[600,10]},0,7).mode,"car-passenger");
  assert.deepEqual(model.streetRows(8,id=>new Map([[0,id]])).map(row=>row[10]),[]);
  const rows=model.streetRows(8);
  const actors=[...scanDrivers(graph,nodes,new Map(),rows,481,[300,0],true)];
  assert.deepEqual(actors.map(actor=>[actor[1],actor[2],actor[10]]),[[7,300,"ridehail"],[9,300,"taxi"]]);
  assert.deepEqual([...scanDrivers(graph,nodes,new Map(),rows,483,[600,0],true)],[]);
});

test("eye-level view rotates around the player and records its aim in the link",()=>{
  const graph=new Network({nodes:[[0,0],[300,0]],names:["Main"],ways:[[1,0,[0,1]]]});
  const p=startPlayer(graph,WALK,0,90,null,false,true);
  const pose={calculateCameraOptionsFromTo:(p,here,look,there)=>({p,here,look,there})};
  const initial=playerCamera(p,1,pose,30);
  assert.deepEqual(initial.p,lngLat([0,0]));
  assert.equal(initial.here,31.65);
  assert.ok(Math.abs(xy(initial.look)[0]-18)<1e-4);
  aimPlayer(p,90,6);
  const turned=playerCamera(p,1,pose,30);
  assert.deepEqual(turned.p,initial.p);
  assert.ok(Math.abs(xy(turned.look)[1]-18)<1e-4);
  assert.ok(turned.there>turned.here);
  const url=playerLink(p,new URL("http://example.test/"),480);
  assert.equal(url.searchParams.get("camera"),"eye");
  assert.equal(url.searchParams.get("look"),"90.0,6.0");
  assert.equal(url.searchParams.get("minute"),"480");
});

test("eye-level bodies retain resident identity and the car footprint faces its heading",()=>{
  const properties={mode:CAR,heading:90,d:4,i:9,minute:480,scenario:false};
  const bodies=streetBodies([[0,0,properties]]);
  assert.equal(bodies.length,2);
  assert.equal(bodies[1].properties.i,9);
  const ring=bodies[0].geometry.coordinates[0].map(xy);
  const span=axis=>Math.max(...ring.map(p=>p[axis]))-Math.min(...ring.map(p=>p[axis]));
  assert.ok(Math.abs(span(0)-4.1)<1e-4);
  assert.ok(Math.abs(span(1)-1.76)<1e-4);
});

test("walkers follow both sides of a bend and disappear exactly at arrival",()=>{
  const places=[[0,0],[0,400],[400,400],[400,0]],paths=new Map();
  const graph=new Network({nodes:places,names:["Test Street"],ways:[[1,0,[0,1,2,3]]]});
  const walks=[[0,8,300,10,0,3,80],[0,9,300,10,0,3,150],[0,10,300,30,0,3,80]];
  assert.deepEqual(nearbyPositions(graph,places,paths,walks,305,[200,400]),[[0,9,200,400,0]]);
  assert.deepEqual(nearbyPositions(graph,places,paths,walks,310,[400,0]),[]);
  assert.deepEqual(nearbyPositions(graph,places,paths,walks,315,[200,400]),[[0,10,200,400,0]]);
});

test("a shared street link restores its directed edge and rejects a moved or inaccessible edge",()=>{
  const g=new Network({nodes:[[0,0],[0,100]],names:["Main"],ways:[[3,0,[0,1]]]});
  const v=g.resumeEdge([0.04,51],2,[0,1,-1,90]);
  assert.deepEqual(v.p,[0,51]);assert.equal(v.edge.name,"Main");assert.equal(v.turn,90);
  assert.equal(g.resumeEdge([0,51],2,[1,0,-1,0]),null);
  assert.equal(g.resumeEdge([10,51],2,[0,1,-1,0]),null);
});

test("a one-way bicycle trip can finish at a sink exactly at its distance budget",()=>{
  const places=[[0,0],[220,0]],paths=new Map(),centre=[110,0];
  const graph=new Network({nodes:places,names:["Cycleway"],ways:[[8,0,[0,1]]]});
  const tr=(id,a,b,speed)=>[0,id,480,1,a,b,speed];
  const trips=[tr(0,1,0,220),tr(1,0,1,219),tr(2,0,1,220)];
  assert.deepEqual(nearbyPositions(graph,places,paths,trips,480.5,centre,BIKE),[[0,2,110,0,0]]);
  assert.deepEqual(nearbyPositions(graph,places,paths,trips,481,centre,BIKE),[]);
});

test("a reassigned commute uses its scenario mode and workplace",()=>{
  const trip=[480,20,"transit",0,1],work={overrides:new Map([[1,19]]),replaceMode:"bike"};
  assert.deepEqual(activeStreetLeg(work,trip,10,11,true,{Bicycle:220}),[10,19,220,BIKE]);
  assert.equal(activeStreetLeg(null,trip,10,11,true),null);
  assert.equal(activeStreetLeg({external:true,assignedMode:"bike"},trip,10,11,true),null);
});

test("nearby cyclists with the same endpoints choose different routes when only one can afford a detour",()=>{
  const nodes=[[0,0],[50,20],[100,0]], paths=new Map();
  const graph=new Network({nodes,names:["Street"],ways:[[24,0,[0,2]],[24,0,[0,1,2]]]},
                          {offBikewayCost:1.25,arcs:[[0,1],[1,2]]});
  const rows=[[0,0,480,1,0,2,100],[0,1,480,1,0,2,120]];
  assert.deepEqual(nearbyPositions(graph,nodes,paths,rows,480.5,nodes[1],BIKE).map(p=>p.slice(1,4)),
                   [[1,50,20],[0,50,0]]);
});

test("nearby cars use directed travel times, skip address connectors and retain heading",()=>{
  const street={nodes:[[0,0],[100,0],[100,-100]],names:["Avenue"],ways:[[2,0,[0,1,2]]]};
  const profile={kmh:[[36,36]],connectorMetres:250,connectorKmh:36};
  const graph=new Network(street,null,profile),places=[[-40,0],[100,-130]];
  const rows=[[0,0,480,1,0,1],[0,1,480,1,1,0]];
  assert.deepEqual(nearbyDrivers(graph,places,new Map(),rows,480.05,[0,0]),[]);
  const results=nearbyDrivers(graph,places,new Map(),rows,480.6,[100,0]);
  assert.equal(results.length,1);
  assert.equal(results[0][1],0);
  assert.equal(results[0][2],100);
  assert.ok(Math.abs(results[0][3]+22)<1e-9);
  assert.deepEqual(results[0].slice(5),[CAR,0]);
  assert.equal(Array.from({length:16},(_,i)=>sampleDriver(21,i)).filter(Boolean).length,2);
});

test("player braking, the queued turn and a directed turnaround preserve the street position",()=>{
  const graph=new Network({nodes:[[0,0],[0,-5],[0,-10],[-100,-10],[20,-10],[0,-80]],
    names:["Main","West","East"],
    ways:[[6,0,[0,1,2,5]],[6,1,[2,3]],[2,2,[2,4]]]});
  const p=startPlayer(graph,CAR,0,0,null);
  p.turn=-90;
  for(let k=0;k<18;k++)stepPlayer(p,.1,true,false);
  assert.equal(p.turn,-90);
  while(p.turn)stepPlayer(p,.1,true,false);
  assert.equal(p.edge.next,3);
  for(let k=0;k<20;k++)stepPlayer(p,.1,false,true);
  assert.equal(p.velocity,0);
  const at=p.p.slice();
  assert.equal(turnAround(p),true);
  assert.deepEqual(p.p,at);
  assert.equal(p.edge.next,2);
  const reverse=graph.resumeEdge([10,-10],CAR,[2,4,1,0]);
  assert.ok(reverse);
  assert.equal(turnAround(startPlayer(graph,CAR,2,90,reverse)),false);
});

test("street links round-trip the player, direction and map camera",()=>{
  const graph=new Network({nodes:[[0,0],[100,0]],names:["Road"],ways:[[6,0,[0,1]]]});
  const p=startPlayer(graph,CAR,0,90,graph.resumeEdge([50,0],CAR,[0,1,-1,90]),true);
  const url=playerLink(p,new URL("https://example.test/cityday.html?coverage=region"),540);
  assert.equal(url.searchParams.get("camera"),"overhead");
  assert.equal(url.searchParams.get("edge"),"0,1,-1,90");
  assert.equal(url.searchParams.get("minute"),"540");
  assert.equal(playerCamera(p).pitch,0);
  p.overhead=false;
  assert.equal(playerCamera(p).pitch,72);
  const sprite=playerSprite(CAR,true);
  assert.equal(sprite.data.length,sprite.width*sprite.height*4);
});

test("scenario actors retain their resident identity and a school walking group's size",()=>{
  const point={mode:"walk",routed:true,p:[20,0],streetParty:4};
  const escort=scenarioActor(0,8,500,[0,0],point,"school-escorts");
  assert.deepEqual(escort,[0,8,20,0,20,1,null,"school-escorts",4]);
  assert.deepEqual(mergeStreetActors([[0,8,30,0,30,1]], [escort]),[escort]);
  assert.deepEqual(nearbyScenarioRecords([[0,8,500,510,20,0,30,10,1]],509,[0,0],false),[]);
  assert.deepEqual(nearbyScenarioRecords([[0,8,500,510,20,0,30,10,1]],510,[0,0]),[]);
});

test("scenario vehicles represent sampled drivers and exclude passengers aboard a vehicle",()=>{
  const ride={mode:"car-driver",start:480,p:[50,0],routed:true,path:[[0,0],[100,0]],offsets:[0,10]};
  assert.deepEqual(scenarioActor(0,8,485,[0,0],ride,"school-escorts"),
    [0,8,50,0,50,CAR,90,"school-escorts",1,[[0,0],[100,0]]]);
  assert.equal(scenarioActor(0,7,485,[0,0],ride,"school-escorts"),null);
  assert.equal(scenarioActor(0,8,485,[0,0],{...ride,mode:"car-passenger"},"school-escorts"),null);
  const boarding={mode:"transit",scheduled:true,routed:true,p:[50,0]};
  assert.equal(scenarioActor(0,8,485,[0,0],{...boarding,description:"Scheduled transit"},"weekday-attendance"),null);
  assert.equal(scenarioActor(0,8,485,[0,0],{...boarding,description:"Walking to the stop"},"weekday-attendance")[5],1);
});

test("outing legs preserve their exact stop time and use free-flow street routing",()=>{
  const indexed=streetOutings([[0,8,0,1,"Shopping","car-driver",470,10,60,15]],
    {walkMetresPerMinute:80});
  assert.deepEqual(indexed[CAR][7-4],[[0,8,470,480,0,1,380,false,"discretionary-outings",false]]);
  assert.deepEqual(indexed[CAR][8-4],[]);
  assert.equal(indexed[CAR][9-4][0][2],540);
});

test("a grocery opening redirects both legs of a fitted walking outing",()=>{
  const trip=[0,8,0,1,"Shopping","walk",479,4,20,6];
  const indexed=streetOutings([trip],{walkMetresPerMinute:80},undefined,new Map([["0/8",2]]));
  assert.deepEqual(indexed[WALK][7-4][0].slice(2,6),[479,483,0,2]);
  assert.deepEqual(indexed[WALK][8-4].at(-1).slice(2,6),[503,509,2,0]);
  assert.equal(trip[3],1);
});

test("a shifted bicycle tour replaces only the affected time and preserves both routes and dwell",()=>{
  const places=[[0,0],[80,0],[160,0]];
  const early=[0,8,880,15,90,25,0,1,2,5,-7,"pre-pm"];
  assert.equal(shiftedShopping(early,872,places,220),null);
  const outward=shiftedShopping(early,873,places,220);
  assert.deepEqual([outward.start,outward.dur,outward.a,outward.b],[873,15,places[0],places[1]]);
  assert.equal(shiftedShopping(early,888,places,220).p,places[1]);
  const back=shiftedShopping(early,978,places,220);
  assert.deepEqual([back.start,back.dur,back.a,back.b],[978,25,places[1],places[2]]);
  assert.equal(shiftedShopping(early,1003,places,220).p,places[2]);
  assert.equal(shiftedShopping(early,1010,places,220),null);
  const late=early.with(10,7);
  assert.equal(shiftedShopping(late,880,places,220).p,places[0]);
  assert.equal(shiftedShopping(late,887,places,220).mode,"bike");
});
