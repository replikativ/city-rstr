import {loadRouteGeometry} from "./regional-transit.js";
import {rideTiming,ScheduledPassengers} from "./transit-passenger.js";

const el = id => document.getElementById(id);
const fmt = n => n.toLocaleString("en-CA");
const identity = (da, person) => da + "/" + person;
const versionPattern = /^[a-f0-9]{20}$/;
const versionKey = versions => [versions.atlas,versions.day,versions.streets].join("_");

async function flexClockID(root,versions) {
  const response = await fetch(root + "work-transit-flex/" + versionKey(versions) + ".json");
  if (response.status === 404) return null;
  if (!response.ok) throw Error("The flexible commute replay is unavailable.");
  const {version} = await response.json();
  if (!versionPattern.test(version)) throw Error("Invalid flexible commute release.");
  return version;
}

export async function loadWorkTransitClock(root,versions,requested,json) {
  if (requested !== "flex" && !versionPattern.test(requested ?? "")) return null;
  const version = requested === "flex" ? await flexClockID(root,versions) : requested;
  if (!version) return null;
  const {loadClock} = await import("../js/vancouver/departures.js");
  const clock = await loadClock(root,versions.atlas,versions.day,version,json);
  if (clock.kind !== "work-transit-flex" || clock.streets !== versions.streets ||
      !versionPattern.test(clock.workTransitRelease))
    throw Error("Flexible transit uses different simulation inputs.");
  return clock;
}

function indexRides(rows) {
  const result = new Map();
  for (const row of rows) {
    const key = identity(row[0],row[1]);
    if (!result.has(key)) result.set(key,[]);
    result.get(key).push(row);
  }
  return result;
}

export class PublishedRiders {
  constructor({report,sample,manifest,base,timetable,json,places,network,render,status}) {
    this.base = base;
    this.json = json;
    this.network = network;
    this.sample = indexRides(sample);
    this.areas = new Set(report.coverage.areas);
    this.residents = new Map();
    this.shards = new Map();
    this.retryAt = new Map();
    this.prefetch = new Set();
    this.frame = null;
    const refresh = () => {
      if (this.frame !== null) return;
      this.frame = requestAnimationFrame(() => {
        this.frame = null;
        render();
      });
    };
    this.refresh = refresh;
    const services = {manifest,routeData:id => loadRouteGeometry(json,timetable + id + ".json")};
    this.status = status;
    this.passengers = new ScheduledPassengers(services,places,refresh,error => {status.textContent = error.message;});
  }

  addExample(label,row,examples,steps,follow) {
    const status=this.status;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.onclick = async () => {
      try {
        await Promise.all([this.loadResident(row[0]),...this.routes(row).map(id => this.passengers.routeData(id))]);
        const first = rideTiming(row,this.passengers.routes.get(row[6]),true);
        const transfer = row[12];
        const final = transfer
          ? rideTiming([...row.slice(0,6),...transfer.slice(0,4),0,row[11]],this.passengers.routes.get(transfer[0]),true)
          : first;
        const breakpoints = [[first.access ? "Walk to the stop" : "Start",row[2]],
          ["Board",(first.boardAt + 0.5)/60]];
        if (transfer) {
          breakpoints.push(["Transfer",(first.alightAt + (transfer[4] ? transfer[4]/2 : 0.5))/60],
            ["Board again",(final.boardAt + 0.5)/60]);
        }
        if (final.egress) {
          breakpoints.push(["Walk from the stop",(final.alightAt + 0.5)/60]);
        }
        breakpoints.push(["Next activity",row[2]+row[3]]);
        steps.replaceChildren();
        for (const [name,minute] of breakpoints) {
          const step = document.createElement("button");
          step.type = "button";
          step.textContent = name;
          step.onclick = () => follow(row[0],row[1],minute).catch(error => {status.textContent = error.message;});
          steps.append(step);
        }
        await follow(row[0],row[1],row[2]);
      } catch (error) {
        status.textContent = error.message;
      }
    };
    examples.append(button);
  }

  routes(row) {
    return row[12] ? [row[6],row[12][0]] : [row[6]];
  }

  loadResident(da, refresh = true) {
    if (!this.areas.has(da)) return Promise.resolve();
    if (!this.shards.has(da)) {
      this.shards.set(da,this.json(this.base + da + ".json").then(rows => {
        for (const [key,value] of indexRides(rows)) this.residents.set(key,value);
        if (refresh) this.refresh();
      }).catch(error => {
        this.shards.delete(da);
        throw error;
      }));
    }
    return this.shards.get(da);
  }

  loadRoute(id,selected) {
    if (this.prefetch.has(id) || (!selected && this.prefetch.size >= 4) || Date.now() < (this.retryAt.get(id) ?? 0)) return;
    this.prefetch.add(id);
    this.passengers.routeData(id).catch(() => {
      this.retryAt.set(id,Date.now() + 3000);
    }).finally(() => this.prefetch.delete(id));
  }

