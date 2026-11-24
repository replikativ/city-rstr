import {groceryPilot} from "./grocery.js";
import {linkStudyArea} from "./coverage.js";
linkStudyArea();
const el = id => document.getElementById(id);
const svg = el("walk-map");
const ns = "http://www.w3.org/2000/svg";
const shape = (tag, attrs) => {
  const node = document.createElementNS(ns, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
};
const path = points => "M" + points.map(p => p.join(",")).join("L");
const clock = time => {
  const m = Math.floor(time) % 1440;
  return [Math.floor(m / 60), m % 60].map(x => String(x).padStart(2, "0")).join(":") + (time >= 1440 ? " +1" : "");
};
const human = s => s.replaceAll("-", " ");
const placeName = s => s === "work-or-school" ? "work or school" : human(s);
const format = n => Math.round(n).toLocaleString();
let data, visible = [], selected, time = 480, playing = false, lastFrame, animation;
let homeView, view, drag, lastLeg;
const dots = new Map();
let pilot;

function drawStreets() {
  el("neighbourhood").setAttribute("d", path(data.boundary) + "Z");
  const groups = [[], [], []], names = new Map();
  for (const [kind, name, points] of data.streets) {
    const major = ["primary","secondary","tertiary"].includes(kind);
    const tier = major ? 2 : ["residential","unclassified","living_street"].includes(kind) ? 1 : 0;
    groups[tier].push(path(points));
    if (!name || !major) continue;
    const p = points[Math.floor(points.length / 2)];
    const score = Math.hypot(p[0] - homeView.x, p[1] - homeView.y);
    if (score < (names.get(name)?.score ?? Infinity)) names.set(name, {p,score});
  }
  groups.forEach((g, i) => el("streets").append(shape("path", {class:["trail-road","side-road","main-road"][i], d:g.join("")})));
  const labels = [];
  for (const [name, {p,score}] of [...names].sort((a,b) => a[1].score-b[1].score)) {
    if (score > 2200 || labels.some(q => Math.abs(q[0]-p[0]) < 330 && Math.abs(q[1]-p[1]) < 115)) continue;
    const label = shape("text", {x:p[0], y:p[1]-10, "text-anchor":"middle"});
    label.textContent = name;
    el("street-labels").append(label);
    labels.push(p);
  }
  const template = el("counters").firstElementChild;
  el("counters").replaceChildren();
  data.studies.forEach((study, index) => {
    const marker = template.cloneNode(true);
    marker.setAttribute("transform", "translate(" + study.point.join(" ") + ")");
    marker.setAttribute("aria-label", "Inspect " + study.name);
    marker.onclick = () => inspectSite(index);
    marker.onkeydown = e => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); inspectSite(index); }
    };
    el("counters").append(marker);
    el("inspect-site").add(new Option(study.name, index));
    const item = document.createElement("li"), link = document.createElement("a");
    link.textContent = study.name + " · " + study.date;
    link.href = study.source;
    item.append(link); el("workbooks").append(item);
  });
}

function camera() {
  const ratio = svg.clientWidth / Math.max(1, svg.clientHeight);
  const h = Math.max(view.width/ratio, view.height);
  const w = h * ratio;
  svg.setAttribute("viewBox", [view.x-w/2, view.y-h/2, w, h].join(" "));
}
function zoom(factor) {
  if (view.width*factor < 250 || view.width*factor > homeView.width*5) return;
  view = {...view, width:view.width*factor, height:view.height*factor};
  camera();
}
function position(leg, minute) {
  const target = (minute-leg.start)/leg.dur * leg.lengths.at(-1);
  let i = 1;
  while (i < leg.lengths.length-1 && leg.lengths[i] < target) ++i;
  const f = (target-leg.lengths[i-1]) / (leg.lengths[i]-leg.lengths[i-1] || 1);
  return leg.points[i-1].map((v, k) => v + f*(leg.points[i][k]-v));
}

