import {track} from "../js/vancouver/route-timeline.js";

const el = id => document.getElementById(id);
const fmt = n => n.toLocaleString("en-CA");
const key = (d,i) => d + "/" + i;
const modes = {walk:"Walk", "car-driver":"Family car"};
const startOfClass = 540, endOfClass = 900, diaryTravel = 30;

function index(rows,target) {
  for (const row of rows) {
    const [d,adult,children] = row;
    for (const person of [adult,...children]) {
      const id = key(d,person);
      if (!target.has(id)) target.set(id,[]);
      target.get(id).push(row);
    }
  }
}

function button(container,label,action) {
  const result = document.createElement("button");
  result.type = "button";
  result.textContent = label;
  result.onclick = action;
  container.append(result);
}

function timing(row) {
  const [,,,,,,direction,start,travel,wait,back] = row;
  const arrival = start + travel, departure = arrival + wait, end = departure + back;
  const drop = direction === "drop-off";
  return {drop, start, arrival, departure, end, sharedStart:drop ? start : departure,
    sharedEnd:drop ? arrival : end};
}

class SchoolEscorts {
  constructor(report,version,base,day,places,sample,json,follow,render,active) {
    Object.assign(this,{report,version,base,day,places,json,follow,render,active});
    this.sample = new Map();
    this.people = new Map();
    this.areas = new Set(report.areas);
    this.loading = new Map();
    index(sample,this.sample);
    const control = el("school-replay");
    control.checked = this.active;
    control.onchange = () => this.enable(control.checked);
    el("school-source").href = report.survey;
    for (const [name,periods] of Object.entries(report.outcomes)) {
      for (const [direction,counts] of Object.entries(periods)) {
        for (const [mode,label] of Object.entries(modes)) {
          const row = el("school-rows").insertRow();
          const {pupils,surveyCeiling} = counts[mode];
          const total = report.populations[name];
          for (const value of [name,direction,label,fmt(pupils)+" / "+fmt(total),
            (100*report.shares[direction][mode]).toFixed(0)+"% ("+fmt(surveyCeiling)+")"])
            row.insertCell().textContent = value;
        }
      }
    }
    for (const [direction,examples] of Object.entries(report.examples)) {
      for (const [mode,row] of Object.entries(examples)) {
        if (!row) continue;
        const label = modes[mode] + " " + direction;
        button(el("school-examples"),label,()=>this.example(row).catch(e=>this.error(e)));
      }
    }
    this.describe();
  }

  describe() {
    const schoolPupils = Object.values(this.report.populations).reduce((a,b)=>a+b,0);
    el("school-status").textContent = fmt(this.report.total) + " coordinated household drop-offs and pickups among "+
      fmt(schoolPupils) + " students assigned to " + fmt(this.report.schools) + " public elementary schools.";
    el("school-layer-note").hidden = !this.differentLayers;
    el("school-replay").disabled = !!this.differentLayers;
    for (const item of el("school-examples").children) item.disabled = !!this.differentLayers;
  }

  error(e) {
    el("school-status").textContent = e.message;
  }

  checkLayers(outings,flex,recreation) {
    const parents = this.report.shared;
    const different = !!((outings?.active && outings.version !== parents.outings) ||
      (flex && flex.version !== parents.flexibleTransit) ||
      (recreation?.active && recreation.version !== parents.recreation));
    if (different === this.differentLayers) return;
    this.differentLayers = different;
    this.describe();
    for (const item of el("school-steps").querySelectorAll("button")) item.disabled = different;
  }

  enable(active) {
    this.active = active;
    el("school-replay").checked = active;
    const url = new URL(location.href);
    url.searchParams.delete("schools");
    if (active) url.searchParams.set("schoolRun",this.version);
    else url.searchParams.delete("schoolRun");
    history.replaceState(null,"",url);
    el("school-example").hidden = !active;
    this.render();
  }

  loadResident(da, refresh = true) {
    if (!this.areas.has(da)) return Promise.resolve();
    if (!this.loading.has(da)) {
      this.loading.set(da,this.json(this.base + da + ".json").then(rows=>{
        index(rows,this.people);
        if (refresh) this.render();
      }).catch(e=>{
        this.loading.delete(da);
        throw e;
      }));
    }
    return this.loading.get(da);
  }

