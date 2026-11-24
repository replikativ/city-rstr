import {rideTiming,ScheduledPassengers} from "./transit-passenger.js";

const el = id => document.getElementById(id);
const fmt = n => n.toLocaleString("en-CA");

export async function commuteClockLink(base, atlas, day) {
  const response = await fetch(base + "transit-commutes/" + atlas + "_" + day + ".json");
  if (response.status === 404) return null;
  if (!response.ok) throw Error("The transit commute replay is unavailable.");
  const {version} = await response.json();
  if (!/^[a-f0-9]{20}$/.test(version)) throw Error("Invalid transit commute replay.");
  return "cityday.html?coverage=region&clock=" + version + "&scheduled=1";
}

export class TransitCommutes {
  constructor(report, rides, services, places, render, follow, clock) {
    let frame;
    const refresh = () => {
      if (!frame) frame = requestAnimationFrame(() => { frame = null; render(); });
    };
    this.passengers = new ScheduledPassengers(services,places,refresh,() => {});
    this.rides = new Map(rides.map(row => [row[0] + "/" + row[1],row]));
    this.loading = new Set();
    this.retryAt = new Map();
    const panel = el("transit-commutes");
    const overall = report.areas["Regional residents"];
    const transfers = Number.isInteger(overall.transferTrips);
    const capacity = report.busCapacity;
    this.busLimits = capacity?.limits;
    this.busRiders = new Map();
    if (this.busLimits) {
      for (const row of rides) {
        const legs = [row.slice(6,10)];
        if (row[12]) legs.push(row[12].slice(0,4));
        for (const [route,run,board,alight] of legs) {
          if (!(route in this.busLimits)) continue;
          const key = route + "/" + run;
          if (!this.busRiders.has(key)) this.busRiders.set(key,[]);
          this.busRiders.get(key).push([board,alight]);
        }
      }
    }
    el("transit-commutes-status").textContent = fmt(overall.changed) + " of " + fmt(overall.eligible) +
      " eligible home-to-work transit trips fit a later departure on the " + report.timetable + " timetable." +
      (capacity ? " Without bus limits, " + fmt(overall.withoutCapacityChanged) + " can leave later." :
        transfers ? " Single-vehicle routes retime " + fmt(overall.directChanged) + " of those trips." : "");
    el("transit-commutes-transfer-column").hidden = !transfers;
    el("transit-commutes-transfer-method").hidden = !transfers;
    const bus = report.busLoadEvidence;
    if (bus?.highest) {
      const peak = bus.highest;
      el("transit-commutes-bus-load").hidden = false;
      el("transit-commutes-bus-number").textContent = capacity ?
        fmt(bus.atLimit) + " of " + fmt(bus.compared) + " assigned bus runs reach their limit. " +
        fmt(overall.foundAlternative) + " commuters switch to another suitable itinerary and " +
        fmt(overall.noLaterWithCapacity) + " keep their original commute times after a bus fills." :
        fmt(bus.above) + " of " + fmt(bus.compared) + " compared bus runs exceed the route-level capacity estimate " +
        "using timed commuters alone. Route " + peak.route + " reaches " + fmt(peak.riders) +
        " model riders on one segment, against about " + fmt(peak.capacityProxy) + " spaces.";
      el("transit-commutes-bus-source").href = bus.source;
    }
    if (capacity) {
      const method = el("transit-commutes-capacity-method");
      const fallbackRoutes = Object.values(capacity.basis).filter(basis => basis === "fallback").length;
      method.textContent = "Bus limits use fall or full-year 2025 route data. " +
        fmt(fallbackRoutes) + " routes use a " + fmt(capacity.fallback) + "-space estimate. " +
        "The replay makes those spaces available to the revised commuters.";
      method.hidden = false;
    }
    const link = el("transit-commutes-link");
    link.href = "cityday.html?coverage=region" + (report.workplaceRun ? "&workplaceRun=" + report.workplaceRun : "");
    link.textContent = "Replay the original commute times";
    const body = el("transit-commutes-areas");
    for (const [area,row] of Object.entries(report.areas).sort(([a],[b]) => a.localeCompare(b))) {
      const tr = body.insertRow();
      tr.insertCell().textContent = area;
      tr.insertCell().textContent = fmt(row.changed) + " of " + fmt(row.eligible);
      if (transfers) tr.insertCell().textContent = fmt(row.transferTrips);
      tr.insertCell().textContent = fmt(row.longBefore) + " → " + fmt(row.longAfter);
    }
    const ex = report.example, button = el("transit-commutes-follow");
    const exampleLabel = ex.capacityRerouted ? "a rerouted commuter" : ex.ride[12] ? "a transfer trip" : "a worker";
    button.textContent = "Follow " + exampleLabel + " leaving at " +
      clock(ex.after) + " (original " + clock(ex.before) + ")";
    button.onclick = async () => {
      try {
        const row = ex.ride;
        await services.init();
        const data = await this.passengers.routeData(row[6]);
        if (row[12]) await this.passengers.routeData(row[12][0]);
        await services.select(row[6]);
        const {boardAt,alightAt} = rideTiming(row,data,true);
        const minute = row[12] ? Math.max(boardAt,alightAt-60)/60 : (boardAt+alightAt)/120;
        await follow(ex.da,ex.person,minute);
      } catch (error) {
        el("transit-commutes-status").textContent = error.message;
      }
    };
    panel.hidden = false;
    panel.open = true;
    el("transit-commutes-results").hidden = false;
  }

  passenger(da, person, minute, network) {
    const row = this.rides.get(da + "/" + person);
    if (!row || minute < row[2] || minute >= row[2] + row[3]) return null;
    const transfer = row[12];
    const routes = transfer ? [row[6],transfer[0]] : [row[6]];
    const missing = routes.filter(route => !this.passengers.routes.has(route));
    if (!missing.length)
      return transfer ? this.passengers.transferPosition(row,minute,network) :
        this.passengers.position(row,minute,network,true);
    for (const route of missing) this.loadRoute(route);
    return null;
  }

  busOccupancy(passenger, minute) {
    if (!passenger?.vehicle || !this.busLimits) return "";
    const [route,run] = passenger.vehicle, limit = this.busLimits[route];
    if (!limit) return "";
    const [,start,times] = this.passengers.routes.get(route).rides[run];
    const seconds = minute*60-start;
    const aboard = this.busRiders.get(route + "/" + run)
      .filter(([board,alight]) => times[2*board+1] <= seconds && seconds < times[2*alight]).length;
    return " · " + fmt(aboard) + " of " + fmt(limit) + " modeled commuter spaces";
  }

  loadRoute(route) {
    if (this.loading.size < 3 && !this.loading.has(route) && Date.now() >= (this.retryAt.get(route) ?? 0)) {
      this.loading.add(route);
      this.passengers.routeData(route).catch(() => this.retryAt.set(route,Date.now() + 3000))
        .finally(() => this.loading.delete(route));
    }
  }
}
