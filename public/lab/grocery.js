// Paired scenario results share the weekday map, camera and clock.
export function groceryPilot({el, shape, path, clock, pause, setTime, recenter, refresh, focus}) {
  let data, enabled = false, selected, matches = [];
  const number = n => n.toLocaleString(undefined,{maximumFractionDigits:1});
  const mean = values => values.reduce((a,b) => a+b,0)/values.length;
  const total = (rows,field) => mean(rows.map(r=>r[field]));
  const text = (tag, value) => {
    const e = document.createElement(tag); e.textContent = value; return e;
  };
  function table(headers, rows) {
    const t = document.createElement("table"), heading = t.createTHead().insertRow();
    headers.forEach(h=>heading.append(text("th",h)));
    const body = t.createTBody();
    for (const values of rows) {
      const r = body.insertRow();
      values.forEach(v=>r.insertCell().textContent = v);
    }
    return t;
  }

  function evidence() {
    const labels = data.sites.map(s=>s.name);
    const sensitivity = data.profiles.map(p => {
      const deltas = data.runs.map(r=>r.profiles[p.id].sites[0].visits-r.profiles[p.id].sites[1].visits);
      return [p.name,number(mean(deltas)),deltas.filter(d=>d>1e-8).length,deltas.filter(d=>d < -1e-8).length];
    });
    el("shop-evidence").hidden = false;
    const standard = data.runs.map(r=>r.profiles.standard.sites);
    const visits = labels.map((_,i)=>number(mean(standard.map(pair=>pair[i].visits))));
    const access = labels.map((_,i)=>number(mean(standard.map(pair=>pair[i].gained))));
    el("pilot-verdict").textContent = "The standard rule gives A "+visits[0]+" and B "+visits[1]+
      " expected walking visits per weekday. Previously deferred visits account for "+access[0]+" at A and "+access[1]+
      " at B. Pedestrian checks and unmeasured grocery demand limit the case for choosing a real site. The two sites use the same shopping occasions in each run. The difference below is expected visits per weekday at A minus B. A is "+labels[0]+" and B is "+labels[1]+". Ties count toward neither site.";
    el("pilot-sensitivity").replaceChildren(table(["Choice rule","A − B","Runs A leads","Runs B leads"],sensitivity));
    el("pilot-method").textContent = "The 2025 City storefront inventory supplies the candidate locations. Issued 2025 licences identify "+data.inventory.grocery+" grocery addresses citywide and "+data.inventory.food+" addresses when other food retailers are included. The model treats "+number(data.share*100)+"% of eligible goods occasions as grocery demand. It assumes walking at "+data.speed+" metres per minute with at most "+data.budget+" walking minutes and enough time to reach the next diary activity. Existing stores open 08:00–20:00 in all runs.";
    const checks = el("movement-check");
    const hours = [];
    data.studies.forEach((s,j)=>s.hours.forEach((h,i)=>{
      const scores = [0,1].map(m => number(mean(data.runs.map(r=>r.diagnostic[m][j][h] ?? 0))));
      hours.push([s.name,clock(h),s.observed[i],...scores]);
    }));
    checks.append(text("p","The workplace alternative samples licensed job locations within 500 m of the original target, weighted by reported employees. The two Broadway intersections were reserved for evaluation. Every comparison uses its archived survey hour."),
      table(["Site","Hour","Observed","Original","Jobs"],hours));
    const flow = [];
    for (let j=0;j<2;j++) {
      for (const [m,label] of [[0,"Original"],[1,"Jobs"]]) {
        const counts = ["present","working","departed","foodOrStore"].map(k => number(mean(data.runs.map(r=>r.diagnostic[m][j][k] ?? 0))));
        flow.push([data.studies[j].name,label,...counts]);
      }
    }
    checks.append(text("p","Among residents with a walking diary, these weighted counts trace people at a known stop within 400 m at 11:30. Departures count immediate standalone walks before 13:00. The final column counts departures to a restaurant or store. The two catchments overlap."),
      table(["Site","Rule","Present","At work","Departed","To food/store"],flow));
    for (const study of data.studies.slice(2)) {
      const link = text("a",study.name+" · "+study.date+" survey workbook");
      link.href = study.source; const p = document.createElement("p"); p.append(link); checks.append(p);
    }
  }

  function breakdown(rows,changed) {
    const host = el("shop-origins"); host.replaceChildren();
    const access = new Map();
    for (const trip of changed) {
      if (!trip.before) access.set(trip.area,(access.get(trip.area) ?? 0)+trip.weight/data.runs.length);
    }
    if (access.size) host.append(table(["Newly feasible by home area","Visits"],[...access].map(([area,n])=>[area,number(n)])));
    for (const [key,title] of [["origins","All visitors by home area"],["ages","Age"],["hourly","Arrival hour"],["displaced","Displaced store address"]]) {
      const counts = new Map();
      rows.forEach(r=>Object.entries(r[key]).forEach(([k,v])=>counts.set(k,(counts.get(k) ?? 0)+v/rows.length)));
      const entries = [...counts].sort((a,b)=>key === "hourly" ? Number(a[0])-Number(b[0]) : b[1]-a[1]);
      if (entries.length) host.append(table([title,"Visits"],entries.map(([k,v])=>[key === "hourly"?clock(Number(k)*60):k, number(v)])));
    }
  }

  function draw(minute) {
    const dot = el("shop-dot"), trip = selected?.after;
    if (!trip || minute < trip.start || minute > trip.end) {dot.style.display="none"; return;}
    let point;
    if (minute < trip.arrival) point = along(trip.to,(minute-trip.start)/(trip.arrival-trip.start));
    else if (minute <= trip.leave) point = trip.to.at(-1);
    else point = along(trip.onward,(minute-trip.leave)/(trip.end-trip.leave));
    dot.setAttribute("cx",point[0]); dot.setAttribute("cy",point[1]); dot.style.display="";
  }
  function along(points,fraction) {
    const lengths = points.slice(1).map(([x,y],i)=>Math.hypot(x-points[i][0],y-points[i][1]));
    let remaining = fraction*lengths.reduce((a,b)=>a+b,0);
    for (let i=0;i<lengths.length;i++) {
      if (lengths[i]>0 && remaining<=lengths[i]) {
        return points[i].map((v,k)=>v+(points[i+1][k]-v)*remaining/lengths[i]);
      }
      remaining -= lengths[i];
    }
    return points.at(-1);
  }
  function trip(index) {
    selected = matches[index];
    const before = selected?.before, after = selected?.after;
    for (const [id,t] of [["before-route",before],["after-route",after]]) {
      el(id).setAttribute("d",t ? path(t.to)+path(t.onward) : "");
    }
    el("shop-dot").style.display="none";
    if (!selected) return;
    const from = selected.origin.replaceAll("-"," "), next = selected.next.replaceAll("-"," ");
    const original = before ? before.name+" ("+number(before.minutes)+" min walking)" : "deferred";
    el("shop-story").textContent = "Age "+selected.age+" · "+selected.area+". Leaves "+from+" at "+clock(after.start)+". The original choice was "+original+". The new trip takes "+number(after.minutes)+" min walking via "+after.name+", reaching "+next+" at "+clock(after.end)+" by the "+clock(selected.deadline)+" commitment.";
    const points = [...after.to,...after.onward,...(before?.to ?? []),...(before?.onward ?? [])];
    pause(); focus(points); setTime(after.start);
  }

  function render() {
    matches=[]; selected=undefined;
    if (!data) return;
    const site = el("shop-site").value, profile = el("shop-profile").value;
    const j = data.sites.findIndex(s=>s.id===site);
    const runs = data.runs.map(r=>r.profiles[profile]), host=el("shop-result");
    host.replaceChildren();
    const baseline=total(runs,"baseline"), deferred=total(runs,"deferred");
    host.append(text("p","Expected walking visits per weekday, averaged over "+runs.length+" seeds."));
    if (j<0) {
      host.append(text("strong",number(baseline)+" visits to existing shops"),text("p",number(deferred)+" additional grocery occasions have no feasible store. Select a site to open the same grocery there."));
    } else {
      const rows=runs.map(r=>r.sites[j]), count=total(rows,"visits"), other=total(runs.map(r=>r.sites[1-j]),"visits");
      const label=text("strong",number(count)+" new-shop visits"); label.className="shop-number";
      host.append(label,text("p",number(total(rows,"diverted"))+" diverted from other shops · "+number(total(rows,"gained"))+" newly feasible. "+number(total(rows,"reachable"))+" occasions can fit this shop into the diary. The other site draws "+number(other)+" visits under the same assumptions."));
      const displaced=total(rows,"diverted");
      if (displaced) host.append(text("p",number(total(rows,"minutesSaved")/displaced)+" walking minutes saved on average per diverted visit."));
      const changed=data.examples.filter(e=>e.site===site && e.profiles.includes(profile));
      breakdown(rows,changed);
      const type=el("shop-trip-type").value;
      matches=changed.filter(e=>type==="all" || (type==="new" ? !e.before : e.before));
      const picker=el("shop-example"); picker.replaceChildren();
      matches.forEach((e,i)=>picker.add(new Option(e.seed+" · "+clock(e.after.start)+" · "+e.area+" · "+(i+1),i)));
    }
    el("shop-breakdown").hidden=j<0;
    el("shop-inspector").hidden=j<0;
    el("shop-example").disabled=!matches.length;
    if (!matches.length) el("shop-story").textContent="No sampled trips of this type for this opening.";
    el("shop-inspector").querySelector(".trip-key").hidden=!matches.length;
    for (const pin of el("shop-pins").children) pin.setAttribute("aria-pressed",String(pin.dataset.site===site));
    trip(0);
    if (!selected) {pause(); focus(data.sites.map(s=>s.point));}
  }
  function mode(open) {
    enabled=open; pause();
    const url=new URL(location.href);
    if (open) url.searchParams.set("view","shop"); else url.searchParams.delete("view");
    history.replaceState(null,"",url);
    document.body.classList.toggle("shop-mode",open);
    el("shop-mode").setAttribute("aria-pressed",String(open)); el("weekday-mode").setAttribute("aria-pressed",String(!open));
    el("weekday-tools").hidden=open; el("shop-tools").hidden=!open; el("shop-layer").style.display=open?"":"none";
    if (open) render(); else {recenter(); refresh();}
  }
  el("shop-mode").onclick=()=>mode(true); el("weekday-mode").onclick=()=>mode(false);
  el("shop-result").textContent="Loading grocery comparison…";
  fetch("data/vancouver/grocery.json").then(r=>{if (!r.ok) throw Error(); return r.json();}).then(result=>{
    data=result;
    data.sites.forEach((s,i)=>{
      const letter=String.fromCharCode(65+i);
      el("shop-site").add(new Option(letter+" · "+s.name,s.id));
      const g=shape("g",{class:"shop-pin",transform:"translate("+s.point.join(" ")+")",role:"button",tabindex:0,"aria-label":"Open grocery at "+s.name});
      g.dataset.site=s.id;
      const caption=shape("text",{});caption.textContent=letter;
      g.append(shape("rect",{x:-20,y:-20,width:40,height:40,rx:4}),caption);
      g.onclick=()=>{el("shop-site").value=s.id;render();};
      g.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();g.onclick();}};
      el("shop-pins").append(g);
    });
    data.profiles.forEach(p=>el("shop-profile").add(new Option(p.name,p.id)));
    el("shop-site").onchange=el("shop-profile").onchange=el("shop-trip-type").onchange=render;
    el("shop-example").onchange=e=>trip(Number(e.target.value));
    evidence(); if(enabled) render();
  }).catch(()=>{el("shop-result").textContent="Grocery comparison unavailable. Build the pilot using the Vancouver instructions in README.md.";});
  if (new URL(location.href).searchParams.get("view")==="shop") mode(true);
  return {active:()=>enabled,draw};
}
