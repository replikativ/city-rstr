import {track} from "../js/vancouver/route-timeline.js";
import {loadRouteGeometry} from "./regional-transit.js";
import {ScheduledPassengers} from "./transit-passenger.js";

const el = id => document.getElementById(id);
const fmt = n => n.toLocaleString("en-CA");
const key = (d,i) => d + "/" + i;
const modes = {"car-driver":"Drive",bike:"Cycle",walk:"Walk",transit:"Take transit"};

class WeekdayAttendance {
  constructor(report,version,base,day,places,sample,passengers,busParents,json,follow,render,active) {
    Object.assign(this,{report,version,base,day,places,json,follow,render,active,passengers,busParents});
    this.sample = new Map(sample.map(row=>[key(...row),row]));
    this.records = new Map();
    this.areas = new Set(report.areas);
    this.loading = new Map();
    const toggle = el("attendance-replay");
    toggle.checked = this.active;
    toggle.onchange = ()=>this.enable(toggle.checked);
    el("attendance-source").href = report.survey;
    const total = Object.values(report.baseline).reduce((n,row)=>n+row.withWorkTrip,0);
    el("attendance-status").textContent = fmt(total) + " North Shore residents with a recorded trip to paid work · " +
      fmt(report.total) + " more with a routed on-site shift.";
    for (const [name,comparisons] of Object.entries(report.modes)) {
      for (const [mode,{recorded,added,scaledSurvey}] of Object.entries(comparisons)) {
        const tr = el("attendance-rows").insertRow();
        for (const label of [name,mode,fmt(recorded),fmt(recorded+added),fmt(scaledSurvey)])
          tr.insertCell().textContent = label;
      }
    }
    for (const [mode,row] of Object.entries(report.examples)) {
      if (!row) continue;
      this.button(el("attendance-examples"),modes[mode]+" to work",()=>this.example(row).catch(e=>this.error(e)));
    }
  }

