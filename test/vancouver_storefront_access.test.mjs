import test from "node:test";
import assert from "node:assert/strict";
import {CAR,Network,WALK} from "../public/lab/vancouver-network.js";
import {addressStreets,atStorefront,StorefrontAccess} from "../public/lab/storefront-access.js";

test("uses the addressed street even when another street is closer to the parcel",()=>{
  const graph=new Network({nodes:[[0,0],[0,100],[14,0],[14,100]],names:["East Hastings Street","Pender Lane"],
    ways:[[7,0,[0,1]],[7,1,[2,3]]]});
  const site={id:"17",name:"2693 E HASTINGS ST",point:[12,30]};
  const index=new StorefrontAccess([site]);
  assert.deepEqual(index.locate(site,graph).p,[0,30]);
  assert.equal(index.locate(site,graph,CAR).edge.name,"East Hastings Street");
  assert.equal(index.locate({...site,id:"not-in-catalogue"},graph),null);
  assert.deepEqual([...addressStreets("102-5701 GRANVILLE ST / 250 W 12TH AVE")],["granville st","w 12th av"]);
});

test("the opening interaction respects nearby connections and excludes a disconnected street",()=>{
  const graph=new Network({nodes:[[0,0],[10,0],[20,0],[30,0],[17,-8],[17,8]],names:["Kingsway","Flyover"],
    ways:[[7,0,[0,1,2,3]],[7,1,[4,5]]]});
  const site={id:"4",name:"2541 Kingsway",point:[23,2]},index=new StorefrontAccess([site]);
  const access=index.locate(site,graph,WALK);
  assert.equal(atStorefront(graph.streetStart([1,0],WALK,90),access),true);
  assert.equal(atStorefront(graph.streetStart([17,2],WALK,0),access),false);
  assert.equal(atStorefront(graph.streetStart([23,0],WALK,90),access),true);
  assert.equal(atStorefront(graph.streetStart([1,0],WALK,90),access,20),false);
});