function draw() {
  if (!data) return;
  if (pilot?.active()) {
    pilot.draw(time); el("clock").textContent = clock(time); el("minute").value = Math.floor(time);
    return;
  }
  const active = new Set();
  let chosenLeg;
  for (const person of visible) {
    const leg = person.legs.find(l => l.start <= time && time < l.start+l.dur);
    if (!leg) continue;
    active.add(person.id);
    const [x,y] = position(leg,time);
    if (!dots.has(person.id)) {
      const g = shape("g", {"data-person":person.id});
      const title = shape("title", {});
      title.textContent = person.label + " · " + person.area;
      g.append(title,shape("circle",{r:36,fill:"transparent"}),shape("circle",{r:11,fill:person.local?"#a1e5bd":"#ffc47c",stroke:"#15252a","stroke-width":3}));
      el("walkers").append(g);
      dots.set(person.id,g);
    }
    const dot = dots.get(person.id);
    dot.setAttribute("transform", "translate("+ x + " " + y + ")");
    dot.lastChild.setAttribute("r", person === selected ? 18 : 11);
    if (person === selected) {
      chosenLeg = leg;
      if (el("follow-camera")?.checked && !drag) {
        view.x = x; view.y = y; camera();
      }
    }
  }
  for (const [id,g] of dots) if (!active.has(id)) { g.remove(); dots.delete(id); }
  if (lastLeg !== chosenLeg) {
    lastLeg = chosenLeg;
    el("selected-path").setAttribute("d", chosenLeg ? path(chosenLeg.points) : "");
    for (const b of el("itinerary").querySelectorAll("[data-leg]"))
      b.setAttribute("aria-current", String(selected.legs[Number(b.dataset.leg)] === chosenLeg));
  }
  el("clock").textContent = clock(time);
  el("minute").value = Math.floor(time);
}
function pause() { cancelAnimationFrame(animation); playing = false; el("play").textContent = "Play"; }
function jump(leg) { pause(); time = leg.start; draw(); }
function choose(person) {
  selected = person;
  el("itinerary").replaceChildren();
  el("walker").value = person?.id ?? "";
  if (!person) { draw(); return; }
  const note = document.createElement("p");
  note.textContent = "Age " + person.age + " · Home in " + person.area;
  const label = document.createElement("label"), input = document.createElement("input");
  input.type = "checkbox"; input.id = "follow-camera"; input.checked = true;
  label.append(input," Follow on map");
  el("itinerary").append(note,label);
  person.legs.forEach((leg,i) => {
    const b = document.createElement("button");
    b.dataset.leg = i;
    b.textContent = clock(leg.start)+"–"+clock(leg.start+leg.dur)+" · "+placeName(leg.origin)+" → "+placeName(leg.destination)+" · "+human(leg.activity);
    b.onclick = () => jump(leg);
    el("itinerary").append(b);
  });
  const active = person.legs.find(l => l.start <= time && time < l.start+l.dur);
  if (!active) jump(person.legs.find(l => l.start >= time) ?? person.legs[0]);
  else draw();
}
function filter() {
  const origin = el("origin").value;
  visible = data.people.filter(p => origin === "all" || (p.local === (origin === "local")));
  const picker = el("walker");
  picker.replaceChildren(new Option("Choose a walker…",""));
  for (const p of visible) picker.add(new Option(p.label+" · "+p.area,p.id));
  choose(undefined);
}
function surveyHours(study) {
  const hours = [];
  for (const [a,b] of study.windows ?? [[study.start,study.end]]) {
    for (let t = a; t < b; t += 60) hours.push(t);
  }
  return hours;
}

