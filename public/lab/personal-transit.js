import {loadPassengerData,PublishedRiders} from "./work-transit.js";

const el=id=>document.getElementById(id);
const fmt=n=>(n??0).toLocaleString("en-CA");
const release=/^[a-f0-9]{20}$/;

function activity(key) {
  if(key==="job")return "workplace visit without recorded paid work";
  return key.replaceAll("-"," ");
}

class PersonalTransit extends PublishedRiders {
  constructor(config) {
    const {report,version,follow}=config;
    super({...config,status:el("personal-transit-status")});
    this.version=version;
    this.report=report;
    const {coverage,eligible,outcomes,excluded,bus,shared}=report;
    this.status.textContent=fmt(coverage.trips)+" of "+fmt(eligible)+" eligible trips fit the "+report.serviceDate+
      " timetable. "+fmt(outcomes.transfer)+" use a transfer.";
    el("personal-transit-method").textContent=fmt(outcomes.access)+" lack reachable stops, "+
      fmt(outcomes.schedule)+" lack service within the diary time, "+fmt(outcomes.capacity)+
      " lack modeled bus space and "+fmt(outcomes.sameCoordinates)+" have coincident endpoints. Before matching, "+
      fmt(excluded.unlocated)+" trips lacked an endpoint and "+fmt(excluded.mixed)+" included another travel mode.";
    el("personal-transit-capacity").textContent="The model reserves bus space for "+fmt(shared.workTrips)+" work trips, "+
      fmt(shared.outingBoardings)+" added outing journeys and "+fmt(shared.attendanceTrips)+" on-site work trips first. "+
      fmt(bus.atLimit)+" bus runs reach their estimated limit on at least one segment.";
    el("personal-transit-gtfs").href=report.gtfsSource;
    el("personal-transit-bus-source").href=bus.source;
    for(const [purpose,[eligible,matched]] of Object.entries(report.purposes)){
      const row=el("personal-transit-purposes").insertRow();
      for(const value of [activity(purpose),fmt(eligible),fmt(matched)])row.insertCell().textContent=value;
    }
    const examples=el("personal-transit-examples"),steps=el("personal-transit-steps");
    for(const [purpose,row] of Object.entries(report.examples)) {
      this.addExample("Follow trip · "+activity(purpose),row,examples,steps,follow);
    }
  }

  checkLayers(work,outings,attendance){
    const {shared}=this.report;
    const enabled=!!work&&[shared.work,shared.recordedWork].includes(work.version)&&
      !(outings?.active&&outings.report.transit&&outings.version!==shared.outings)&&
      !(attendance?.enabled&&attendance.version!==shared.attendance);
    if(enabled===this.enabled)return;
    this.enabled=enabled;
    const note=el("personal-transit-compatibility");
    note.hidden=enabled;
    note.textContent="This transit replay uses the bus reservations of its published work and outing runs.";
    for(const button of el("personal-transit").querySelectorAll("button"))button.disabled=!enabled;
  }
}

export async function attachPersonalTransit(root,versions,work,json,places,network,render,follow) {
  const folder=root+"personal-transit/";
  const params=new URLSearchParams(location.search);
  const pinned=params.get("personalTransit");
  let version=pinned;
  if(!version||version==="1"){
    const key=["atlas","day","streets"].map(k=>versions[k]).join("_");
    const response=await fetch(folder+key+".json");
    if(response.status===404)return null;
    if(!response.ok)throw Error("The personal transit replay is unavailable.");
    ({version}=await response.json());
  }
  if(!release.test(version))throw Error("Invalid personal transit release.");
  const base=folder+version+"/",report=await json(base+"report.json");
  if(Object.entries(versions).some(([key,value])=>report.versions[key]!==value)||
     report.versions.transit!==work.timetableVersion)
    throw Error("Personal transit uses a different weekday or timetable.");
  const service=await loadPassengerData(root,base,report,json);
  const rides=new PersonalTransit({report,...service,version,base,json,places,network,render,follow});
  const panel=el("personal-transit");
  panel.hidden=false;
  if(pinned){
    panel.open=true;
    const url=new URL(location.href);
    url.searchParams.set("personalTransit",version);
    history.replaceState(null,"",url);
  }
  return rides;
}
