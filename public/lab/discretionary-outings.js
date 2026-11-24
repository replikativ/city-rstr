const el=id=>document.getElementById(id);
const fmt=n=>n.toLocaleString("en-CA");
const shopping="Shopping and personal errands";
const labels={"walk":"Walk","car-driver":"Drive","bike":"Bicycle","transit":"Transit"};

export function outingState(row,minute,places,siteOverride){
  if(!row)return null;
  const [,,home,site,purpose,mode,start,there,dwell,back]=row;
  const arrive=start+there,leave=arrive+dwell,end=leave+back;
  if(minute<start||minute>=end)return null;
  const a=places[home],b=places[siteOverride??site];
  const retail=purpose===shopping||purpose==="Shopping";
  const lunch=purpose==="Workplace lunch";
  const outing=lunch?"Lunch outing from work":retail?"Added shopping outing":"Added recreation outing";
  const kind=lunch?"restaurant":retail?"store":"recreation";
  if(minute>=arrive&&minute<leave)return {outing,kind,mode:"stop",a:b,p:b,start:arrive,dur:dwell};
  return minute<arrive?{outing,kind,mode,a,b,start,dur:there}:{outing,kind:lunch?"job":"home",mode,a:b,b:a,start:leave,dur:back};
}

export async function attachLunchWalks(root,joint,day,places,json,follow,refresh){
  const response=await fetch(root+joint.id+".json");
  if(response.status===404)return null;
  if(!response.ok)throw Error("The workplace lunch comparison is unavailable.");
  const {version}=await response.json();
  if(!/^[a-f0-9]{20}$/.test(version))throw Error("Invalid workplace lunch release.");
  const directory=root+version+"/",report=await json(directory+"report.json");
  if(report.joint!==joint.id||report.workplaces!==joint.workplaces["tract-workplaces"]||
     Object.entries(joint.versions).some(([k,v])=>report.versions[k]!==v))
    throw Error("The lunch walks use a different workplace weekday.");
  const panel=el("workplace-lunch"),toggle=el("lunch-replay"),button=el("lunch-follow");
  const summary=el("lunch-summary");
  const sum=xs=>xs.reduce((a,b)=>a+b,0);
  const model={version,report,active:false,rows:[],byPerson:new Map(),
    delta:minute=>model.active?report.occupancyDelta[minute-240]:null,
    state:(d,i,minute)=>model.active?outingState(model.byPerson.get(d+"/"+i),minute,places):null};
  const rows=el("lunch-count-rows");
  for(const site of report.crossings){
    const row=rows.insertRow(),name=document.createElement("a");
    name.href=site.source;name.textContent=site.name;row.insertCell().append(name);
    for(const value of [sum(site.baseline),sum(site.baseline)+sum(site.added),sum(site.observed)])
      row.insertCell().textContent=fmt(value);
  }
  summary.textContent=fmt(report.attendance)+" of "+fmt(report.target)+" additional restaurant walks fit existing on-site meals. "+
    "The fit draws from "+fmt(report.donorCount)+" observed urban weekday tours. It preserves paid work and uses part of an existing meal break for walking.";
  el("lunch-source").href=report.source;
  async function setActive(active){
    toggle.disabled=true;
    try{
      if(active&&!model.rows.length){
        const tours=await json(directory+"tours.json");
        if(tours.length!==report.attendance)throw Error("The lunch tours differ from the published count.");
        const byPerson=new Map(tours.map(row=>[row[0]+"/"+row[1],row]));
        if(byPerson.size!==tours.length)throw Error("A resident has more than one lunch tour.");
        model.rows=tours;model.byPerson=byPerson;
      }
      model.active=active;toggle.checked=active;
      const url=new URL(location.href);
      if(active)url.searchParams.set("lunch","walk");else url.searchParams.delete("lunch");
      history.replaceState(null,"",url);
      refresh();
    }finally{toggle.disabled=!report.attendance;}
  }
  const error=e=>{el("lunch-status").textContent=e.message;toggle.checked=model.active;};
  toggle.onchange=()=>setActive(toggle.checked).catch(error);
  button.onclick=()=>setActive(true).then(()=>{
    const [d,i,,,,,start,there]=model.rows[0];
    return follow(day.das[d],i,start+Math.min(there/2,1));
  }).catch(error);
  button.hidden=!report.attendance;toggle.disabled=!report.attendance;
  panel.hidden=false;
  if(location.hash==="#workplace-lunch"||new URLSearchParams(location.search).get("lunch")==="walk"){
    el("joint-weekday").open=true;panel.open=true;
  }
  if(toggle.disabled)return model;
  if(new URLSearchParams(location.search).get("lunch")==="walk")await setActive(true);
  return model;
}