  async example(row) {
    if (this.differentLayers) return;
    const [d,adult,children,,school] = row;
    const da = this.day.das[d], stages = timing(row);
    await this.loadResident(da);
    this.enable(true);
    const panel = el("school-example"), controls = el("school-steps");
    const name = this.places[school][3];
    panel.hidden = false;
    el("school-example-site").textContent = name + " · " + fmt(children.length) +
      (children.length === 1 ? " student" : " siblings");
    controls.replaceChildren();
    const midpoint = (stages.sharedStart + stages.sharedEnd) / 2;
    const move = (person,minute)=>this.follow(da,person,minute).catch(e=>this.error(e));
    button(controls,"Follow adult with students",()=>move(adult,midpoint));
    button(controls,"Follow a student",()=>move(children[0],midpoint));
    button(controls,stages.drop?"Drop-off":"School pickup",()=>move(adult,stages.arrival));
    const alone = stages.drop?(stages.departure+stages.end)/2:(stages.start+stages.arrival)/2;
    button(controls,stages.drop?"Adult returns home":"Adult leaves for school",()=>move(adult,alone));
    await move(adult,midpoint);
  }

  delta(minute) {
    return this.active && !this.differentLayers ? this.report.occupancyDelta[minute - 240] : null;
  }

  adultTrips() {
    return this.active && !this.differentLayers ? 2 * this.report.total : 0;
  }

  state(d,i,minute,trail,selected=false) {
    if (!this.active || this.differentLayers) return null;
    const id = key(d,i);
    const rows = (selected && this.people.get(id)) || this.sample.get(id);
    for (const row of rows ?? []) {
      const [,adult,,home,site,mode,direction,start,there,wait,back,out,inbound] = row;
      const {drop,arrival,departure,end,sharedStart,sharedEnd} = timing(row);
      const isAdult = i === adult;
      const label = "School " + direction;
      if (!isAdult && ((drop && minute >= startOfClass - diaryTravel && minute < start) ||
          (!drop && minute >= end && minute < endOfClass + diaryTravel))) {
        const before = drop ? startOfClass - diaryTravel : end;
        return {mode:"stop",kind:"home",p:this.places[home],a:this.places[home],
          start:before,dur:(drop?start:endOfClass + diaryTravel)-before,school:"At home"};
      }
      if (isAdult && minute >= arrival && minute < departure) {
        const school = this.places[site];
        return {mode:"stop",kind:"school",p:school,a:school,start:arrival,dur:wait,school:label};
      }
      const moving = isAdult ? minute >= start && minute < end : minute >= sharedStart && minute < sharedEnd;
      if (moving) {
        const going = minute < arrival;
        const [path,offsets] = going ? out : inbound, origin = going ? start : departure;
        const p = track(path,offsets,minute - origin,trail?1.5:0);
        const shared = minute >= sharedStart && minute < sharedEnd;
        const actualMode = mode === "car-driver" && !isAdult ? "car-passenger" : mode;
        return {mode:actualMode,p:p.position,trail:p.trail,path,offsets,start:origin,dur:going?there:back,routed:true,
          streetParty:actualMode==="walk"&&shared?1+row[2].length:1,
          school:shared ? label + " with household" : label,
          description:(actualMode==="walk"?"Walking":isAdult?"Driving":"Riding in family car") +
            " · " + (going ? this.places[site][3] : "returning home")};
      }
    }
    return null;
  }
}

export async function attachSchoolEscorts(root,versions,day,places,json,follow,render) {
  const folder = root + "school-escorts/";
  const params = new URLSearchParams(location.search);
  const pinned = params.get("schoolRun");
  let version = pinned;
  if (!version) {
    const response = await fetch(folder + [versions.atlas,versions.day,versions.streets].join("_") + ".json");
    if (response.status === 404) return null;
    if (!response.ok) throw Error("School escorts are unavailable.");
    ({version} = await response.json());
  }
  if (!/^[a-f0-9]{20}$/.test(version)) throw Error("Invalid school escort release.");
  const base = folder + version + "/";
  const [report,sample] = await Promise.all([json(base + "report.json"),json(base + "sample.json")]);
  if (Object.entries(versions).some(([k,v])=>report.versions[k] !== v))
    throw Error("School escorts use a different weekday.");
  const result = new SchoolEscorts(report,version,base,day,places,sample,json,follow,render,
    !!pinned || params.get("schools") === "on");
  const panel = el("school-escorts");
  el("school-controls").hidden = false;
  panel.hidden = false;
  if (pinned || params.has("schools")) panel.open = true;
  return result;
}
