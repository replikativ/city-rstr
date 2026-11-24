import test from "node:test";
import assert from "node:assert/strict";
import {BIKE} from "../scripts/vancouver-network.js";
import {activeStreetLeg} from "../scripts/street-pedestrians.js";

test("a reassigned commute uses its scenario mode and workplace",()=>{
  const trip=[480,20,"transit",0,1],work={overrides:new Map([[1,19]]),replaceMode:"bike"};
  assert.deepEqual(activeStreetLeg(work,trip,10,11,true,{Bicycle:220}),[10,19,220,BIKE]);
  assert.equal(activeStreetLeg(null,trip,10,11,true),null);
  assert.equal(activeStreetLeg({external:true,assignedMode:"bike"},trip,10,11,true),null);
});
