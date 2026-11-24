// Resolve a pinned release once at startup. Playback consumes the returned values.
export async function loadManifest(city, id, json) {
  if (!/^[a-f0-9]{64}$/.test(id)) throw Error("Invalid published weekday identifier.");
  const store = await import("../js/experiments/saved.js").catch(() => null);
  const cached = store && await store.releaseManifest(city, id).catch(() => null);
  if (cached?.release === id && cached.city === city) return cached;
  const run = await json("data/runs/" + id + ".json");
  if (run.release !== id || run.city !== city) throw Error("Published weekday identity mismatch.");
  // Private browsing and storage quota limits still permit network replay.
  if (store) await store.indexManifest(run).catch(() => null);
  return run;
}
