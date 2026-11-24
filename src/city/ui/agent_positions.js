// Per-agent last reached stop, indexed once when the user requests the roster.
export async function loadPositions(url, expected) {
  const response = await fetch(url);
  if (!response.ok) throw Error("The agent position file is unavailable.");
  const stream = response.body.pipeThrough(new DecompressionStream("gzip"));
  const view = new DataView(await new Response(stream).arrayBuffer());
  const count = view.getUint32(4);
  if (view.getUint32(0) !== 0x43524131 || count !== expected) throw Error("Agent roster mismatch.");
  const offsets = new Uint32Array(count + 1);
  let offset = 8;
  for (let i = 0; i < count; i++) {
    offsets[i] = offset;
    const length = view.getUint16(offset);
    if (!length || view.getUint16(offset + 2) !== 0) throw Error("Incomplete agent schedule.");
    offset += 2 + 10 * length;
  }
  offsets[count] = offset;
  if (offset !== view.byteLength) throw Error("Invalid agent position file.");
  return function frame(minute, requested) {
    const size = Math.min(requested, count);
    const positions = new Float32Array(2 * size);
    for (let i = 0; i < size; i++) {
      const id = Math.floor((i + 0.5) * count / size);
      let p = offsets[id] + 2;
      while (p + 10 < offsets[id + 1] && view.getUint16(p + 10) <= minute) p += 10;
      positions[2*i] = view.getInt32(p + 2) / 1e5;
      positions[2*i+1] = view.getInt32(p + 6) / 1e5;
    }
    return positions;
  };
}
