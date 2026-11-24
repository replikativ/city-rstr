import {distance} from "./vancouver-network.js";
import {track} from "../js/vancouver/route-timeline.js";

const el = id => document.getElementById(id);
const fmt = n => n.toLocaleString("en-CA");
const key = (d,i) => d + "/" + i;

function index(rows) {
  const result = new Map();
  for (const row of rows) {
    const resident = key(row[0],row[1]);
    if (!result.has(resident)) result.set(resident,[]);
    result.get(resident).push(row);
  }
  return result;
}

class RecreationLoops {
  constructor(report,version,base,day,sample,json,follow,render,active) {
    Object.assign(this,{report,version,base,day,json,follow,render,active});
    this.mode = report.mode ?? "walk";
    this.sample = index(sample);
    this.records = new Map();
    this.areas = new Set(report.areas);
    this.loading = new Map();
    this.offsets = new WeakMap();
    this.feedback = el("recreation-status");
    const totals = {recorded:0,recordedRouted:0,added:0,target:0};
    for (const [name,counts] of Object.entries(report.outcomes)) {
      const row = el("recreation-rows").insertRow();
      row.insertCell().textContent = name;
      for (const k of Object.keys(totals)) {
        const cell = row.insertCell();
        cell.textContent = fmt(counts[k]);
        totals[k] += counts[k];
      }
    }
    this.totals = totals;
    this.residentCount = Object.values(report.residents).reduce((a,b)=>a+b,0);
    el("recreation-survey").href = report.survey.source;
    el("recreation-donors").href = report.donor.source;
    if (this.mode === "bike") this.bicycleEvidence();
    else el("recreation-reference-rate").textContent = Math.round(100 * report.survey.loopShare) +
        "% of North Shore trips start and end at home for recreation. This scenario applies the " +
        Math.round(100 * report.survey.walkShare) + "% walking share of all recreation trips to those loops.";
    el("recreation-routing").textContent = fmt(report.kinds.circuit ?? 0) + " circuits and " +
      fmt(report.kinds["out-and-back"] ?? 0) + " out-and-back trips. " +
      fmt(report.donor.respondents) + " time-use respondents supply " +
      (this.mode === "bike" ? "outdoor-sports" : "outdoor exercise") + " times.";
    const toggle = el("recreation-replay");
    toggle.checked = active;
    toggle.onchange = () => this.enable(toggle.checked);
    const trip = this.mode === "bike" ? "ride" : "walk";
    for (const [kind,phrase] of [["recorded","a recorded"],["added","an added"]]) {
      const row = report.examples[kind];
      if (!row) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Follow " + phrase + " " + trip;
      button.onclick = () => this.choose(row).catch(e=>this.error(e));
      el("recreation-examples").append(button);
    }
    this.describe();
  }

  bicycleEvidence() {
    const {survey, crossings, donor} = this.report;
    el("recreation-title").textContent = "Recreational bike rides from home";
    el("recreation-toggle-text").textContent = "Add recreational bike rides";
    el("recreation-caption").textContent = "Home-to-home rides by Vancouver neighbourhood";
    el("recreation-home-heading").textContent = "Home neighbourhood";
    el("recreation-survey").textContent = "Vancouver travel survey, Figure 46";
    const source = el("recreation-loop-source");
    source.hidden = false;
    source.href = survey.loopSource;
    el("recreation-reference-rate").textContent = Math.round(100 * survey.cyclingShare) + "% of Vancouver's " +
      fmt(survey.recreationTrips) + " weekday recreation trips used a bicycle. This scenario transfers the " +
      (100 * survey.loopShare).toFixed(1) + "% home-to-home share of recreation trips from the North Shore survey. " +
      "Outdoor-sports diaries supply times for the added rides. Routes favour mapped greenways.";
    if (donor.hours) {
      el("recreation-departures").hidden = false;
      const table = el("recreation-departure-rows");
      for (const [hour,target,fitted] of donor.hours) {
        const row = table.insertRow();
        row.insertCell().textContent = String(hour % 24).padStart(2,"0") + ":00";
        row.insertCell().textContent = fmt(target);
        row.insertCell().textContent = fmt(fitted);
      }
    }
    el("recreation-bike-counters").hidden = false;
    for (const site of Object.values(crossings)) {
      const row = el("recreation-crossings").insertRow();
      const link = document.createElement("a");
      link.href = site.source;
      link.textContent = site.name;
      row.insertCell().append(link, " (" + site.year + ")");
      row.insertCell().textContent = fmt(site.observed);
      const added = row.insertCell();
      if (!site.example) { added.textContent = fmt(site.added); continue; }
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = fmt(site.added);
      button.setAttribute("aria-label", "Follow a rider at " + site.name);
      button.onclick = async () => {
        try {
          const [d,i,minute] = site.example;
          await this.loadResident(this.day.das[d]);
          const record = this.records.get(key(d,i))?.find(r => r[5] && r[3] <= minute && minute < r[3] + r[4]);
          if (!record) throw Error("The counter's ride is unavailable.");
          await this.choose(record,minute);
        } catch (e) { this.error(e); }
      };
      added.append(button);
    }
  }