  passenger(da, person, minute, graph, selected = false) {
    const key = identity(da,person);
    const rows = (selected && this.residents.get(key)) || this.sample.get(key);
    const row = rows?.find(r => r[2] <= minute && minute < r[2] + r[3]);
    if (!row) return null;
    const routes = this.routes(row).filter(id => !this.passengers.routes.has(id));
    if (routes.length) {
      for (const route of routes) this.loadRoute(route,selected);
      return {p:null,description:"Loading the scheduled trip"};
    }
    const trip = row[12] ? this.passengers.transferPosition(row,minute,graph)
      : this.passengers.position(row,minute,graph,true);
    if (trip && !trip.routed && trip.description.startsWith("Walking ")) {
      if (!graph && !this.streetRequest) {
        this.streetRequest = this.network().then(this.refresh).catch(error => {
          this.status.textContent = error.message;
          this.streetRequest = null;
        });
      }
      return {p:null,description:graph ? "Street walk unresolved" : "Finding the street walk"};
    }
    return trip;
  }
}
export class WorkTransit extends PublishedRiders {
  constructor(config) {
    const {report,follow}=config;
    const status=el("work-transit-status");
    super({...config,status});
    this.reservedOutingVersion = report.sharedOutings?.version;
    status.textContent = fmt(report.coverage.trips) + " of " + fmt(report.eligible) +
      " eligible trips fit the " + report.serviceDate + " timetable. " +
      fmt(report.outcomes.towardWork ?? 0) + " go to work, " +
      fmt(report.outcomes.fromWork ?? 0) + " leave work, and " +
      fmt(report.outcomes.transfer ?? 0) + " change vehicles.";
    if (report.flex) {
      el("work-transit-flex").textContent = fmt(report.flex.added) +
        " more trips fit by using adjacent flexible home time. Each adds up to " +
        report.flex.maxExtension + " minutes of travel.";
      el("work-transit-flex").hidden = false;
    }
    el("work-transit-misses").textContent =
      fmt(report.outcomes.access ?? 0) + " lack reachable stops, " +
      fmt(report.outcomes.schedule ?? 0) + " lack service within the diary window, and " +
      fmt(report.outcomes.capacity ?? 0) + " could not get modeled bus space. " +
      fmt(report.outcomes.sameCoordinates ?? 0) + " start and end at the same coordinates.";
    el("work-transit-load").textContent = fmt(report.bus.atLimit) + " of " + fmt(report.bus.compared) +
      " assigned bus runs reach their modeled limit on at least one segment." +
      (report.sharedOutings ? " The published outings share this capacity budget." : "");
    el("work-transit-gtfs").href = report.gtfsSource;
    el("work-transit-capacity").href = report.bus.source;
    const examples = el("work-transit-examples");
    const steps = el("work-transit-steps");
    for (const [kind,label] of [["flex","Follow a longer return"],["direct","Follow a direct trip"],
                               ["transfer","Follow a transfer"],["return","Follow a return from work"]]) {
      const row = report.examples[kind];
      if (row) this.addExample(label,row,examples,steps,follow);
    }
  }

  compareOutings(outings) {
    const version = outings?.active && outings.report.transit ? outings.version : null;
    if (version === this.activeOutingVersion) return;
    this.activeOutingVersion = version;
    const note = el("work-transit-outings");
    note.hidden = !version || version === this.reservedOutingVersion;
    if (!note.hidden) note.textContent = "This archived outing release uses a separate bus capacity estimate.";
  }

}

export async function loadPassengerData(root,base,report,json) {
  const timetable = root + "transit/" + report.versions.transit + "/";
  const [sample,manifest] = await Promise.all([json(base + "sample.json"),json(timetable + "transit.json")]);
  if (manifest.date !== report.serviceDate) throw Error("The passenger trips use a different service day.");
  return {sample,manifest,timetable};
}

export async function attachWorkTransit(root,versions,json,places,network,render,follow,flex) {
  const folder = root + "work-transit/";
  const params = new URL(location.href).searchParams;
  const fixed = /^recorded-([a-f0-9]{20})$/.exec(params.get("workTransit") ?? "");
  let version = flex?.workTransitRelease ?? fixed?.[1];
  if (!version) {
    const pointer = await fetch(folder + versionKey(versions) + ".json");
    if (pointer.status === 404) return null;
    if (!pointer.ok) throw Error("The workplace transit replay is unavailable.");
    ({version} = await pointer.json());
  }
  if (!versionPattern.test(version)) throw Error("Invalid workplace transit release.");
  const base = folder + version + "/";
  const report = await json(base + "report.json");
  if (Object.keys(versions).some(k => report.versions[k] !== versions[k]) ||
      !versionPattern.test(report.versions.transit) ||
      (flex && flex.transit !== report.versions.transit) ||
      Boolean(report.flex) !== Boolean(flex))
    throw Error("Workplace transit uses a different weekday.");
  const service = await loadPassengerData(root,base,report,json);
  const rides = new WorkTransit({report,...service,base,json,places,network,render,follow});
  rides.version = version;
  rides.timetableVersion = report.versions.transit;
  const panel = el("work-transit");
  panel.hidden = false;
  if (params.has("workTransit")) panel.open = true;
  if (flex || await flexClockID(root,versions)) {
    const link = el("work-transit-switch");
    const updateLink = () => {
      const url = new URL(location.href);
      url.searchParams.set("workTransit",flex ? "recorded-" + report.flex.baselineRelease : "flex");
      link.href = url;
    };
    updateLink();
    link.onpointerenter = updateLink;
    link.onclick = updateLink;
    link.textContent = flex ? "Replay the recorded travel windows" : "Allow flexible time at home";
    link.hidden = false;
  }
  return rides;
}
