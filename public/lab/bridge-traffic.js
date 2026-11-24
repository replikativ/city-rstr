import {layersForNewDay} from "./coverage.js";
import {loadBridgeChoice} from "./bridge-choice.js";

const el = id => document.getElementById(id);
const number = n => n.toLocaleString("en-CA");
const selected = (select, value) => {
  if (Array.from(select.options).some(option => option.value === value)) select.value = value;
};

function renderAttribution(evidence, attributed, heading, hours) {
  const rows = el("bridge-attribution-rows");
  rows.replaceChildren();
  for (const [i, home] of evidence.homeGroups.entries()) {
    const row = rows.insertRow();
    row.insertCell().textContent = home;
    for (const k of [1,2,0]) {
      const total = hours.reduce((n,h) => n + attributed[h][i][k],0);
      row.insertCell().textContent = number(total);
    }
  }
  const sum = counts => number(hours.reduce((n,h) => n + counts[h],0));
  const {assigned,fits,routed} = evidence.directWorkDriving[heading];
  const destination = heading===0?(evidence.widerDestinations?"destinations south of Burrard Inlet":"Vancouver and UBC"):"the North Shore";
  el("bridge-direct-work").textContent =
    "Among direct drives from home to paid work departing in these hours toward " + destination + ", " +
    sum(assigned) + " are assigned across the inlet, " + sum(fits) + " have a bridge route within the diary time, and " +
    sum(routed) + " cross on their shortest route. These totals cover both bridges and use departure time.";
  const toward = evidence.workFlows.reduce((n,x) => n + x.towardVancouver,0);
  const from = evidence.workFlows.reduce((n,x) => n + x.fromVancouver,0);
  const stock =
    "The 2021 Census records " + number(toward) + " North Shore residents with a usual workplace in the City of Vancouver " +
    "and " + number(from) + " Vancouver residents with one in the three North Shore municipalities. These counts cover all usual commute modes.";
  const dailyToward = evidence.workFlows.reduce((n,x) => n + x.weekdayTowardVancouver,0);
  const dailyFrom = evidence.workFlows.reduce((n,x) => n + x.weekdayFromVancouver,0);
  const daily = "On this weekday, " + number(dailyToward) + " employed residents travel directly from home to paid work in Vancouver " +
    "and " + number(dailyFrom) + " in the reverse direction, across all recorded modes.";
  el("bridge-census-work").textContent = Number.isFinite(dailyToward + dailyFrom) ? stock + " " + daily : stock;
  el("bridge-commute-source").href = evidence.workSource;
}

function commuteSchedule(root, versions, json, requested) {
  const panel = el("bridge-commute-schedule"), home = el("bridge-schedule-home");
  const mode = el("bridge-schedule-mode"), measure = el("bridge-schedule-measure");
  const time = el("bridge-schedule-time");
  let report;
  function draw() {
    const i = Number(mode.value), area = home.value;
    const departures = measure.value === "departures";
    const timeBand = departures ? 0 : Number(time.value);
    const series = [report.census[area], report.model[area].direct, report.model[area].across];
    const rows = series.map(cube => cube[i]);
    const totals = rows.map(cube => cube[timeBand][0]);
    const share = (n,total) => Number.isFinite(n) && total > 0 ? (100*n/total).toFixed(1) + "%" : "—";
    el("bridge-schedule-total").textContent = totals.map((n,j) => (n === null ? "—" : number(n)) +
      [" usual commuters", " simulated direct work trips", " assigned across the inlet"][j]).join(" · ") + ".";
    el("bridge-schedule-time-label").hidden = departures;
    el("bridge-schedule-band").textContent = departures ? "Leaving home" : "Travel duration";
    const body = el("bridge-schedule-rows");
    body.replaceChildren();
    if (i !== 0) {
      const row = body.insertRow();
      row.insertCell().textContent = "Share using this mode";
      totals.forEach((n,k) => { row.insertCell().textContent = share(n,series[k][0][timeBand][0]); });
    }
    report.labels[measure.value].forEach((label, j) => {
      const row = body.insertRow(), band = j + 1;
      row.insertCell().textContent = label;
      rows.forEach((cube,k) => {
        row.insertCell().textContent = share(departures ? cube[band][0] : cube[timeBand][band],totals[k]);
      });
    });
  }
  for (const control of [home, mode, measure, time]) control.onchange = draw;
  return async heading => {
    const base = new URL("../commute-schedule/", new URL(root,location.href));
    const pointer = await fetch(new URL(versions.atlas + "_" + versions.day + ".json",base));
    if (pointer.status === 404) return;
    if (!pointer.ok) throw Error("The commute mode and timing comparison is unavailable.");
    const {version} = await pointer.json();
    report = await json(new URL(version + "/report.json",base));
    if (report.atlas !== versions.atlas || report.day !== versions.day)
      throw Error("The commute comparison uses a different population or weekday.");
    const areas = ["Vancouver", "North Shore", ...Object.keys(report.census).filter(k => k !== "Vancouver" && k !== "North Shore")];
    home.replaceChildren(...areas.map(area => new Option(area,area)));
    home.value = heading === 0 ? "North Shore" : "Vancouver";
    mode.replaceChildren(...report.labels.modes.map((label,i) => new Option(label,String(i))));
    mode.value = "1";
    time.replaceChildren(...["All times", ...report.labels.departures].map((label,i) => new Option(label,String(i))));
    el("bridge-schedule-source").href = report.source;
    draw();
    panel.hidden = false;
    if (requested) {
      el("bridge-attribution").open = true;
      panel.open = true;
    }
  };
}

