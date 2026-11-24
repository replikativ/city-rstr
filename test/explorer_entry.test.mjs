import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import {runInNewContext} from "node:vm";

const html = readFileSync(new URL("../public/index.html", import.meta.url), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function destination(suffix) {
  const location = new URL("http://localhost/city/" + suffix);
  let target;
  location.replace = href => { target = new URL(href); };
  runInNewContext(script, {location, URL, URLSearchParams, document: {getElementById: () => ({})}});
  return target;
}

test("the city entry preserves a shared explorer link with a saved camera", () => {
  const query = "?city=vancouver&release=abc&metric=case-2&minute=1020&camera=-123.1,49.28,13";
  const target = destination(query);
  assert.equal(target.pathname, "/city/explorer.html");
  assert.equal(target.search, query);
});

test("the city entry still opens historical views at their original anchors", () => {
  const target = destination("?dayRun=abc#diary-zone-check");
  assert.equal(target.pathname, "/city/cityday.html");
  assert.equal(target.hash, "#diary-zone-check");
});
