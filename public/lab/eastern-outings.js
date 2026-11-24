import {outingState} from "./discretionary-outings.js";

const el=id=>document.getElementById(id);
const n=value=>value.toLocaleString("en-CA");
const isRelease=id=>/^[a-f0-9]{20}$/.test(id);

class EasternOutings {
  constructor({version,report,day,places,load,refresh,follow}){
    Object.assign(this,{version,report,day,places,load,refresh,follow,active:false});
    const {constraint,cities,attendance}=report;
    el("eastern-outing-result").textContent=n(attendance)+" additional round trips · "+
      Object.entries(cities).map(([city,total])=>n(total)+" to "+city).join(" · ");
    el("eastern-outing-survey").textContent=n(constraint.assigned)+" recorded trips to these cities, "+
      n(constraint.assigned+constraint.attendance+attendance)+" with the added errands and on-site work, and "+n(constraint.check2025)+
      " in the 2025 survey. These are southbound totals across purposes and modes.";
    el("eastern-outing-source").href=report.source;
  }

  async enable(active){
    const toggle=el("eastern-outing-replay"),status=el("eastern-outing-status");
    toggle.disabled=true;
    try{
      if(active&&!this.rows){
        const rows=await this.load(),{basePlaces,sites,attendance}=this.report;
        const byPerson=new Map();
        if(rows.length!==attendance||this.places.length<basePlaces)throw Error("Eastern errands use a different day or place inventory.");
        const start=this.places.length;
        for(const source of rows){
          const [d,i,home,site]=source,key=d+"/"+i,k=site-basePlaces;
          if(!this.day.das[d]||byPerson.has(key)||home<0||home>=basePlaces||!sites[k])
            throw Error("The published eastern errand roster is inconsistent.");
          const row=source.slice();row[3]=start+k;
          byPerson.set(key,row);
        }
        for(const site of sites)this.places.push(site);
        this.byPerson=byPerson;
        this.rows=[...byPerson.values()];
        this.examples();
      }
      this.active=active;
      const url=new URL(location.href);
      url.searchParams.delete("easternOutings");
      if(active)url.searchParams.set("easternOutingRun",this.version);
      else url.searchParams.delete("easternOutingRun");
      history.replaceState(null,"",url);
      el("eastern-outing-examples").hidden=!active;
      status.textContent="";
      this.refresh();
    }catch(error){status.textContent=error.message;}
    finally{toggle.checked=this.active;toggle.disabled=false;}
  }

  examples(){
    const select=el("eastern-outing-example"),chosen=new Map();
    for(const row of this.rows){
      const [, , ,site,purpose]=row,place=this.places[site],city=this.day.areas[place[2]];
      const key=city+" · "+purpose;
      if(!chosen.has(key)){
        select.add(new Option(key+" · "+place[3],key));
        chosen.set(key,row);
      }
    }
    for(const button of el("eastern-outing-steps").querySelectorAll("button"))button.onclick=()=>{
      const [d,i,,,,,start,there,dwell,back]=chosen.get(select.value);
      const minutes=[start+there/2,start+there+dwell/2,start+there+dwell+back/2];
      this.follow(this.day.das[d],i,minutes[Number(button.value)]).catch(error=>{el("eastern-outing-status").textContent=error.message;});
    };
  }

  delta(minute){return this.active?this.report.occupancyDelta[minute-240]:null;}
  state(d,i,minute){return this.active?outingState(this.byPerson.get(d+"/"+i),minute,this.places):null;}
}

export async function attachEasternOutings({root,versions,workplaceRun,day,places,json,refresh,follow,onLoad}){
  const panel=el("eastern-outings"),status=el("eastern-outing-status");
  const params=new URLSearchParams(location.search);
  let version=params.get("easternOutingRun");
  const enabled=!!version||params.get("easternOutings")==="on";
  if(!version){
    const key=[versions.atlas,versions.day,versions.streets].join("_");
    const response=await fetch(root+key+".json");
    if(response.status===404)return;
    if(!response.ok)throw Error("The eastern errands release is unavailable.");
    ({version}=await response.json());
  }
  if(!isRelease(version))throw Error("Invalid eastern errands release.");
  panel.hidden=false;
  let pending;
  const open=()=>{
    if(!panel.open)return;
    pending??=(async()=>{
      const directory=root+version+"/";
      const report=await json(directory+"report.json");
      if(report.schema!==1||report.workplaceRun!==workplaceRun||report.basePlaces!==places.length||
         Object.entries(versions).some(([k,v])=>report.versions[k]!==v))
        throw Error("The eastern errands and the weekday use different releases.");
      const model=new EasternOutings({version,report,day,places,load:()=>json(directory+"tours.json"),refresh,follow});
      onLoad(model);
      const toggle=el("eastern-outing-replay");
      toggle.onchange=()=>model.enable(toggle.checked);
      el("eastern-outing-controls").hidden=false;status.textContent="";
      if(enabled)await model.enable(true);
    })().catch(error=>{status.textContent=error.message;pending=null;});
    return pending;
  };
  panel.ontoggle=open;
  if(enabled){panel.open=true;await open();}
}
