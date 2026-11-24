import assert from "node:assert/strict";
import test from "node:test";
import {gzipSync} from "node:zlib";
import {loadPositions} from "../src/city/ui/agent_positions.js";

test("a sampled person keeps the same roster index when the clock crosses an arrival", async () => {
  const bytes=Buffer.alloc(8 + 2*2 + 3*10);
  bytes.writeUInt32BE(0x43524131);
  bytes.writeUInt32BE(2,4);
  let offset=8;
  for(const records of [[[0,9,48]], [[0,10,47],[65,11,49]]]){
    bytes.writeUInt16BE(records.length,offset); offset+=2;
    for(const [minute,lon,lat] of records){
      bytes.writeUInt16BE(minute,offset);
      bytes.writeInt32BE(lon*100000,offset+2);
      bytes.writeInt32BE(lat*100000,offset+6);
      offset+=10;
    }
  }
  const url="data:application/gzip;base64,"+gzipSync(bytes).toString("base64");
  const frame=await loadPositions(url,2);
  assert.deepEqual([...frame(64,2)],[9,48,10,47]);
  assert.deepEqual([...frame(65,200)],[9,48,11,49]);
  assert.deepEqual([...frame(64,1)],[10,47]);
  assert.deepEqual([...frame(65,1)],[11,49]);
  assert.equal(frame(65,0).length,0);
  await assert.rejects(loadPositions(url,3),/roster mismatch/);
});
