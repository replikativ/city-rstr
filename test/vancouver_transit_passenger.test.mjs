import assert from "node:assert/strict";
import test from "node:test";
import {onwardRide,rideTiming} from "../scripts/transit-passenger.js";

test("a city rider walks from the alighting stop immediately and waits at the destination",()=>{
  const from=[60,0,"First stop"],to=[180,0,"Last stop"];
  const data={stations:[from,to],patterns:[{stops:[0,1]}],rides:[[0,28800,[0,600,2100,2110],"East"]]};
  const row=["DA",12,480,60,0,1,"bus",0,0,1,60,120];
  const timing=rideTiming(row,data,true);
  assert.deepEqual([timing.accessStart,timing.boardAt,timing.egressStart,timing.egress],[28800,29400,30900,120]);
  assert.equal(rideTiming(row,data).egressStart,32280);
});

test("a connecting ride uses the original destination and onward boarding details",()=>{
  const row=["DA",3,478,25,0,1,"first",0,0,1,0,100,["second",0,0,1,120,300,[[100,0],[150,0]]]];
  assert.deepEqual(onwardRide(row),["DA",3,478,25,0,1,"second",0,0,1,0,100]);
});