  describe() {
    const {recorded,recordedRouted,added} = this.totals;
    if (this.mode === "bike") {
      this.feedback.textContent = fmt(added) + " home-to-home bike rides fit the weekday.";
      el("recreation-rate").textContent = fmt(this.residentCount) + " residents aged 20 or older, " +
        fmt(this.report.survey.target) + " rides in the scenario target. The street table compares added passages " +
        "in one weekday with City summer averages across all travellers.";
      return;
    }
    this.feedback.textContent = fmt(recordedRouted) + " of " + fmt(recorded) +
      " recorded home-to-home walks on mapped paths" +
      (this.active && !this.differentLayers ? " · " + fmt(added) + " added recreational walks." : ".");
    const {recordedTrips,observedTripsPerResident} = this.report.weekday;
    const trips = recordedTrips + (this.outingTrips ?? 0) + (this.shortWalks ?? 0) + (this.escortTrips ?? 0) +
      (this.active && !this.differentLayers ? added : 0);
    el("recreation-rate").textContent = (trips / this.residentCount).toFixed(2) +
      " daily trips per North Shore resident aged 15+ with the selected layers · " +
      observedTripsPerResident.toFixed(2) + " in the 2025 survey.";
  }

  error(error) {
    this.feedback.textContent = error.message;
  }

  enable(active) {
    this.active = active;
    el("recreation-replay").checked = active;
    const url = new URL(location.href);
    url.searchParams.delete("recreation");
    if (active) url.searchParams.set("recreationRun",this.version);
    else url.searchParams.delete("recreationRun");
    history.replaceState(null,"",url);
    if (!active && this.example?.[5]) el("recreation-stages").replaceChildren();
    this.describe();
    this.render();
  }

  checkLayers(outings,flex,shortWalks,escortTrips) {
    if (this.mode === "bike") return;
    const differs = !!((outings?.active && outings.version !== this.report.shared.outings) ||
                       (flex && flex.version !== this.report.shared.flexibleTransit));
    const outingTrips = outings?.active ? 2 * outings.report.attendance : 0;
    const walks = shortWalks ? this.report.weekday.shortWalks : 0;
    if (differs === this.differentLayers && outingTrips === this.outingTrips &&
        walks === this.shortWalks && escortTrips === this.escortTrips) return;
    this.differentLayers = differs;
    this.outingTrips = outingTrips;
    this.shortWalks = walks;
    this.escortTrips = escortTrips;
    el("recreation-layer-note").hidden = !differs;
    this.describe();
  }

  loadResident(da, refresh = true) {
    if (!this.areas.has(da)) return Promise.resolve();
    if (!this.loading.has(da)) {
      this.loading.set(da,this.json(this.base + da + ".json").then(rows => {
        for (const [id,loops] of index(rows)) this.records.set(id,loops);
        if (refresh) this.render();
      }).catch(e => {
        this.loading.delete(da);
        throw e;
      }));
    }
    return this.loading.get(da);
  }

  async choose(row,minute = row[3]) {
    const [d,i,,start,duration,added] = row;
    if (added && this.differentLayers) throw Error("The added trip uses the published activity reservations.");
    const da = this.day.das[d];
    await this.loadResident(da);
    this.example = row;
    if (added) this.enable(true);
    const controls = el("recreation-stages");
    controls.replaceChildren();
    for (const [label,minute] of [["Leave home",start],["On the path",start + duration / 2],["Back home",start + duration]]) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.onclick = () => this.follow(da,i,minute).catch(e=>this.error(e));
      controls.append(button);
    }
    await this.follow(da,i,minute);
  }

  delta(minute) {
    return this.active && !this.differentLayers ? this.report.occupancyDelta[minute - 240] : null;
  }

  state(d,i,minute,trail,selected = false) {
    const id = key(d,i);
    const records = (selected && this.records.get(id)) || this.sample.get(id);
    const enabled = this.active && !this.differentLayers;
    const row = records?.find(r => (!r[5] || enabled) && minute >= r[3] && minute < r[3] + r[4]);
    if (!row) return null;
    const [,,,start,dur,added,kind,path,metres] = row;
    if (!this.offsets.has(row)) {
      const lengths = [0];
      for (let j=1;j<path.length;j++) lengths.push(lengths[j-1] + distance(path[j-1],path[j]));
      const length = lengths.at(-1);
      this.offsets.set(row,lengths.map(x=>x * dur / length));
    }
    const offsets = this.offsets.get(row);
    const motion = track(path,offsets,minute - start,trail ? 1.5 : 0);
    const trip = this.mode === "bike" ? "bike ride" : "walk";
    return {mode:this.mode,p:motion.position,trail:motion.trail,routed:true,path,offsets,start,dur,added,
      recreation:(added ? "Added recreational " : "Recorded home-to-home ") + trip,
      description:(kind === "circuit" ? (this.mode === "bike" ? "Cycling circuit" : "Walking circuit") : "Out-and-back " + trip) +
        " · " + (metres / 1000).toFixed(2) + " km · " + dur + " min"};
  }
}

export async function attachRecreation(root,versions,day,json,follow,render) {
  const folder = root + "recreation-loops/";
  const params = new URL(location.href).searchParams;
  const pinned = params.get("recreationRun");
  let version = pinned;
  if (!version) {
    const key = [versions.atlas,versions.day,versions.streets,versions.clock].filter(Boolean).join("_");
    const response = await fetch(folder + key + ".json");
    if (response.status === 404) return null;
    if (!response.ok) throw Error("The recreation replay is unavailable.");
    ({version} = await response.json());
  }
  if (!/^[a-f0-9]{20}$/.test(version)) throw Error("Invalid recreation release.");
  const base = folder + version + "/";
  const [report,sample] = await Promise.all([json(base + "report.json"),json(base + "sample.json")]);
  if ((report.versions.clock ?? null) !== (versions.clock ?? null) ||
      Object.entries(versions).some(([k,v])=>report.versions[k] !== v))
    throw Error("The recreation trips use a different weekday.");
  const result = new RecreationLoops(report,version,base,day,sample,json,follow,render,
    !!pinned || params.get("recreation") === "on");
  const panel = el("recreation-loops");
  el("recreation-controls").hidden = false;
  panel.hidden = false;
  if (pinned || params.has("recreation")) panel.open = true;
  return result;
}
