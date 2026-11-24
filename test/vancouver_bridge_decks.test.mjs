import test from "node:test";
import assert from "node:assert/strict";
import {BridgeDecks} from "../public/lab/bridge-decks.js";
import {streetBodies} from "../public/lab/street-player.js";

test("a bridge height follows the routed segment in either direction",()=>{
  const decks=new BridgeDecks({bridges:[{name:"Span",ways:[{way:17,vertices:[0,2],
    points:[[0,0,55],[40,0,58],[100,0,59]]}]}]});
  assert.deepEqual(decks.surface([40,0],[[0,0],[100,0]]),{name:"Span",height:58,heading:90});
  assert.deepEqual(decks.surface([70,0],[[100,0],[0,0]]),{name:"Span",height:58.5,heading:-90});
  assert.equal(decks.surface([40,0],[[40,-80],[40,80]]),null);
  assert.equal(decks.route([40,0],[[40,-80],[40,80]]),null);
  assert.equal(decks.route([40,0],[[0,0],[100,0],[130,20]]).height,58);
  assert.deepEqual(decks.sections([[-30,0],[0,0],[100,0],[130,20]]),{
    ground:[[[-30,0],[0,0]],[[100,0],[130,20]]],
    deck:[[[0,0,55],[40,0,58],[100,0,59]]]
  });
});

test("street bodies and their resident properties survive a bridge height offset",()=>{
  const [vehicle]=streetBodies([[30,30,{mode:2,heading:0,d:1,i:4,surfaceOffset:60}]]);
  assert.equal(vehicle.properties.base,60.15);
  assert.equal(vehicle.properties.height,61.05);
  assert.equal(vehicle.properties.i,4);
});
