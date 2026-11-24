import assert from "node:assert/strict";
import test from "node:test";
import {activeWalks,onwardRide,rideTiming,ScheduledPassengers} from "../public/lab/transit-passenger.js";

test("walking intervals are start-inclusive and end-exclusive even for simultaneous riders",()=>{
  const rows=[[100,60],[120,10],[120,40],[160,5]];
  assert.deepEqual(activeWalks(rows,119,60),[rows[0]]);
  assert.deepEqual(activeWalks(rows,120,60),rows.slice(0,3));
  assert.deepEqual(activeWalks(rows,130,60),[rows[0],rows[2]]);
  assert.deepEqual(activeWalks(rows,160,60),[rows[3]]);
  assert.deepEqual(activeWalks(rows,165,60),[]);
});

test("a city rider walks from the alighting stop immediately and waits at the destination",()=>{
  const from=[60,0,"First stop"],to=[180,0,"Last stop"];
  const data={stations:[from,to],patterns:[{stops:[0,1]}],rides:[[0,28800,[0,600,2100,2110],"East"]]};
  const row=["DA",12,480,60,0,1,"bus",0,0,1,60,120];
  const timing=rideTiming(row,data,true);
  assert.deepEqual([timing.accessStart,timing.boardAt,timing.egressStart,timing.egress],[28800,29400,30900,120]);
  const replay=new ScheduledPassengers({},[[0,0],[300,0]],()=>{},()=>{});
  replay.routes.set("bus",data);
  const graph={route:(a,b)=>[a,b]};
  assert.deepEqual(replay.position(row,480.5,graph,true).p,[30,0]);
  assert.equal(replay.position(row,481,graph,true).description,"Waiting at First stop");
  assert.deepEqual(replay.position(row,516,graph,true).p,[240,0]);
  assert.equal(replay.position(row,517,graph,true).description,"Arrived · waiting for the next diary activity");
  assert.equal(replay.position(row,516,graph,false).description,"Waiting at Last stop");
  assert.deepEqual(replay.position(row,539,graph,false).p,[240,0]);
});

test("a rider walks and waits at the stop before boarding the connecting vehicle",()=>{
  const shape=(a,b)=>({stops:[0,1],mapped:true,line:[a,b],dist:[0,100],axis:[0,100]});
  const a=[0,0], b=[100,0], c=[150,0], d=[250,0];
  const data=(stations,pattern,start,end)=>({stations,patterns:[pattern],rides:[[0,start,[0,0,end,end],"East"]]});
  const replay=new ScheduledPassengers({},[[0,0],[300,0]],()=>{},()=>{});
  replay.routes.set("first",data([[...a,"Home"],[...b,"First stop"]],shape(a,b),28800,300));
  replay.routes.set("second",data([[...c,"Connection"],[...d,"Last stop"]],shape(c,d),29460,300));
  const path=[b,[125,25],c], row=["DA",3,478,25,0,1,"first",0,0,1,0,100,["second",0,0,1,120,300,path]];
  assert.deepEqual(onwardRide(row),["DA",3,478,25,0,1,"second",0,0,1,0,100]);
  const r=minute=>replay.transferPosition(row,minute,null);
  assert.match(r(482).description,/Home → First stop/);
  assert.deepEqual(r(486).p,[125,25]);
  assert.equal(r(486).description,"Walking to transfer at Connection");
  assert.equal(r(487).description,"Waiting to transfer at Connection");
  assert.match(r(491).description,/Connection → Last stop/);
  assert.equal(r(498).description,"Arrived · waiting for the next diary activity");
  const e=[310,0],f=[410,0];
  replay.routes.set("third",data([[...e,"Second connection"],[...f,"End"]],shape(e,f),30120,300));
  row[12].push(["third",0,0,1,90,180,[d,[280,20],e]]);
  assert.match(r(491).description,/Connection → Last stop/);
  assert.deepEqual(r(496.75).p,[280,20]);
  assert.equal(r(498).description,"Waiting to transfer at Second connection");
  assert.match(r(503).description,/Second connection → End/);
});
