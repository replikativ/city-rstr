import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import {entryDestination} from "../public/lab/entry.js";

const cityDir = new URL("https://example.test/city/");
const destination = suffix => entryDestination(new URL(suffix, cityDir));

test("the city entry preserves a shared explorer link with a saved camera", () => {
  const query = "?city=vancouver&release=abc&metric=case-2&minute=1020&camera=-123.1,49.28,13";
  const target = destination(query);
  assert.equal(target.pathname, "/city/explorer.html");
  assert.equal(target.search, query);
});

test("the retired Vancouver workbench preserves portable time and map settings", () => {
  const target = destination("?dayRun=abc&minute=1515&at=-123.1,49.28,135&metric=density#diary-zone-check");
  assert.equal(target.pathname, "/city/explorer.html");
  assert.deepEqual(Object.fromEntries(target.searchParams), {
    city: "vancouver", retired: "vancouver", minute: "75", camera: "-123.1,49.28,13", metric: "density"
  });
  assert.equal(target.hash, "");
});

test("legacy Vancouver entry pages open the regional map with a retirement notice", () => {
  for (const page of ["cityday.html", "population.html", "vancouver.html"]) {
    const html = readFileSync(new URL("../public/" + page, import.meta.url), "utf8");
    assert.match(html, /entryDestination\(location\)/);
    const target = destination(page + "?minute=480&marketRun=old&shop=123&metric=case-1&traveller=1%2F2&camera=invalid#market");
    assert.equal(target.pathname, "/city/explorer.html");
    assert.deepEqual(Object.fromEntries(target.searchParams), {
      city: "vancouver", retired: "vancouver", minute: "480"
    });
    assert.equal(target.hash, "");
  }
});

test("older Stuttgart links retain their scenario and evidence anchor", () => {
  const target = destination("?city=stuttgart&hour=8&scenario=shop#district-effects");
  assert.equal(target.pathname, "/city/lab.html");
  assert.equal(target.search, "?city=stuttgart&hour=8&scenario=shop&mode=city");
  assert.equal(target.hash, "#district-effects");
});
