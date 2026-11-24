// Resolve one batch of journeys against the archived Vancouver route cache and graph.
// The JVM caller owns the roster, clock, ordering, and release layout.
import {once} from "node:events";
import {readFileSync} from "node:fs";
import {join} from "node:path";
import {Network, lngLat, roadMode, CAR, BIKE} from "./vancouver-network.js";
import {findRoute, routeKey} from "./weekday-pathfinder.js";
import {bicycleMetresPerMinute} from "./street-pedestrians.js";

const [cache, network, driveProfile] = process.argv.slice(2);
const read = path => JSON.parse(readFileSync(path));
const jobs = read(0);
let graph, cachedHour, routes;
for (const [i, [hour, recordedMode, from, to, start, duration, incoming]] of jobs.entries()) {
  const mode = roadMode(recordedMode);
  if (!mode) continue;
  const speed = mode === CAR ? 380 : mode === BIKE ? bicycleMetresPerMinute : 150;
  let route;
  if (incoming) {
    graph ??= new Network(read(network), null, read(driveProfile));
    route = findRoute(graph, mode, from, to, duration, speed, false, start);
  } else {
    if (hour !== cachedHour) {
      routes = new Map(read(join(cache, hour + ".json")));
      cachedHour = hour;
    }
    route = routes.get(routeKey(mode, from, to, duration, speed, false));
  }
  if (route?.minutes) {
    const path = route.path.map(point => lngLat(point).map(x => +x.toFixed(6)));
    const line = JSON.stringify([i, path, route.offsets, route.minutes]) + "\n";
    if (!process.stdout.write(line)) await once(process.stdout, "drain");
  }
}
