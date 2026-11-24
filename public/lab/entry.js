const sharedKeys = new Set([
  "city", "minute", "release", "metric", "traveller", "people", "limit",
  "venue", "district", "basket", "camera", "retired"
]);
const legacyPages = new Set(["cityday.html", "population.html", "vancouver.html"]);
const portableMetrics = new Set(["none", "density", "presence", "arrivals", "departures"]);

function cameraOf(query) {
  for (const key of ["camera", "at"]) {
    const parts = query.get(key)?.split(",");
    if (parts?.length !== 3 || parts.some(part => !part.trim())) continue;
    const [lon, lat, extra] = parts.map(Number);
    if (Math.abs(lon) > 180 || Math.abs(lat) > 85 || ![lon, lat, extra].every(Number.isFinite)) continue;
    const zoom = key === "at" ? 13 : extra;
    if (zoom >= 0 && zoom <= 22) return [lon, lat, zoom].join(",");
  }
}

function regionalDestination(source) {
  const query = source.searchParams;
  const destination = new URL("explorer.html?city=vancouver&retired=vancouver", source);
  const minute = query.get("minute");
  if (minute?.trim() && Number.isFinite(Number(minute)) && Number(minute) >= 0 && Number(minute) < 1680) {
    destination.searchParams.set("minute", Math.floor(Number(minute)) % 1440);
  }
  const camera = cameraOf(query);
  if (camera) destination.searchParams.set("camera", camera);
  const metric = query.get("metric");
  if (portableMetrics.has(metric)) destination.searchParams.set("metric", metric);
  return destination;
}

export function entryDestination(location) {
  const source = new URL(location.href);
  const query = source.searchParams;
  const shared = !source.hash && [...query.keys()].every(key => sharedKeys.has(key));
  const vancouver = query.get("city") === "vancouver" || query.has("dayRun") ||
    query.get("coverage") === "region" || query.has("marketRun");

  if (legacyPages.has(source.pathname.split("/").at(-1)) || (!shared && vancouver)) {
    return regionalDestination(source);
  }

  const destination = new URL(shared ? "explorer.html" : "lab.html", source);
  destination.search = source.search;
  destination.hash = source.hash;
  if (!shared && !query.has("mode")) destination.searchParams.set("mode", "city");
  return destination;
}