export class DiscretionaryOutings {
  constructor(report,version,day,places,load,refresh,follow,schedule,prepareStreets,{pinned=false,shopFor}={}){
    Object.assign(this,{report,version,day,places,load,refresh,follow,pinned,shopFor,active:false});
    this.byPerson=new Map();
    this.examples=new Map();
    if(schedule)this.passengers=new ScheduledPassengers(schedule,places,refresh,e=>this.error(e));
    this.prepareStreets=prepareStreets;
    const area=el("outing-area");
    const scope=report.cityScope??"North Shore";
    area.add(new Option(scope,"all"));
    if(!report.cityScope)for(const name of new Set(report.metrics.map(row=>row[0])))area.add(new Option(name,name));
    el("outing-scope").hidden=!!report.cityScope;
    area.onchange=()=>this.draw();
    el("outing-replay").onchange=()=>this.enable(el("outing-replay").checked).catch(error=>this.error(error));
    el("outing-summary").textContent=fmt(report.attendance)+" added outings · "+
      (report.trips/report.residents).toFixed(2)+" recorded trips per "+(report.cityScope?"adult":"North Shore resident")+" · "+
      ((report.trips+report.attendance*2)/report.residents).toFixed(2)+" with added outings · "+
      report.surveyRate.toFixed(2)+" in the survey.";
    el("outing-source").href=report.source;
    if(report.cityScope){
      el("outing-caption").textContent="Walking trips to shops, citywide";
      el("outing-source").textContent="2023 Vancouver Transportation Survey, Figure 46";
      el("outing-timing-source").href=report.timeUse;
      el("outing-method").hidden=false;
      const walkShare=report.benchmark.walkShare.toLocaleString("en-CA",{style:"percent"});
      el("outing-model-target").textContent=fmt(report.attendance)+" of "+fmt(report.benchmark.volumeTarget)+
        " additional shopping walks fit the diaries. The target uses the survey’s "+walkShare+
        " walking share of the total shopping trip shortfall.";
      el("outing-donors").textContent=fmt(report.donorTours)+" recorded walk-to-shop outings from "+fmt(report.donorDiaries)+
        " Canadian urban weekday diaries supplied the timing and store visit lengths. The replay models visits to "+
        fmt(report.visitedVenues)+" named shops and assumes shop hours of 08:00–20:00.";
      if(report.pedestrianCheck)this.showPedestrianCheck(report.pedestrianCheck);
    }
    el("outing-controls").hidden=false;
    el("outing-status").textContent="";
    this.draw();
  }
  showPedestrianCheck({sites,radius}){
    const body=el("outing-count-rows"),sum=values=>values.reduce((a,b)=>a+b,0);
    for(const {name,date,source,base,added,observed} of sites){
      const row=body.insertRow(),link=document.createElement("a");
      link.textContent=name;
      link.href=source;
      link.title=date;
      row.insertCell().append(link);
      for(const value of [sum(base),sum(base)+sum(added),sum(observed)])row.insertCell().textContent=fmt(value);
    }
    el("outing-count-note").textContent="The City counted all pedestrian passages. The model counts walks passing within "+
      radius+" m with both endpoints outside the circle. The base includes reconstructed short walks. These sites were held out of the fit.";
    el("outing-count-check").hidden=false;
  }
  error(error){
    el("outing-status").textContent=error.message;
    el("outing-replay").checked=this.active;
  }
  async enable(active){
    const toggle=el("outing-replay");
    toggle.disabled=true;
    try{
      if(active&&!this.rows){
        const rows=await this.load();
        if(rows.length!==this.report.attendance)throw Error("The outing roster differs from the published counts.");
        const byPerson=new Map(),examples=new Map();
        for(const row of rows){
          const [d,i,home,,purpose,mode]=row;
          const key=d+"/"+i;
          if(byPerson.has(key))throw Error("A resident has more than one added outing.");
          byPerson.set(key,row);
          const area=this.report.cityScope??this.day.areas[this.places[home][2]];
          for(const scope of ["all",area]){
            const cell=JSON.stringify([scope,purpose,mode]);
            if(!examples.has(cell))examples.set(cell,row);
          }
        }
        Object.assign(this,{rows,byPerson,examples});
        if(this.passengers||this.report.cityScope)this.prepareStreets().then(this.refresh).catch(e=>this.error(e));
      }
      this.active=active;
      toggle.checked=active;
      const url=new URL(location.href);
      url.searchParams.delete("outings");
      if(active)url.searchParams.set("outingsRun",this.version);
      else url.searchParams.delete("outingsRun");
      history.replaceState(null,"",url);
      el("outing-status").textContent="";
      this.draw();
      this.refresh();
    }finally{toggle.disabled=this.pinned;}
  }
  draw(){
    const area=el("outing-area").value, table=el("outing-rows");
    const totals=new Map();
    for(const [municipality,purpose,mode,baseline,target,added] of this.report.metrics){
      if(area!=="all"&&area!==municipality)continue;
      const key=JSON.stringify([area,purpose,mode]);
      const [a,b,c]=totals.get(key)||[0,0,0];
      totals.set(key,[a+baseline,b+target,c+added]);
    }
    table.replaceChildren();
    for(const [key,[baseline,target,added]] of totals){
      const [,purpose,mode]=JSON.parse(key);
      const row=table.insertRow();
      for(const value of [purpose,labels[mode],fmt(baseline),fmt(baseline+added),fmt(target)])
        row.insertCell().textContent=value;
      const cell=row.insertCell(),example=this.examples.get(key);
      if(this.active&&example){
        const button=document.createElement("button");
        button.textContent="Follow";
        button.setAttribute("aria-label","Follow "+purpose.toLowerCase()+" by "+labels[mode].toLowerCase());
        button.onclick=()=>this.select(example);
        cell.append(button);
      }
    }
    if(!this.active)el("outing-example").hidden=true;
  }
  select(row){
    const [d,i,,site,,,start,there,dwell,back,,rides]=row;
    el("outing-example").hidden=false;
    el("outing-example-site").textContent=this.places[this.shopFor?.(d,i)??site][3];
    const steps=el("outing-steps");
    steps.replaceChildren();
    const rideMinute=([,,,,,,board,alight])=>Math.ceil(board/60)<alight/60?Math.ceil(board/60):(board+alight)/120;
    const items=[["Outward trip",rides?rideMinute(rides[0]):start+Math.floor(there/2)],
      ["At the destination",start+there+Math.floor(dwell/2)],
      ["Return trip",rides?rideMinute(rides[1]):start+there+dwell+Math.floor(back/2)]];
    for(const [label,minute] of items){
      const button=document.createElement("button");
      button.textContent=label;
      button.onclick=()=>this.follow(this.day.das[d],i,minute).catch(error=>this.error(error));
      steps.append(button);
    }
    steps.firstElementChild.click();
  }
  delta(minute){
    return this.active?this.report.occupancyDelta[minute-240]:null;
  }
  state(d,i,minute,network){
    if(!this.active)return null;
    const row=this.byPerson.get(d+"/"+i);
    const leg=outingState(row,minute,this.places,this.shopFor?.(d,i)),rides=row?.[11];
    if(!leg||leg.mode==="stop"||!rides)return leg;
    const [,,home,site]=row;
    const outward=leg.start===row[6];
    const trip=[this.day.das[d],i,leg.start,leg.dur,outward?home:site,outward?site:home,...rides[outward?0:1].slice(0,6)];
    const position=this.passengers.position(trip,minute,network,true);
    if(position?.description.startsWith("Walking ")&&!position.routed){
      position.p=null;
      position.path=null;
    }
    return {...leg,...position,scheduled:true,description:position?.description??"Loading scheduled transit"};
  }
}

