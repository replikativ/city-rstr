// Resolve resident driver legs against the same workplace rules as the browser.
import { readFileSync, writeSync } from "node:fs";
import { join } from "node:path";

const root = process.argv[2], versions = JSON.parse(readFileSync(0));
const detail = process.argv[3] === "--templates";
const fitted = process.argv[3] === "--fitted";
const read = name => JSON.parse(readFileSync(join(root, name)));
const atlasRoot = "atlas/" + versions.atlas + "/";
const dayRoot = "cityday/" + versions.day + "/";
const population = read(atlasRoot + "atlas.json"), day = read(dayRoot + "day.json");
let work, paid, expectedChanges = 0;
const riding = new Set();
if (versions.outbound) {
  const { residentTrips } = await import("../public/js/vancouver/workplaces.js");
  const outboundRoot = "outbound/" + versions.outbound + "/";
  const outbound = read(outboundRoot + "report.json");
  const worksites = read("worksites/" + versions.worksites + "/worksites.json");
  const tracts = read("tract-workplaces/" + versions.tracts + "/worksites.json");
  if ([outbound, worksites, tracts].some(r => r.atlas !== versions.atlas || r.day !== versions.day) ||
      tracts.worksites !== versions.worksites || worksites.outbound !== versions.outbound ||
      worksites.streets !== versions.streets)
    throw Error("Bridge replay and travel model releases differ");
  work = residentTrips(outbound, read(outboundRoot + "assignments.json"),
                       read(outboundRoot + "local-modes.json"), worksites, tracts, () => "tracts");
  if (fitted) paid = outbound.slots.map(slots => new Set(slots));
  else {
    const tourRoot = "cycle-tours/" + versions.tours + "/", tours = read(tourRoot + "report.json");
    if (["atlas","day","streets"].some(k => tours.versions[k] !== versions[k]))
      throw Error("Bridge replay and cycling releases differ");
    expectedChanges = tours.zones[0].accessLegs;
    for (const [da,index,,,,legs,access] of read(tourRoot + "tours.json"))
      if (access) for (const [start] of legs) riding.add(da + "/" + index + "/" + start);
  }
}
if (fitted && !work) throw Error("The fitted drives need the published workplace rules");

const driverParts = day.templates.map((tpl,k) => tpl.parts
  .filter(p => p[2] !== "stop").map(part => {
    const [start,duration,mode] = part;
    const driver = mode === "car-driver" && population.templates[k].episodes
      .filter(([s]) => start <= s && s < start + duration)
      .every(([, , ,m]) => m === "car-driver");
    return [part,driver];
  }));

let residents = 0, changes = 0;
for (const [d,da] of day.das.entries()) {
  const {people} = read(atlasRoot + da + ".json"), {plans} = read(dayRoot + da + ".json");
  if (plans.length !== people.length) throw Error("Incomplete resident plans at " + da);
  residents += people.length;
  const lines = [];
  for (const [i,person] of people.entries()) {
    const tpl = person[7], plan = plans[i];
    for (const [part,driver] of driverParts[tpl]) {
      const [start,duration,,a,b] = part;
      const from = plan[a] ?? -1, to = plan[b] ?? -1;
      if (!work) {
        if (driver) {
          const fields = [1,from,to,start,duration,d,i];
          if (detail) fields.push(tpl);
          lines.push(fields.join(","));
        }
        continue;
      }
      const path = work(d,i,tpl,part);
      const fittedDriver = (path?.replaceMode ?? path?.assignedMode) === "car-driver" ||
        (driver && !path?.replaceMode && !path?.assignedMode);
      if (!driver && !fittedDriver) continue;
      const origin = path?.external ? -1 : path?.overrides?.get(a) ?? from;
      const destination = path?.external ? -1 : path?.overrides?.get(b) ?? to;
      if (fitted) {
        if (fittedDriver) {
          const purpose = paid[tpl].has(a) || paid[tpl].has(b) ? 1 : 2;
          lines.push([purpose,origin,destination,start,duration,d,i,Number(!!path?.external)].join(","));
        }
        continue;
      }
      const ride = riding.has(d + "/" + i + "/" + start);
      if (ride) {
        if (!driver || !fittedDriver || path) throw Error("The two interventions affect the same driver leg");
        changes++;
      }
      const adjusted = fittedDriver ? 2 | (ride ? 0 : 4) : 0;
      if (driver && fittedDriver && origin === from && destination === to)
        lines.push([1 | adjusted,from,to,start,duration,d,i].join(","));
      else {
        if (driver) lines.push([1,from,to,start,duration,d,i].join(","));
        if (fittedDriver) lines.push([adjusted,origin,destination,start,duration,d,i].join(","));
      }
    }
  }
  if (lines.length) writeSync(1, lines.join("\n") + "\n");
}
if (residents !== day.population || changes !== expectedChanges)
  throw Error("Driver legs omit residents or feasible bicycle switches");