function showLunchComparison() {
  const sites = ["Ontario St & 5th Ave", "Ontario St & 10th Ave"].map(
    name => data.studies.find(s => s.name === name && s.date === "2023-07-12"));
  if (!sites.every(s => s?.runs?.length > 1)) return;
  const [fifth,tenth] = sites;
  const noon = sites.map(s => surveyHours(s).indexOf(720));
  if (noon.includes(-1)) return;
  const observed = sites.map((s,k) => {
    const n = 60/s.bin, first = noon[k]*n;
    return s.observed.slice(first,first+n).reduce((a,b) => a+b,0);
  });
  const tenthBySeed = new Map(tenth.runs.map(run => [run.seed,run.hours[noon[1]]]));
  const body = el("lunch-rows");
  let higher = 0, reached = 0;
  for (const run of fifth.runs) {
    const a = run.hours[noon[0]], b = tenthBySeed.get(run.seed);
    if (b === undefined) continue;
    if (a > b) higher++;
    if (a-b >= observed[0]-observed[1]) reached++;
    const row = body.insertRow();
    for (const value of [run.seed,a.toFixed(1),b.toFixed(1),(a-b).toFixed(1)]) row.insertCell().textContent = value;
  }
  const count = body.rows.length;
  if (!count) return;
  el("lunch-result").textContent = "From noon to 13:00 on July 12, the City counted "+observed[0]+
    " crossings at 5th and "+observed[1]+" at 10th. Across "+count+" seeded weekdays, "+higher+
    " put more passings at 5th and "+reached+" reached the observed difference of "+(observed[0]-observed[1])+".";
  el("lunch-evidence").hidden = false;
}

function inspectSite(index) {
  const s = data.studies[index];
  el("inspect-site").value = index;
  const windows = s.windows ?? [[s.start, s.end]];
  const periods = windows.map(([a,b]) => clock(a)+"–"+clock(b)).join(", ");
  const observed = s.observed.reduce((a,b) => a+b,0);
  const total = s.events.reduce((a,e) => a+e[1],0);
  const local = s.events.reduce((a,e) => a+(e[2]?e[1]:0),0);
  el("comparison").hidden = false;
  el("comparison").innerHTML = '<p>'+s.date+' · '+periods+'</p><dl><dt>Observed crossings</dt><dd>'+format(observed)+'</dd><dt>Modelled passings</dt><dd>'+format(total)+'</dd></dl><p>'+format(local)+' from local residents and '+format(total-local)+' from elsewhere in Vancouver. Expanded from '+s.events.length+' sampled walks.</p>';
  const repeated = s.runs?.length > 1;
  if (repeated) {
    const totals = s.runs.map(run => run.hours.reduce((sum,n) => sum+n,0));
    const mean = totals.reduce((sum,n) => sum+n,0) / totals.length;
    const note = document.createElement("p");
    note.textContent = totals.length+" seeded weekdays averaged "+format(mean)+" modelled passings, ranging from "+
      format(Math.min(...totals))+" to "+format(Math.max(...totals))+". The map shows seed "+s.runs[0].seed+".";
    el("comparison").append(note);
  }
  const detail = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "Hourly comparison";
  const table = document.createElement("table");
  const header = table.createTHead().insertRow();
  const headings = ["Hour", "Observed", "Replay"];
  if (repeated) headings.push("Run range");
  for (const title of headings) {
    const th = document.createElement("th");
    th.textContent = title;
    header.append(th);
  }
  const body = table.createTBody();
  surveyHours(s).forEach((t,i) => {
    const bin = i*60/s.bin;
    const obs = s.observed.slice(bin, bin+60/s.bin).reduce((a,b) => a+b,0);
    const estimate = s.events.filter(e => t <= e[0] && e[0] < t+60).reduce((a,e) => a+e[1],0);
    const row = body.insertRow();
    const values = [clock(t),format(obs),format(estimate)];
    if (repeated) {
      const hours = s.runs.map(run => run.hours[i]);
      values.push(format(Math.min(...hours))+"–"+format(Math.max(...hours)));
    }
    for (const value of values) row.insertCell().textContent = value;
  });
  detail.append(summary,table); el("comparison").append(detail);
  choose(undefined);
  view = {x:s.point[0],y:s.point[1],width:1500,height:850}; camera();
}
function frame(stamp) {
  if (!playing) return;
  time += Math.min(stamp-lastFrame, 250)/1000 * Number(el("speed").value);
  lastFrame = stamp;
  if (time >= 1680) {time = 1679; pause();}
  draw();
  if (playing) animation = requestAnimationFrame(frame);
}
function bind() {
  el("evidence").onclick = () => el("methods").showModal();
  el("inspect-site").onchange = e => {
    if (e.target.value === "") el("comparison").hidden = true;
    else inspectSite(Number(e.target.value));
  };
  el("walker").onchange = e => choose(visible.find(p => p.id === e.target.value));
  el("walkers").onclick = e => {
    const id = e.target.closest("[data-person]")?.dataset.person;
    if (id) choose(visible.find(p => p.id === id));
  };
  el("origin").onchange = filter;
  el("minute").oninput = e => {pause(); time = Number(e.target.value); draw();};
  el("play").onclick = () => {
    if (playing) {pause(); return;}
    if (time >= 1679) time = 240;
    playing = true; lastFrame = performance.now(); el("play").textContent = "Pause";
    animation = requestAnimationFrame(frame);
  };
  el("zoom-in").onclick = () => zoom(0.7);
  el("zoom-out").onclick = () => zoom(1/0.7);
  el("recenter").onclick = () => {
    if (el("follow-camera")) el("follow-camera").checked = false;
    view = {...homeView}; camera();
  };
  svg.onwheel = e => {e.preventDefault(); zoom(e.deltaY < 0 ? 0.85 : 1/0.85);};
  svg.onpointerdown = e => {
    if (e.target.closest(".counter,[data-person],.shop-pin")) return;
    svg.setPointerCapture(e.pointerId);
    drag = {x:e.clientX,y:e.clientY,view:{...view}};
    if (el("follow-camera")) el("follow-camera").checked = false;
  };
  svg.onpointermove = e => {
    if (!drag) return;
    const scale = svg.viewBox.baseVal.width / svg.clientWidth;
    view.x = drag.view.x-(e.clientX-drag.x)*scale;
    view.y = drag.view.y-(e.clientY-drag.y)*scale;
    camera();
  };
  svg.onlostpointercapture = () => {drag = undefined;};
  new ResizeObserver(camera).observe(svg);
}

