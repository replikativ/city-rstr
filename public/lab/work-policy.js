const el=id=>document.getElementById(id);
const fmt=n=>n.toLocaleString();
const clock=t=>String(Math.floor(t/60)%24).padStart(2,"0")+":"+String(t%60).padStart(2,"0");

function offerRank(da,i){
  let x=Number(da)^i;
  x=Math.imul(x^(x>>>16),0x85ebca6b);
  x=Math.imul(x^(x>>>13),0xc2b2ae35);
  return ((x^(x>>>16))&1)===0?50:100;
}

function remoteTour(person,tpl,minute,level){
  if(!person||person.labour!==1||person.occupation!==2||offerRank(person.d,person.i)>level)return null;
  const parts=tpl.parts,p=person.p;
  for(let k=2;k<parts.length-2;k++){
    const [before,out,work,back,after]=parts.slice(k-2,k+3);
    if(minute<out[0]||minute>=after[0]||work[2]!=="stop"||tpl.slots[work[3]]!=="job")continue;
    if(before[2]!=="stop"||after[2]!=="stop"||out[2]==="stop"||back[2]==="stop")continue;
    if(tpl.slots[before[3]]!=="home"||tpl.slots[after[3]]!=="home")continue;
    if(p[before[3]]!==person.home||p[after[3]]!==person.home||p[work[3]]<0||p[work[3]]===person.home)continue;
    if(person.diary.episodes.some(([s,,act])=>s>=work[0]&&s<back[0]&&act==="paid-work"))
      return {start:out[0],end:after[0],working:minute>=work[0]&&minute<back[0]};
  }
  return null;
}

export class WorkPolicy{
  constructor(day,load,refresh,compare,draw){
    this.day=day;this.draw=draw;this.refresh=refresh;this.compare=compare;this.level=50;this.area=-1;
    const panel=el("work-policy"),qs=new URLSearchParams(location.search);
    el("policy-level").value=qs.get("policy")==="100"?"100":"50";
    for(const name of day.areas)el("policy-area").add(new Option(name,name));
    if(day.areas.includes(qs.get("policyArea")))el("policy-area").value=qs.get("policyArea");
    const controls=()=>{
      this.area=day.areas.indexOf(el("policy-area").value);
      this.level=Number(el("policy-level").value);
    };
    const update=()=>{
      controls();
      const url=new URL(location.href);
      if(panel.open)url.searchParams.set("policy",String(this.level));else url.searchParams.delete("policy");
      if(panel.open&&this.area>=0)url.searchParams.set("policyArea",day.areas[this.area]);else url.searchParams.delete("policyArea");
      history.replaceState(null,"",url);
      this.refresh();
    };
    el("policy-level").onchange=update;el("policy-area").onchange=update;
    el("policy-example").onclick=async()=>{
      const examples=this.report.examples[this.level===50?0:1];
      const ex=this.area===-1?Object.values(examples)[0]:examples[this.area];
      if(ex)try{await this.compare(ex);}catch(e){el("policy-person").textContent=e.message;}
    };
    panel.ontoggle=async()=>{
      update();
      if(!panel.open||this.report)return;
      try{
        this.pending??=load().catch(e=>{this.pending=null;throw e;});
        this.report=await this.pending;
        if(this.report.population!==day.population||this.report.areas.join("|")!==day.areas.join("|"))throw Error("Scenario and resident geography differ.");
        el("policy-status").textContent="";
        el("policy-controls").hidden=false;
        el("policy-compute").textContent=fmt(this.report.population)+" resident schedules collapse to "+
          fmt(this.report.groups)+" weighted area itineraries. Raster ran the published counts on "+
          (this.report.backend==="jvm"?"the JVM":"device "+this.report.backend)+". "+
          (this.report.verifiedAgents?"All 1,440 minutes also matched a separate run with one work item per resident.":"All 1,440 minutes matched the individual schedule reference.");
        this.refresh();
      }catch(e){el("policy-status").textContent=e.message;}
    };
    controls();panel.hidden=false;if(qs.has("policy"))panel.open=true;
  }
  render(t,person){
    const panel=el("work-policy");
    if(!panel.open||!this.report){
      if(this.marker!=null)this.draw(null);
      this.marker=null;return;
    }
    const k=this.level===50?0:1,minute=Math.floor(t),idx=minute-240,n=this.day.areas.length;
    const base=this.day.occupancy[idx],delta=this.report.delta[k][idx],effects=this.report.effects[k];
    const describe=(before,change)=>fmt(before)+" → "+fmt(before+change)+" ("+(change>0?"+":"")+fmt(change)+")";
    el("policy-summary").textContent=fmt(effects[0])+" people switch work location, removing "+fmt(effects[1])+
      " commute legs and freeing "+fmt(effects[2])+" travel minutes over the study day.";
    el("policy-moving").textContent="Travelling across the study area · "+describe(base[n],delta[n]);
    const before=this.area>=0?base[this.area]:this.day.population-base[n]-base[n+1];
    const diff=this.area>=0?delta[this.area]:-delta[n]-delta[n+1];
    el("policy-placed").textContent=(this.area>=0?this.day.areas[this.area]:"All study areas")+" · at a known place · "+describe(before,diff);
    const examples=this.report.examples[k];
    el("policy-example").disabled=this.area<0?!Object.keys(examples).length:!examples[this.area];
    const tour=person&&remoteTour(person,this.day.templates[person.tpl],minute,this.level);
    const marker=tour?person.home:null;
    if(marker!==this.marker)this.draw(marker);
    this.marker=marker;
    el("policy-person").textContent=tour?"Selected worker · "+(tour.working?"working at home":"commute time released at home")+
      " · changed tour "+clock(tour.start)+"–"+clock(tour.end)+". The blue ring marks their scenario location.":"";
  }
}
