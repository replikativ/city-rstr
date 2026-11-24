import {departureHour} from "./vancouver-network.js";

const el=id=>document.getElementById(id);
const releaseId=/^[a-f0-9]{20}$/;

export async function loadCorridorTimes(root,streets,requested,json) {
  if(requested&&requested!=="observed"&&!releaseId.test(requested))throw Error("Unknown road traffic release.");
  const parent=root+"drive-profile/";
  let version=requested;
  if(!version||version==="observed"){
    const response=await fetch(parent+streets+"_corridor-times.json");
    if(!response.ok){
      if(requested)throw Error("Observed corridor times are unavailable for this street network.");
      return null;
    }
    const pointer=await response.json();
    if(pointer.streets!==streets)throw Error("The road traffic pointer uses another street network.");
    version=pointer.version;
  }
  if(!releaseId.test(version))throw Error("Invalid road traffic release.");
  const directory=parent+"corridor-times/"+version+"/";
  const report=await json(directory+"report.json");
  if(report.streets!==streets)throw Error("The road traffic release uses another street network.");
  if(requested){
    const url=new URL(location.href);
    url.searchParams.set("roadTraffic",version);
    history.replaceState(null,"",url);
  }
  return {version,driving:directory+"profile.json",report,active:!!requested};
}

export function corridorEvidence(model,selected,locate,time,replayUrl){
  const panel=el("road-traffic"),selector=el("road-traffic-site"),link=el("road-traffic-switch");
  const {report,version,active}=model;
  const names={"granville-south":"Granville · Marpole",georgia:"West Georgia · Downtown",
    "granville-broadway":"Granville · South Granville"};
  panel.hidden=false;
  el("road-traffic-scope").textContent=report.sources.length===2
    ? "The profile uses 2015 GPS measurements on three city reaches and the 2022 Highway 1 study near Ironworkers."
    : "The profile uses 2015 GPS measurements on three city reaches.";
  el("road-traffic-source").href=report.sources[0].url;
  link.textContent=active?"Replay with baseline road speeds":"Replay with observed corridor times";
  const updateLink=()=>{
    const url=replayUrl();
    if(active)url.searchParams.delete("roadTraffic");
    else url.searchParams.set("roadTraffic",version);
    url.searchParams.set("roadSection",selector.value);
    link.href=url;
  };
  const render=(minute,force=false)=>{
    if(!panel.open)return;
    const site=report.sites[selector.selectedIndex],hour=departureHour(minute);
    updateLink();
    if(!force&&selector.dataset.hour===String(hour))return;
    selector.dataset.hour=hour;
    const range=String(hour).padStart(2,"0")+":00–"+String(hour+1).padStart(2,"0")+":00";
    const sample=el("road-traffic-hour");
    sample.textContent=range+" · about "+site.observedKmh[hour]+" km/h in the study";
    const rows=site.directions.map(({start,end,freeMinutes,modeledMinutes})=>{
      const row=document.createElement("tr"),name=document.createElement("th");
      name.scope="row";name.textContent=start+" → "+end;row.append(name);
      for(const minutes of [freeMinutes,modeledMinutes[hour]])row.insertCell().textContent=minutes.toFixed(1)+" min";
      return row;
    });
    el("road-traffic-directions").replaceChildren(...rows);
  };
  for(const site of report.sites)selector.add(new Option(names[site.id]??site.street,site.id));
  el("road-traffic-view").onclick=()=>locate(report.sites[selector.selectedIndex]);
  selector.onchange=()=>render(time(),true);
  panel.ontoggle=()=>render(time(),true);
  link.addEventListener("pointerdown",updateLink);
  link.addEventListener("focus",updateLink);
  if(report.sites.some(site=>site.id===selected))selector.value=selected;
  if(active)el("road-traffic-active").hidden=false;
  return render;
}

export async function workplaceDriveEvidence(root,tract,versions,json){
  const directory=root+"workplace-drives/";
  const response=await fetch(directory+tract+".json");
  if(response.status===404)return;
  if(!response.ok)throw Error("The workplace driving comparison is unavailable.");
  const {version}=await response.json();
  if(!releaseId.test(version))throw Error("Invalid workplace driving release.");
  const report=await json(directory+version+"/report.json");
  if(report.versions.tracts!==tract||!releaseId.test(report.traffic)||
     Object.entries(versions).some(([name,value])=>report.versions[name]!==value))
    throw Error("The workplace driving comparison uses different addresses.");
  const fmt=n=>n.toLocaleString("en-CA");
  const rows=el("workplace-driving-rows");
  for(const [label,hours] of [["All day",report.hourly],["07:00–09:00",report.hourly.slice(7,9)],
    ["16:00–18:00",report.hourly.slice(16,18)]]){
    const row=rows.insertRow(),header=document.createElement("th");
    header.scope="row";header.textContent=label;row.append(header);
    const sums=[0,0,0,0];
    for(const {trips,feasible} of hours){
      sums[0]+=trips;
      for(const [i,value] of feasible.entries())sums[i+1]+=value;
    }
    for(const total of sums)row.insertCell().textContent=fmt(total);
  }
  el("workplace-driving-scope").textContent=fmt(report.day.trips)+" single-mode driving legs tied to work have two city addresses. "+
    fmt(report.coverage.external)+" have a workplace outside Vancouver. The table counts drives that fit their original time windows. "+
    "At free-flow speeds, revised workplaces make "+fmt(report.day.gained)+" more legs feasible and "+
    fmt(report.day.lost)+" previously feasible legs miss their route or travel window.";
  if(report.example){
    const trip=report.example,url=new URL(location.href);
    for(const key of ["shop","visit","street","at","edge","look","camera"])url.searchParams.delete(key);
    for(const [key,value] of Object.entries({commute:"tracts",roadTraffic:report.traffic,roadClock:"street",da:trip.da,person:trip.index+1,
      minute:trip.start+0.5,follow:1}))url.searchParams.set(key,value);
    url.hash="workplace-driving";
    el("workplace-driving-follow").href=url;
    el("workplace-driving-trip").textContent=trip.baseline.toFixed(1)+" minutes at free-flow speeds · "+
      trip.measured.toFixed(1)+" minutes with measured corridor speeds.";
    el("workplace-driving-example").hidden=false;
  }
  const panel=el("workplace-driving");
  panel.hidden=false;
  if(location.hash==="#workplace-driving"){
    el("road-traffic").open=true;
    panel.open=true;
  }
}
