const el=id=>document.getElementById(id);
const fmt=n=>n.toLocaleString();
const clock=t=>String(Math.floor(t/60)%24).padStart(2,"0")+":"+String(t%60).padStart(2,"0");

export class IncomingWorkers{
  constructor(root,version,load,places,ages,getTime,locate,areas,pinned){
    Object.assign(this,{root,version,load,places,ages,getTime,locate,areas,pinned});
    this.shards=new Map();
    el("commuter-city").onchange=()=>{el("commuter-id").value=1;this.choose();this.onCity?.();};
    el("commuter-id").onchange=()=>this.choose();
    el("commuter-locate").onclick=()=>{if(this.row)locate(places[this.row[1]]);};
    el("commuter-follow-schedule").onclick=async()=>{
      const control=el("commuter-follow-schedule"),status=el("commuter-follow-status"),worker=this.selectedWorker;
      const trace=this.selectedTrace();
      if(!trace)return;
      control.disabled=true;status.hidden=true;
      try{await trace(...worker,this.getTime(),()=>this.selectedWorker===worker);}
      catch(error){if(this.selectedWorker===worker){status.hidden=false;status.textContent=error.message;}}
      finally{control.disabled=false;}
    };
  }
  init(){
    if(!this.pending)this.pending=this.open().catch(e=>{this.pending=null;throw e;});
    return this.pending;
  }
  async open(){
    const {root,version}=this;
    const release=this.pinned??(await this.load(root+"commuters/"+version.atlas+"_"+version.version+".json")).version;
    this.base=root+"commuters/"+release+"/";
    const [report,timeline]=await Promise.all([this.load(this.base+"commuters.json"),this.load(this.base+"presence.json")]);
    if(report.versions.day!==version.version||report.versions.atlas!==version.atlas)throw Error("Incoming workers and resident releases differ.");
    if(this.timing&&this.timing.cities.join()!==timeline.cities.join())throw Error("The commuter clocks use different home municipalities.");
    const entries=Object.entries(report.groups).sort((a,b)=>a[1].name.localeCompare(b[1].name));
    this.report=report;this.timeline=timeline;
    el("commuter-city").disabled=false;
    el("commuter-city").replaceChildren(new Option("All home municipalities",""),...entries.map(([id,g])=>new Option(g.name,id)));
    el("commuter-method").textContent=(100*report.attendance).toFixed(0)+"% weekday attendance is transferred from the City’s 2023 survey of workers with a usual workplace. "+
      (100*report.downtownJobShare).toFixed(1)+"% of workplace weight goes to Downtown using the City’s 2016 job counts. Licences weight addresses within each area. The census donor supplies usual mode, departure-time and duration bands for comparable commuting distances.";
    await this.choose();
  }
  groups(){
    if(!this.report)return [];
    const city=el("commuter-city").value;
    return city?[this.report.groups[city]]:Object.values(this.report.groups);
  }
  applyTiming(timing){
    if(this.timeline&&timing.cities.join()!==this.timeline.cities.join())throw Error("The commuter clocks use different home municipalities.");
    this.timing=timing;this.presenceKey=null;this.lastMinute=null;
    this.describe(this.getTime());
  }
  applyHomeFit(load){
    this.homeFit=load;
    if(this.row)this.choose();
  }
  selectedTrace(){
    if(!this.row?.[8])return null;
    const mode=this.report.modes[this.row[4]];
    return mode==="Public transit"?this.followWorker:mode==="Car driver"?this.followDriver:null;
  }
  showScheduledFollow(){
    const control=el("commuter-follow-schedule");
    control.hidden=!this.selectedTrace();
  }
  presence(minute,visible){
    const output=el("commuter-now");
    output.hidden=!visible||!this.timeline;
    if(output.hidden)return;
    const m=Math.floor(minute)%1440,city=el("commuter-city").value,key=m+"/"+city;
    if(this.presenceKey===key)return;
    this.presenceKey=key;
    const counts=[0,0,0];
    this.timeline.cities.forEach((id,i)=>{
      if(!city||city===id){
        const extension=this.timing?.occupancyDelta[m][i][1];
        this.timeline.counts[m][i][1].forEach((n,k)=>counts[k]+=n+(extension?.[k]??0));
      }
    });
    output.textContent=clock(m)+" · incoming workers assigned to Downtown · "+fmt(counts[0])+
      " travelling to work, "+fmt(counts[1])+" at their workplace, "+fmt(counts[2])+" travelling home.";
  }
  async choose(){
    this.row=null;this.selectedWorker=null;el("commuter-locate").disabled=true;
    el("commuter-follow-status").hidden=true;
    this.showScheduledFollow();
    const city=el("commuter-city").value,groups=this.groups();
    const sum=k=>groups.reduce((n,g)=>n+g[k],0);
    el("commuter-stock").textContent=fmt(sum("stock"))+" usual workers from "+(city?groups[0].name:"Metro Vancouver origins outside the city")+
      " have jobs in Vancouver. "+fmt(sum("attending"))+" attend on this simulated weekday, including "+fmt(sum("downtownAttending"))+" in Downtown."+
      (city?"":" The census also records "+fmt(this.report.beyondMetro)+" workers from beyond Metro Vancouver.");
    el("commuter-id").disabled=!city;
    el("commuter-person").textContent=city?"Loading worker…":"Select a home municipality to inspect a worker.";
    el("commuter-shift").textContent="";
    if(!city)return;
    const n=groups[0].stock,idx=Math.min(n,Math.max(1,Math.trunc(el("commuter-id").valueAsNumber)||1))-1;
    el("commuter-id").max=n;el("commuter-id").value=idx+1;
    try{
      if(!this.shards.has(city))this.shards.set(city,this.load(this.base+city+".json").catch(e=>{this.shards.delete(city);throw e;}));
      const [shard,homeFit]=await Promise.all([this.shards.get(city),this.homeFit?.(city)]);
      if(el("commuter-city").value!==city||Number(el("commuter-id").value)!==idx+1)return;
      this.row=shard.people[idx];
      this.selectedWorker=[city,idx];
      this.showScheduledFollow();
      const [home,job,,age,mode]=this.row;
      el("commuter-person").textContent=groups[0].name+" worker "+fmt(idx+1)+" · home census area "+shard.homes[homeFit?.get(idx)??home]+
        " · age "+(this.ages[age-1]||"unavailable")+" · usual mode "+this.report.modes[mode]+" · workplace in "+this.areas[this.places[job][2]]+".";
      el("commuter-locate").disabled=false;this.lastMinute=null;this.describe(this.getTime());
    }catch(e){el("commuter-person").textContent=e.message;}
  }
  describe(minute){
    if(!this.row||this.lastMinute===Math.floor(minute))return;
    this.lastMinute=Math.floor(minute);
    const [,,,,,start,dur,span,attend,tpl]=this.row;
    if(!attend){el("commuter-shift").textContent="Away from the assigned workplace this weekday.";return;}
    const [city,index]=this.selectedWorker;
    const override=this.timing?.windows[city]?.[index];
    const leave=override?.[0]??start,workStart=start+dur,workEnd=workStart+span,home=override?.[1]??workEnd+dur;
    const now=leave+(minute-leave+1440)%1440;
    const atJob=this.report.workSpans[tpl].some(([a,b])=>now>=workStart+a&&now<workStart+b);
    const stage=now<workStart?"travelling to work":atJob?"at the assigned workplace":now<workEnd?"between workplace stops":
      now<home?"travelling from work":"outside the commute tour";
    el("commuter-shift").textContent="Leave home "+clock(leave)+" · arrive "+clock(workStart)+" · leave work "+clock(workEnd)+
      " · return "+clock(home)+". At the selected time, "+stage+".";
  }
}
