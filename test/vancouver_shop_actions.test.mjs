import assert from "node:assert/strict";
import { test } from "node:test";
import { chooseShops, readOpenings, referenceReplay } from "../public/lab/shop-actions.js";

const hours = () => ({
  withinReference: true,
  admits: (arrival, dwell) => arrival + dwell <= 1200,
  admitsAfterActivation: (at, arrival, dwell, inward) =>
    arrival - inward >= at && arrival + dwell <= 1200,
});

test("two shops share demand and leave purchases already en route in place", () => {
  const occasions = [
    [0, 1, 0, 725, 15, 1, 22, 0, 0, 0, 0, 15],
    [0, 2, 0, 740, 15, 1, 22, 0, 0, 0, 0, 15],
    [0, 3, 0, 740, 15, 1, 22, 0, 0, 0, 0, 15],
    [0, 4, 0, 1190, 15, 1, 22, 0, 0, 0, 0, 15],
  ];
  const sites = new Map([
    ["earlier", { changes: [[0, 15], [1, 15], [2, 15], [3, 15]] }],
    ["later", { changes: [[0, 5], [1, 5], [2, 15], [3, 5]] }],
  ]);
  const earlier = ["earlier", "full", 600];
  const later = ["later", "full", 720];
  const expected = new Map([
    [0, ["earlier", 15]],
    [1, ["later", 5]],
    [2, ["earlier", 15]],
  ]);
  assert.deepEqual(chooseShops(occasions, sites, [earlier, later], hours), expected);
  assert.deepEqual(chooseShops(occasions, sites, [later, earlier], hours), expected);
});

test("links for earlier single storefront replays still resolve to an action", () => {
  assert.deepEqual(
    readOpenings(new URLSearchParams("shop=3738&opened=720&hours=full")),
    [["3738", "full", 720]],
  );
});

test("activation uses the actual departure while opening hours use the fixed shopping slot", () => {
  const occasions=[[0,1,0,725,15,1,22,0,0,0,0,15]];
  const sites=new Map([["shop",{changes:[[0,15]]}]]);
  const action=["shop","full",708];
  assert.equal(chooseShops(occasions,sites,[action],hours).size,1);
  assert.equal(chooseShops(occasions,sites,[action],hours,[[720,748]]).size,0);
  assert.equal(chooseShops(occasions,sites,[["shop","full",705]],hours,[[720,748]]).size,1);
});

test("the existing-grocer replay retains the shopper and model while removing player actions", () => {
  const url = referenceReplay(
    "https://example.org/lab/cityday.html?shop=3738&shopPlay=1&opened=720&openings=%5B%5D&hours=short&" +
      "basket=20&street=walk&da=wrong&person=1&visit=4&minute=480&walks=diary&bikeRoutes=hills&terrain=on",
    { market: "release", da: "59150757", person: 94, minute: 1210, commute: "tracts" },
  );
  assert.equal(url.pathname, "/lab/cityday.html");
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    walks: "diary", bikeRoutes: "hills", terrain: "on", marketRun: "release", shop: "baseline",
    da: "59150757", person: "94", minute: "1210", follow: "1", commute: "tracts",
  });
});

test("an existing-grocer comparison retains the published combined day and external cohorts", () => {
  const url = referenceReplay(
    "https://example.org/cityday.html?dayRun=weekday&jointRun=joint&incomingTransit=inbound&" +
      "outboundRoad=driving&outboundTransit=transit&outboundClock=street&marketRun=old&outingsRun=unrelated&opened=720",
    { market: "market", da: "59150757", person: 94, minute: 1210, commute: "tracts" },
  );
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    jointRun: "joint", dayRun: "weekday", incomingTransit: "inbound", outboundRoad: "driving",
    outboundTransit: "transit", outboundClock: "street", marketRun: "market", shop: "baseline", da: "59150757",
    person: "94", minute: "1210", follow: "1", commute: "tracts",
  });
});