async function init() {
  const response = await fetch("data/vancouver/walks.json");
  if (!response.ok) throw new Error("Weekday data unavailable");
  data = await response.json();
  data.studies ??= [data.study];
  const xs = data.boundary.map(p=>p[0]), ys = data.boundary.map(p=>p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  homeView = {x:(x0+x1)/2,y:(y0+y1)/2,width:(x1-x0)*1.13,height:(y1-y0)*1.28};
  view = {...homeView};
  data.people.forEach((p,i) => {
    p.local = p.area === data.area;
    p.label = "Walker "+String(i+1).padStart(3,"0");
    for (const leg of p.legs) {
      leg.lengths = [0];
      leg.points.slice(1).forEach(([x,y],j) => leg.lengths.push(leg.lengths[j]+Math.hypot(x-leg.points[j][0],y-leg.points[j][1])));
    }
  });
  drawStreets(); bind(); camera(); filter(); showLunchComparison();
  el("sample-note").textContent = data.people.length+" sampled walkers have a route touching Mount Pleasant. Citywide, "+data.exclusions["same-node"]+" candidate legs had coincident endpoints and "+data.exclusions["over-speed-limit"]+" implied a speed above 2.5 m/s. Both are excluded.";
  pilot = groceryPilot({el, shape, path, clock, pause, setTime: t => {time = t; draw();},
    recenter: () => {view = {...homeView}; camera();}, refresh: draw,
    focus: points => {
      const xs = points.map(p=>p[0]), ys = points.map(p=>p[1]);
      const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
      view = {x:(x0+x1)/2,y:(y0+y1)/2,width:Math.max(650,(x1-x0)*1.4),height:Math.max(600,(y1-y0)*1.5)};
      camera();
    }});
  el("play").disabled = false;
  el("status").textContent = "";
}
init().catch(e => {el("status").textContent = e.message + ". Generate the Vancouver replay as described in README.md.";});