export async function attachOutings(root,versions,day,places,json,refresh,follow,cycleVersion,prepareStreets,{pinned,shopFor}={}){
  const params=new URLSearchParams(location.search);
  const wanted=pinned??params.get("outingsRun");
  if(pinned&&params.has("outingsRun")&&params.get("outingsRun")!==pinned)
    throw Error("The grocery comparison requires its published shopping outings.");
  let version=wanted;
  if(!version){
    const response=await fetch(root+versions.atlas+"_"+versions.day+".json");
    if(response.status===404)return null;
    if(!response.ok)throw Error("The discretionary outings comparison is unavailable.");
    ({version}=await response.json());
  }
  if(!/^[a-f0-9]{20}$/.test(version))throw Error("The discretionary outing release is invalid.");
  const panel=el("discretionary-outings");
  panel.hidden=false;
  const directory=root+version+"/";
  // Other regional evidence remains available if the user never opens this comparison.
  const load=async()=>{
    const report=await json(directory+"report.json");
    if(Object.entries(versions).some(([k,v])=>report.versions[k]!==v))
      throw Error("The discretionary outings use a different weekday.");
    if(report.cycleProfile&&report.cycleProfile.version!==cycleVersion)throw Error("The outing bicycle graph differs from the replay.");
    const dir=report.transit&&new URL("../transit/"+report.transit.release+"/",new URL(root,document.baseURI)).href;
    const schedule=dir?{manifest:{routes:report.transit.routes},routeData:id=>loadRouteGeometry(json,dir+id+".json")}:null;
    return new DiscretionaryOutings(report,version,day,places,()=>json(directory+"tours.json"),refresh,follow,schedule,prepareStreets,
      {pinned:!!pinned,shopFor});
  };
  return {panel,load,activate:!!wanted||params.get("outings")==="fit"};
}
import {loadRouteGeometry} from "./regional-transit.js";
import {ScheduledPassengers} from "./transit-passenger.js";