  button(container,label,action) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.onclick = action;
    container.append(button);
  }

  error(e) {
    el("attendance-error").textContent = e.message;
  }

  checkLayers(outings,flex,recreation,schools,workTransit) {
    const parents = this.report.shared;
    const differs = !!((outings?.active && outings.version!==parents.outings) ||
      (flex && flex.version!==parents.flexibleTransit) ||
      (recreation?.active && recreation.version!==parents.recreation) ||
      (schools?.active && schools.version!==parents.schools) ||
      (workTransit && !this.busParents.has(workTransit.version)));
    if (differs === this.differentLayers) return;
    this.differentLayers = differs;
    el("attendance-layer-note").hidden = !differs;
    el("attendance-replay").disabled = differs;
    for (const button of el("attendance-controls").querySelectorAll("button")) button.disabled = differs;
  }

  enable(active) {
    this.active = active;
    el("attendance-replay").checked = active;
    const url = new URL(location.href);
    url.searchParams.delete("attendance");
    if (active) url.searchParams.set("attendanceRun",this.version);
    else url.searchParams.delete("attendanceRun");
    history.replaceState(null,"",url);
    el("attendance-example").hidden = !active;
    this.render();
  }

  loadResident(da, refresh = true) {
    if (!this.areas.has(da)) return Promise.resolve();
    if (!this.loading.has(da)) this.loading.set(da,this.json(this.base+da+".json").then(rows=>{
      for (const row of rows) this.records.set(key(...row),row);
      if (refresh) this.render();
    }).catch(e=>{
      this.loading.delete(da);
      throw e;
    }));
    return this.loading.get(da);
  }

  async example(row) {
    if (this.differentLayers) return;
    const [d,i,,job,mode,start,work,leave,end,,back,paid,,,,,arrived] = row;
    const da = this.day.das[d];
    await this.loadResident(da);
    this.enable(true);
    const controls = el("attendance-steps");
    const returning = mode==="transit"?back[0]:leave;
    el("attendance-example").hidden = false;
    el("attendance-example-workplace").textContent = (this.places[job][3] ?? "Mapped workplace") +
      " · " + fmt(paid) + " minutes of paid work";
    controls.replaceChildren();
    const follow = minute=>this.follow(da,i,minute).catch(e=>this.error(e));
    const commute = (start + arrived)/2;
    for (const [label,minute] of [["To work",commute],["At the workplace",(work+leave)/2],
      ["Returning home",(returning+end)/2],["Back home",end]])
      this.button(controls,label,()=>follow(minute));
    await follow(commute);
  }

  get enabled() { return this.active && !this.differentLayers; }
  adultTrips() { return this.enabled ? 2*this.report.total : 0; }
  delta(minute) { return this.enabled ? this.report.occupancyDelta[minute-240] : null; }

  scheduled(row,minute,graph) {
    const routes = [row[6],row[12]?.[0]].filter(Boolean);
    for (const route of routes) if (!this.passengers.routes.has(route)) {
      this.passengers.routeData(route).catch(e=>this.error(e));
    }
    if (routes.some(route=>!this.passengers.routes.has(route))) return {p:null,description:"Loading scheduled transit"};
    const position = row[12] ? this.passengers.transferPosition(row,minute,graph)
      : this.passengers.position(row,minute,graph,true);
    if (position?.description.startsWith("Walking ") && !position.routed)
      return {p:null,description:"Finding the street walk"};
    return position;
  }

  state(d,i,minute,graph,trail,selected=false) {
    if (!this.enabled) return null;
    const id = key(d,i);
    const row = (selected && this.records.get(id)) || this.sample.get(id);
    if (!row) return null;
    const [,,home,job,mode,start,work,leave,end,go,back,,,,,,arrived] = row;
    if (minute < start || minute >= end) return null;
    const returning = mode==="transit"?back[0]:leave;
    const workplace = this.places[job];
    if (minute>=arrived && minute<returning) {
      const label = minute<work?"Arrived before the shift":minute<leave?"On-site shift":"Waiting to travel home";
      const [a,b] = minute<work?[arrived,work]:minute<leave?[work,leave]:[leave,returning];
      return {mode:"stop",p:workplace,a:workplace,kind:"job",attendance:label,start:a,dur:b-a};
    }
    const outward = minute<arrived;
    const origin = outward ? start : returning;
    const dur = (outward ? arrived : end)-origin;
    const a = outward?home:job, b = outward?job:home;
    const base = {mode,attendance:outward?"Added trip to work":"Added trip home",
      a:this.places[a],b:this.places[b],kind:outward?"job":"home",start:origin,dur};
    if (mode==="transit") {
      const ride = [this.day.das[d],i,origin,dur,a,b,...(outward?go:back[1])];
      return {...base,...this.scheduled(ride,minute,graph),scheduled:true};
    }
    const [path,times] = outward?go:back;
    const motion = track(path,times,minute-origin,trail?1.5:0);
    return {...base,path,offsets:times,routed:true,p:motion.position,trail:motion.trail,routeMinutes:dur};
  }
}

export async function attachAttendance(root,versions,day,places,json,follow,render) {
  const folder = root+"weekday-attendance/";
  const params = new URLSearchParams(location.search), pinned = params.get("attendanceRun");
  let version = pinned;
  if (!version) {
    const result = await fetch(folder+[versions.atlas,versions.day,versions.streets].join("_")+".json");
    if (result.status===404) return null;
    if (!result.ok) throw Error("The on-site work replay is unavailable.");
    ({version}=await result.json());
  }
  if (!/^[a-f0-9]{20}$/.test(version)) throw Error("Invalid on-site work release.");
  const base = folder+version+"/";
  const [report,sample] = await Promise.all([json(base+"report.json"),json(base+"sample.json")]);
  if (Object.entries(versions).some(([k,v])=>report.versions[k]!==v) || !/^[a-f0-9]{20}$/.test(report.versions.transit))
    throw Error("On-site work uses a different weekday.");
  const timetable = root+"transit/"+report.versions.transit+"/";
  const [manifest,clock] = await Promise.all([json(timetable+"transit.json"),
    json(root+"household-clock/"+report.shared.flexibleTransit+"/report.json")]);
  if (manifest.date!==report.serviceDate) throw Error("On-site work uses a different transit service date.");
  const passengers = new ScheduledPassengers({manifest,routeData:id=>loadRouteGeometry(json,timetable+id+".json")},
    places,render,e=>{el("attendance-error").textContent=e.message;});
  const busParents = new Set([clock.workTransitRelease,clock.flex.baselineRelease]);
  const result = new WeekdayAttendance(report,version,base,day,places,sample,passengers,busParents,json,follow,render,
    !!pinned || params.get("attendance")==="on");
  const panel = el("weekday-attendance");
  el("attendance-controls").hidden = false;
  panel.hidden = false;
  if (pinned || params.has("attendance")) panel.open = true;
  return result;
}