export function bridgeRoutingMetric(params, regional) {
  const requested=params.get("bridgeMetric");
  return regional&&["time","highway1"].includes(requested)?requested:null;
}

const playbackLayers={
  "discretionary-outings":"Added shopping and recreation drivers",
  "eastern-outings":"Drivers on eastern errands",
  "school-escorts":"School escorts by car",
  "weekday-attendance":"Additional on-site work drivers"
};

export function attachBridgeTraffic({root, versions, regional, json, workplace, external, locate, follow, followExternal, time, onRouting,
  timetable, activeLayers, followLayer, followChoice, showBus, focusQueue, drawQueue}) {
  const panel = el("bridge-traffic"), site = el("bridge-site"), direction = el("bridge-direction");
  const scenario = el("bridge-scenario"), window = el("bridge-window"), status = el("bridge-traffic-status");
  const params = new URLSearchParams(location.search);
  const loadCommuteSchedule = regional && commuteSchedule(root,versions,json,params.get("bridgeCommute") === "1");
  let report, pending, currentSite, pair, outside, comparison, observedAvailable;
  const metric=bridgeRoutingMetric(params,regional);
  const compareMetric=metric==="time"?null:"time";
  const routeName=metric==="highway1"?"observed Highway 1 times":metric==="time"?"road speeds":"constant speed";
  let lastMinute, playback, playbackView, lastLayers, queue, routeChoice;

  function updatePlayback(force=false){
    if(!playback||!playbackView||!panel.open)return;
    const active=activeLayers();
    const key=JSON.stringify(active);
    if(!force&&key===lastLayers)return;
    lastLayers=key;
    const {bridge,heading,hours,residents,incoming,observed}=playbackView;
    const index=playback.bridges.indexOf(bridge.key);
    if(index===-1)return;
    const sum=counts=>hours.reduce((total,h)=>total+counts[h],0);
    const rows=el("bridge-playback-rows");
    rows.replaceChildren();
    let total=0;
    function add(label,amount,example,action){
      const row=rows.insertRow();
      row.insertCell().textContent=label;
      row.insertCell().textContent=amount==null?"—":number(amount);
      const control=row.insertCell();
      if(example){
        const button=document.createElement("button");
        button.type="button";
        button.textContent=label==="Scheduled buses"?"View bus "+example[1]:"Follow a driver";
        button.setAttribute("aria-label",label==="Scheduled buses"?button.textContent:"Follow a driver · "+label);
        button.onclick=()=>action(example);
        control.append(button);
      }
      total+=amount??0;
    }
    function crossing(source){
      const {counts,examples}=source.sites[index];
      return [sum(counts[heading]),hours.map(h=>examples[heading][h]).find(Boolean)];
    }
    add("Recorded resident drivers",sum(residents));
    add("Incoming work drivers",incoming?sum(incoming):null);
    add("Scheduled buses",...crossing(playback.buses),([route,,minute])=>showBus(route,minute,bridge.point));
    let unavailable=!incoming;
    for(const [id,release] of Object.entries(active)){
      if(!release)continue;
      const data=playback.layers[id];
      const label=playbackLayers[id];
      if(data?.release===release)add(label,...crossing(data),followLayer);
      else{add(label,null);unavailable=true;}
    }
    const gap=sum(observed.counts)-total;
    el("bridge-playback-total").textContent=unavailable?
      "The rows shown account for "+number(total)+" vehicles. Some counts for this replay are unavailable.":
      number(total)+" modeled crossings · "+number(sum(observed.counts))+" counted"+
      (gap?" · "+number(Math.abs(gap))+(gap>0?" fewer in the model":" more in the model"):"")+".";
    el("bridge-playback-method").textContent="Buses use the "+playback.buses.date+
      " timetable and mapped route shapes. Each bus crossing counts once. Added car journeys use their published free-flow routes. "+
      "The traffic counters cover all vehicles, including visitors and commercial traffic.";
    el("bridge-playback").hidden=false;
    queue?.update({...playbackView,playback,active});
  }

  function updateClock(minute) {
    const clock = el("bridge-external-clock");
    clock.hidden = !outside?.presence;
    if (clock.hidden || !panel.open || minute === lastMinute) return;
    lastMinute = minute;
    const [inbound,work,home] = outside.presence[minute % 1440];
    clock.textContent = number(work) + " incoming workers at paid work · " +
      number(inbound) + " on the way to work · " + number(home) + " on the way home.";
  }

  function update() {
    if (!report) return;
    const bridge = report.sites.find(item => item.key === site.value);
    if (currentSite !== bridge) {
      const preferred = currentSite ? direction.value : params.get("bridgeDirection");
      direction.replaceChildren(...bridge.counters.map((row,i) => new Option(row.direction,String(i))));
      selected(direction,preferred);
      currentSite = bridge;
    }
    const heading = Number(direction.value), model = Number(scenario.value), observed = bridge.counters[heading];
    const inbound = outside?.sites[bridge.key];
    const residents = bridge.scenarios[model].counts[heading];
    const incoming = regional ? inbound?.counts[heading] : bridge.scenarios[3]?.counts[heading];
    const examples = bridge.scenarios[model].examples[heading];
    const hours = window.value === "am" ? [7,8] : window.value === "pm" ? [16,17] : Array.from(residents.keys());
    routeChoice?.(hours,window.value==="day"?"Full weekday":window.selectedOptions[0].textContent);
    playbackView={bridge,heading,hours,residents,incoming,observed};
    updatePlayback(true);
    const sum = counts => number(hours.reduce((n,h) => n + counts[h],0));
    el("bridge-period").textContent = observed.month + " " + observed.year + " · average weekday" +
      (observed.days ? " · " + observed.days + " weekdays" : "");
    el("bridge-source").href = bridge.source ?? report.source;
    el("bridge-source").textContent = bridge.source ? "B.C. Ministry of Transportation and Transit hourly counts" : "City of Vancouver permanent counters";
    el("bridge-attribution").hidden = !bridge.byHomePurpose;
    if (bridge.byHomePurpose) renderAttribution(report.evidence,bridge.byHomePurpose[heading],heading,hours);
    el("bridge-incoming").hidden = !incoming;
    const modelled = incoming ? " · " + sum(incoming) + " incoming work drivers" : "";
    el("bridge-totals").textContent = sum(observed.counts) + " observed · " + sum(residents) + " resident drivers" +
      modelled + ".";
    el("bridge-external-stock").hidden = !outside;
    if (outside) {
      const required = outside.requiredCrossing;
      const duration = required?.medianRoadMinutes === undefined ? "" :
        " The median is " + number(required.medianDiaryMinutes) + " minutes in the schedules and " +
        number(Math.round(required.medianRoadMinutes)) + " minutes using " + routeName + ".";
      const fit = required?.legs ? " Of " + number(required.legs) +
        " road-connected car legs that need a bridge, " + number(required.fits) + " fit their travel time." + duration : "";
      el("bridge-external-stock").textContent = number(outside.attending) + " of " + number(outside.stock) +
        " workers from outside the resident roster attend jobs across the four municipalities on this simulated day." + fit;
    }
    updateClock(Math.floor(time()));
    const covered = report.coverage[model], commuters = report.coverage[3];
    const reach = "Both endpoints are within " + number(report.connectorMetres) + " m of the network for " +
      number(covered.snapped) + " of " + number(covered.legs) + " resident driving legs";
    const speed = metric==="highway1" ?
      "The 2022 study adjusts directed Highway 1 road costs between Lynn Valley Road and McGill Street in seven measured departure hours. "+
      "Trips use the costs for their departure hour. Other roads and hours use free-flow speeds." :
      metric==="time" ? "Driving paths minimize time using mapped limits and defaults by road class. " +
      "The comparison uses free-flow speeds." : "The speed ceiling is " + number(report.speed) + " m/min.";
    const speedSource=el("bridge-speed-source");
    speedSource.hidden=metric!=="highway1";
    if(metric==="highway1")speedSource.href=report.routing.source;
    el("bridge-coverage").textContent = regional ?
      "The replay covers people who live in Vancouver, UBC and the North Shore. " + reach + ". " + speed :
      (report.versions.incomingStreets ? "Residents use city streets. Incoming workers use the regional graph. " :
        "Both groups use the city street graph. ") + reach + " and " +
      number(commuters.snapped) + " of " + number(commuters.legs) + " incoming work legs. " +
      (report.incomingCityCoverage ? "With city streets alone, " + number(report.incomingCityCoverage.snapped) +
        " incoming legs have both endpoints within reach. " : "") + speed;
    el("bridge-locate").onclick = () => locate(bridge.point);
    const other = el("bridge-other-coverage");
    other.hidden = bridge.key !== "LionsGateBridge";
    if (!other.hidden) {
      const comparison = new URLSearchParams({bridge:bridge.key,bridgeDirection:heading,bridgeWindow:window.value});
      if (!regional) comparison.set("coverage","region");
      other.href = "cityday.html?" + comparison;
      other.textContent = regional ? "Compare the municipal replay" : "Compare the regional replay";
    }
    const body = el("bridge-hours");
    body.replaceChildren();
    for (const h of hours) {
      const row = body.insertRow(), time = String(h).padStart(2,"0") + ":00";
      row.insertCell().textContent = time;
      row.insertCell().textContent = number(observed.counts[h]);
      const driver = row.insertCell(), example = examples[h];
      if (example) {
        const button = document.createElement("button");
        button.textContent = number(residents[h]);
        button.setAttribute("aria-label", "Follow a resident crossing during " + time);
        button.onclick = () => follow(example, model);
        driver.append(button);
      } else driver.textContent = number(residents[h]);
      if (incoming) {
        const cell = row.insertCell(), worker = inbound?.examples[heading][h];
        if (worker) {
          const button = document.createElement("button");
          button.textContent = number(incoming[h]);
          button.setAttribute("aria-label", "Follow an incoming worker crossing during " + time);
          button.onclick = () => followExternal(worker,outside);
          cell.append(button);
        } else cell.textContent = number(incoming[h]);
      }
    }
    const url = new URL(location.href);
    for (const [key, select] of [["bridge",site],["bridgeDirection",direction],["bridgeWindow",window],["bridgeScenario",scenario]])
      url.searchParams.set(key,select.value);
    history.replaceState(null,"",url);
    const compared = comparison?.sites.find(item => item.key === bridge.key);
    el("bridge-routing-pair").hidden = !compared;
    if (compared) {
      const alternate = new URL(url);
      if (compareMetric) alternate.searchParams.set("bridgeMetric",compareMetric);
      else alternate.searchParams.delete("bridgeMetric");
      const count = sum(compared.scenarios[0].counts[heading]), current = sum(residents);
      el("bridge-route-counts").textContent = metric==="highway1" ?
        count+" resident drivers at free-flow speeds · "+current+" with observed Highway 1 times." :
        (metric?count:current) + " resident drivers at constant speed · " + (metric?current:count) + " using road speeds.";
      const link = el("bridge-routing-link");
      link.href = alternate;
      link.textContent = metric==="highway1" ? "Replay free-flow road speeds" : metric ? "Replay constant speed" : "Replay road speeds";
    }
    el("bridge-highway1-pair").hidden=!observedAvailable;
    if(observedAvailable){
      const hourly=new URL(url);
      hourly.searchParams.set("bridgeMetric","highway1");
      el("bridge-highway1-link").href=hourly;
    }
    const paired = pair?.other.sites.find(item => item.key === bridge.key);
    el("bridge-workplace-pair").hidden = !paired;
    const refinement = el("bridge-downtown-link-row");
    refinement.hidden = !pair?.refinement;
    if(pair?.refinement){
      const href=new URL(url);
      href.searchParams.delete("dayRun");
      href.searchParams.set("workplaceRun",pair.refinement);
      href.searchParams.set("workplaceBasis","census");
      layersForNewDay(href.searchParams);
      const link=el("bridge-downtown-link");
      link.href=href;
      link.textContent=pair.easternAllocations?"Replay the 2025 workplace fit":
        pair.rows?"Replay jobs in Burnaby and New Westminster":"Replay the downtown workplace fit";
    }
    const fit=el("bridge-downtown-fit");
    fit.hidden=!pair?.rows;
    if (paired) {
      const census = pair.basis === "census";
      url.searchParams.set("workplaceRun",pair.id);
      url.searchParams.set("workplaceBasis",census ? "original" : "census");
      layersForNewDay(url.searchParams);
      url.searchParams.delete("street");
      url.searchParams.delete("edge");
      url.searchParams.delete("at");
      const link = el("bridge-workplace-link");
      link.href = url;
      const baseLabel=pair.basisLabels?.original??"Original workplaces";
      const fittedLabel=pair.basisLabels?.census??"Census workplaces";
      link.textContent = "Replay " + (census ? baseLabel : fittedLabel).toLowerCase();
      const counterpart = sum(paired.scenarios[0].counts[heading]);
      el("bridge-workplace-basis").textContent =
        (census ? counterpart : sum(residents)) + " with " + baseLabel.toLowerCase() + " · " +
        (census ? sum(residents) : counterpart) + " with " + fittedLabel.toLowerCase() + ".";
    }
    if(pair?.rows){
      el("bridge-downtown-summary").textContent=number(pair.swaps)+
        " pairs exchange existing job sites within the same occupation group. The original diary windows are checked against roads, paths and scheduled transit.";
      const body=el("bridge-downtown-rows");
      body.replaceChildren();
      const pct=(n,total)=>(100*n/Math.max(1,total)).toFixed(1)+"%";
      for(const row of pair.rows){
        const line=body.insertRow();
        for(const value of [row.home,pct(row.survey[0],row.survey[0]+row.survey[1]),pct(row.before,row.total),pct(row.after,row.total)])
          line.insertCell().textContent=value;
      }
      el("bridge-downtown-example").onclick=()=>follow(pair.example);
      el("bridge-downtown-source").href=pair.source;
    }
    const east=el("bridge-eastern-fit");
    east.hidden=!pair?.easternAllocations;
    if(pair?.easternAllocations){
      const body=el("bridge-eastern-rows");
      body.replaceChildren();
      for(const row of pair.easternAllocations){
        for(const destination of Object.keys(row.target)){
          const line=body.insertRow();
          for(const value of [row.home,destination,number(row.observed[destination]),number(row.target[destination]),number(row.after[destination])])
            line.insertCell().textContent=value;
        }
      }
      const links=el("bridge-eastern-examples");
      links.replaceChildren();
      for(const [city,[da,i,start,duration]] of Object.entries(pair.easternExamples)){
        const href=new URL(url);
        for(const [key,value] of Object.entries({workplaceRun:pair.id,workplaceBasis:"census",bridgeMetric:"highway1",
          da,person:i+1,minute:start+Math.floor(duration/2),follow:1}))href.searchParams.set(key,value);
        const link=document.createElement("a");
        link.textContent="Follow a commute to "+city;
        link.href=href;
        links.append(link,document.createTextNode(" "));
      }
      el("bridge-eastern-source").href=pair.source;
    }
  }

  async function counts(choice, optional=false) {
    const id = [versions.atlas, versions.day, versions.streets].join("_") + (choice?"_"+choice:"");
    const response = await fetch(root + id + ".json");
    if(optional&&response.status===404)return null;
    if(!response.ok)throw Error("This bridge comparison is unavailable.");
    const pointer = await response.json();
    const data = await json(root + pointer.version + "/counts.json");
    if(Object.entries(versions).some(([k,v])=>data.versions[k]!==v)||
       (data.routing?.metric??null)!==choice ||
       (choice && !data.routing.profileDigest))
      throw Error("This report uses a different population, weekday, street network or speed profile.");
    return data;
  }

  function checkRouting(other) {
    if (report.routing?.profileDigest !== other?.routing?.profileDigest)
      throw Error("These crossing counts use different road speeds.");
  }

  function sameObservations(other) {
    return other&&other.sourceDigest===report.sourceDigest&&other.ironworkersDigest===report.ironworkersDigest;
  }

  async function loadPlayback(){
    const folder=new URL("../bridge-layers/",new URL(root,location.href));
    const key=[versions.atlas,versions.day,versions.streets].join("_");
    const response=await fetch(new URL(key+".json",folder));
    if(response.status===404)return;
    if(!response.ok)throw Error("The active replay bridge counts are unavailable.");
    const {version}=await response.json();
    const counts=await json(new URL(version+"/counts.json",folder));
    if(counts.schema!==1||counts.versions.transit!==timetable||
       Object.entries(versions).some(([k,v])=>counts.versions[k]!==v)||
       (metric&&counts.roads.profileDigest!==(report.routing.baselineDigest??report.routing.profileDigest)))
      throw Error("The additional crossings use a different weekday, timetable or road profile.");
    playback=counts;
    const details=el("bridge-playback");
    if(params.get("bridgePlayback")==="1")details.open=true;
    details.ontoggle=()=>{
      const url=new URL(location.href);
      if(details.open)url.searchParams.set("bridgePlayback","1");else url.searchParams.delete("bridgePlayback");
      history.replaceState(null,"",url);
    };
    updatePlayback(true);
    try{
      const {loadBridgeQueue}=await import("./bridge-queue.js");
      queue=await loadBridgeQueue({root,versions,json,profileDigest:counts.roads.profileDigest,
        time,focus:focusQueue,draw:drawQueue,bridgeOpen:()=>panel.open});
      updatePlayback(true);
    }catch(error){status.textContent=error.message;}
  }

  async function open() {
    if (!panel.open) return;
    if (report) { update(); return; }
    if (pending) return;
    status.textContent = "Loading bridge counts…";
    try {
      pending = counts(metric);
      report = await pending;
      onRouting?.(report.routing);
      site.replaceChildren(...report.sites.map(item => new Option(item.name,item.key)));
      const labels = regional ? report.labels : report.labels.slice(0,3);
      scenario.replaceChildren(...labels.map((name,i) => new Option(name,String(i))));
      scenario.value = String(labels.length - 1);
      el("bridge-scenario-label").hidden = labels.length === 1;
      selected(site,params.get("bridge"));
      selected(scenario,params.get("bridgeScenario"));
      selected(window,params.get("bridgeWindow"));
      el("bridge-traffic-results").hidden = false;
      status.textContent = "";
      update();
      if(regional&&metric==="highway1")loadBridgeChoice(root,versions,report.routing,json,followChoice).then(loaded=>{
        if(loaded){routeChoice=loaded;update();}
      }).catch(error=>{
        el("bridge-choice").hidden=false;
        el("bridge-choice-status").textContent=error.message;
      });
      if(timetable)loadPlayback().catch(error=>{status.textContent=error.message;});
      if (loadCommuteSchedule) loadCommuteSchedule(Number(direction.value))
        .catch(error => { status.textContent = error.message; });
      if(regional)counts(compareMetric,true).then(alternative=>{
        if(sameObservations(alternative)&&
           (metric!=="highway1"||alternative.routing.profileDigest===report.routing.baselineDigest)){
          comparison=alternative;
          update();
        }
      }).catch(error=>{status.textContent=error.message;});
      if(metric==="time")counts("highway1",true).then(alternative=>{
        observedAvailable=sameObservations(alternative)&&alternative.routing.baselineDigest===report.routing.profileDigest;
        if(observedAvailable)update();
      }).catch(error=>{status.textContent=error.message;});
      if (workplace) workplace(metric).then(result => {
        if (!result) return;
        checkRouting(result.other);
        pair = result;
        update();
      })
        .catch(error => { status.textContent = error.message; });
      if (external) external(metric).then(result => {
        if (!result) return;
        checkRouting(result);
        outside = result;
        update();
      })
        .catch(error => { status.textContent = error.message; });
    } catch (error) {
      status.textContent = "Bridge counts unavailable for this weekday. " + error.message;
    } finally { pending = null; }
  }

  for (const control of [site,direction,scenario,window]) control.onchange = update;
  panel.hidden = false;
  panel.ontoggle = ()=>{open();queue?.atMinute(time());};
  if (params.has("bridge") || params.has("bridgeChoice")) { panel.open = true; open(); }
  return minute=>{updateClock(minute);updatePlayback();queue?.atMinute(minute);};
}
