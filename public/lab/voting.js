import {loadRouteGeometry} from "./regional-transit.js";
import {ScheduledPassengers} from "./transit-passenger.js";

const el=id=>document.getElementById(id);
const n=value=>value.toLocaleString("en-CA");
const layouts={hall:"City Hall only",centres:"City Hall and four community centres"};

async function showBallotEvidence(root){
  const response=await fetch(root+"voting/ballots-2025.json");
  if(response.status===404)return;
  if(!response.ok)throw Error("The anonymous ballot comparison is unavailable.");
  const {schema,source,official,candidates,all,groups}=await response.json();
  if(schema!==1)throw Error("The anonymous ballot comparison has an unexpected format.");
  const advance=groups.Advance;
  const addRow=(id,values)=>{
    const row=el(id).insertRow();
    for(const value of values)row.insertCell().textContent=value;
  };
  for(const [i,count] of all.marks.entries())
    addRow("voting-ballot-marks",[i,n(count),n(advance.marks[i])]);
  const name=id=>candidates[id].name.split(", ").reverse().join(" ");
  const advancePairs=new Map(advance.pairs.map(([a,b,count])=>[a+"/"+b,count]));
  for(const [a,b,count] of all.pairs.slice(0,5))
    addRow("voting-ballot-pairs",[name(a)+" and "+name(b),n(count),n(advancePairs.get(a+"/"+b)??0)]);
  el("voting-ballot-file").href=source;
  el("voting-ballot-official").href=official;
  el("voting-ballot-tables").hidden=false;
  el("voting-ballot-evidence").hidden=false;
}

export class Voting {
  constructor({version,report,day,places,load,routeData,refresh,draw,follow,focus,network,clock}){
    Object.assign(this,{version,report,day,places,load,refresh,draw,follow,focus,network,clock});
    this.cache=new Map();
    this.placeStart=places.length;
    this.offices=new Map(report.offices.map((site,i)=>[site.id,{...site,index:this.placeStart+i}]));
    for(const site of report.offices)places.push(site.anchor??site.position);
    this.passengers=new ScheduledPassengers({manifest:report.transit,routeData},places,refresh,e=>this.fail(e));
    el("voting-source").href=report.source;
    el("voting-data").href=report.locations;
    el("voting-ballots").href=report.ballotsSource;
    el("voting-daily").href=report.dailySource;
    el("voting-date-label").hidden=el("voting-date-source").hidden=!report.dates;
    el("voting-schedule-label").hidden=el("voting-schedule-source").hidden=!report.houseworkShift;
    if(report.houseworkShift){
      const source=document.createElement("a");
      source.href=report.schedulingSource;source.textContent="Activity scheduling research";
      el("voting-schedule-source").replaceChildren(
        "The housework comparison can move a task up to "+report.houseworkShift+" minutes within the same period at home. "+
        "Tasks keep their duration and order. Work, school, care, sleep and existing travel keep their times. ",source);
    }
    el("voting-on-way-option").hidden=el("voting-detour-source").hidden=!report.onWay;
    if(report.onWay){
      const source=document.createElement("a");
      source.href=report.onWay.source;source.textContent="TransLink trip diary";
      el("voting-detour-source").replaceChildren(
        "A stop on the way home uses the original departure time and mode. A walk or drive can use up to "+
        report.onWay.maxExtension+" minutes of immediately following free time at home. ",source);
    }
    el("voting-date").onchange=()=>this.enable(this.layout,el("voting-date").value).catch(error=>this.fail(error));
    el("voting-schedule").onchange=()=>this.enable(this.layout,this.date,el("voting-schedule").value).catch(error=>this.fail(error));
    el("voting-layout").onchange=()=>this.enable(el("voting-layout").value).catch(error=>this.fail(error));
    el("voting-site").onchange=()=>this.selectSite(Number(el("voting-site").value));
    el("voting-locate").onclick=()=>{if(this.site)this.focus(this.site.position);};
    el("voting-follow-housework").onclick=()=>{
      if(this.choreExample)this.follow(...this.choreExample).catch(error=>this.fail(error));
    };
    el("voting-follow-detour").onclick=()=>{
      if(this.detourExample)this.follow(...this.detourExample).catch(error=>this.fail(error));
    };
    for(const button of el("voting-steps").querySelectorAll("button"))button.onclick=()=>{
      if(!this.example)return;
      const [d,i,,,,start,there,leave,back,,,ready]=this.example;
      const minutes=[start+there/2,(start+there+(ready??leave))/2,leave+back/2];
      const minute=minutes[Number(button.value)];
      this.follow(this.day.das[d],i,minute).catch(error=>this.fail(error));
    };
    el("voting-controls").hidden=false;el("voting-status").textContent="";
  }

  showComparison({demand,registrars,paired,layouts:keys}){
    const {report}=this;
    el("voting-method").textContent=n(demand)+" synthetic residents share both layouts. "+
      "Each layout has "+registrars+" registrars. "+
      n(report.officialAdvanceBallots)+" ballots were officially counted across the two advance dates.";
    el("voting-pair").hidden=!paired;
    if(paired)el("voting-pair").textContent="Of the "+n(paired.both)+" who can reach a poll in both layouts, "+n(paired.shorter)+
      " travel less with five sites, "+n(paired.same)+" travel the same amount and "+n(paired.longer)+" travel longer.";
    const comparison=el("voting-comparison");
    comparison.replaceChildren();
    for(const [key,label] of Object.entries(layouts)){
      const row=comparison.insertRow(),data=report.results[keys[key]];
      for(const value of [label,n(data.trips),n(data.cast),n(data.trips-data.cast),n(data.medianTravel)+" min"])
        row.insertCell().textContent=value;
    }
    const append=(body,label,hall,centres)=>{
      const row=body.insertRow();
      for(const value of [label,n(hall.assigned),n(hall.cast),n(centres.cast)])row.insertCell().textContent=value;
    };
    for(const [group,id] of [["area","voting-area-rows"],["age","voting-age-rows"],["employment","voting-employment-rows"]]){
      const first=report.results[keys.hall][group],second=report.results[keys.centres][group],body=el(id);
      body.replaceChildren();
      for(const key of Object.keys(first).sort())append(body,key,first[key],second[key]);
    }
  }

  fail(error){el("voting-status").textContent=error.message;}

  async enable(layout,date=this.date??this.report.defaultDate,schedule=this.schedule){
    const control=el("voting-layout"),dateControl=el("voting-date"),scheduleControl=el("voting-schedule");
    control.disabled=dateControl.disabled=scheduleControl.disabled=true;
    try{
      const original=this.report.dates?.[date]??{...this.report,layouts:{hall:"hall",centres:"centres"}};
      const revised=["flex","on-way"].includes(schedule)?original[schedule]:null;
      const config=revised?{...original,...revised}:original;
      const variant=config.layouts[layout];
      if(variant&&!this.cache.has(variant)){
        const source=await this.load(variant),rows=[],byPerson=new Map(),bySite=new Map();
        if(source.length!==this.report.results[variant].trips)throw Error("The voting itinerary count differs from the report.");
        for(const data of source){
          const [d,i,home,stored]=data,id=data[10],site=this.offices.get(id),key=d+"/"+i;
          if(!site||site.place!==stored||home<0||home>=this.report.basePlaces||!this.day.das[d]||byPerson.has(key))
            throw Error("The voting itineraries and weekday differ.");
          const row=data.slice();row[3]=site.index;
          byPerson.set(key,row);
          if(!bySite.has(id))bySite.set(id,[]);
          bySite.get(id).push(row);
          const [,,,,mode,start,there,leave,back]=row;
          const origin=row[14]?.[0];
          if(origin!==undefined&&(origin<0||origin>=this.report.basePlaces))throw Error("A polling detour has no mapped origin.");
          rows.push([d,i,home,site.index,"Voting",mode,start,there,leave-start-there,back,origin]);
        }
        this.cache.set(variant,{roadTrips:{rows,report:this.report},byPerson,bySite});
      }
      const policy=revised?schedule:"recorded";
      if(this.date!==date||this.schedule!==policy)this.showComparison(config);
      this.date=date;
      this.schedule=policy;
      this.layout=layout;
      this.active=!!variant;
      Object.assign(this,this.cache.get(variant));
      this.result=this.report.results[variant];
      const summary=el("voting-rescheduled"),changes=this.result?.housework,detours=this.result?.detours;
      summary.hidden=!(changes||detours);
      if(changes)summary.textContent=n(changes.added)+" more residents can reach a poll. "+
        n(changes.tasks)+" tasks move, with a median shift of "+n(changes.medianShift)+" minutes.";
      if(detours)summary.textContent=n(detours.added)+" more residents can reach a poll on the way home, "+
        n(detours.fromWork)+" directly from work. The median delay arriving home is "+n(detours.medianLater)+" minutes.";
      const sites=el("voting-site"),selectedSite=this.site?.id;
      sites.replaceChildren(...Object.keys(this.result?.sites??{}).map(Number).map(id=>
        new Option(this.offices.get(id).position[3],String(id))));
      this.selectSite(this.result?.sites[selectedSite]?selectedSite:(this.result?200:null));
      el("voting-live").hidden=!this.active;
      const url=new URL(location.href);
      url.searchParams.delete("voting");
      url.searchParams.delete("votingSchedule");
      if(this.active){
        url.searchParams.set("votingRun",this.version);url.searchParams.set("votingLayout",layout);
        if(this.date)url.searchParams.set("votingDate",this.date);
        if(revised)url.searchParams.set("votingSchedule",policy);
      }else for(const key of ["votingRun","votingLayout","votingSite","votingDate"])url.searchParams.delete(key);
      history.replaceState(null,"",url);
      el("voting-status").textContent="";
      if(this.active)this.network().then(this.refresh).catch(error=>this.fail(error));
      this.refresh();
    }finally{
      control.disabled=dateControl.disabled=scheduleControl.disabled=false;control.value=this.layout??"";
      if(this.date)dateControl.value=this.date;
      scheduleControl.value=this.schedule??"recorded";
    }
  }

  selectSite(id){
    if(id!==null&&!this.result?.sites[id])return;
    this.site=this.offices.get(id);
    el("voting-site").value=id===null?"":String(id);
    const staffing=el("voting-site-staff"),staff=this.result?.staff?.[id];
    staffing.hidden=!staff;
    if(staff)staffing.textContent=n(staff)+(staff===1?" registrar":" registrars");
    const options=this.bySite?.get(id)??[];
    this.example=options.reduce((best,row)=>!best||Math.abs(row[5]+row[6]-1010)<Math.abs(best[5]+best[6]-1010)?row:best,null);
    const moved=this.active?options.find(row=>row[13]):null;
    const task=moved?.[13][2].find(([old,,,revised])=>old!==revised);
    this.choreExample=task?[this.day.das[moved[0]],moved[1],task[3]]:null;
    el("voting-follow-housework").hidden=!task;
    const chain=options.find(row=>row[14]);
    this.detourExample=chain?[this.day.das[chain[0]],chain[1],chain[5]+chain[6]/2]:null;
    el("voting-follow-detour").hidden=!chain;
    el("voting-steps").hidden=!this.example;
    const url=new URL(location.href);
    if(id!==null)url.searchParams.set("votingSite",String(id));else url.searchParams.delete("votingSite");
    history.replaceState(null,"",url);
    this.lastMinute=null;
    this.refresh();
  }

  atMinute(time){
    const timeIndex=Math.floor(time)-240;
    if(this.lastMinute===timeIndex)return;
    this.lastMinute=timeIndex;
    if(!this.active){this.draw([]);return;}
    const sites=Object.entries(this.result.sites).map(([key,activity])=>{
      const id=Number(key),office=this.offices.get(id);
      return {id,point:office.position,waiting:activity.waiting[timeIndex],current:id===this.site?.id};
    });
    this.draw(sites);
    if(!this.site)return;
    const {arrivals,ballots,waiting}=this.result.sites[this.site.id];
    const count=values=>values.slice(0,timeIndex+1).reduce((total,part)=>total+part,0);
    el("voting-clock").textContent=n(waiting[timeIndex])+" waiting for registration · "+n(count(arrivals))+" arrived · "+n(count(ballots))+" cast by this minute";
  }

  delta(minute){return this.active?this.result.occupancyDelta[minute-240]:null;}

  replacesLeg(d,i,start){
    const row=this.active&&this.byPerson.get(d+"/"+i);
    return !!row?.[14]&&row[5]===start;
  }

  state(d,i,minute,graph){
    if(!this.active)return null;
    const row=this.byPerson.get(d+"/"+i);
    if(!row)return null;
    const [,,home,poll,mode,start,there,leave,back,cast,,ready,rides,housework,chain]=row;
    if(minute<start||minute>=leave+back){
      if(chain&&leave+back<=minute&&minute<chain[1]){
        const point=this.places[home];
        return {kind:"home",mode:"stop",a:point,p:point,activityLabel:"Back home after voting",detour:true};
      }
      if(!housework||minute<housework[0]||minute>=housework[1])return null;
      const tasks=housework[2],newTask=tasks.find(([,length,,revised])=>revised<=minute&&minute<revised+length);
      const oldTask=tasks.find(([old,length])=>old<=minute&&minute<old+length);
      if(newTask?newTask[0]===newTask[3]:!oldTask)return null;
      const activityLabel=newTask?(newTask[2]==="housework"?"Housework":"Occasional housework")+
        " · moved from "+this.clock(newTask[0]):"Free time at home · housework rescheduled";
      const point=this.places[home];
      return {kind:"home",mode:"stop",a:point,p:point,activityLabel};
    }
    const arrival=start+there,a=this.places[chain?.[0]??home],b=this.places[poll];
    if(arrival<=minute&&minute<leave){
      const activity=ready===null||minute<ready?"Waiting to register":minute<cast?"Marking a ballot":"Waiting to head home";
      return {outing:activity,kind:"voting",mode:"stop",a:b,p:b,start:arrival,dur:leave-arrival,description:activity+" · "+b[3],detour:!!chain};
    }
    const outgoing=minute<arrival;
    const leg=outgoing?{a,b,start,dur:there}:{a:b,b:this.places[home],start:leave,dur:back};
    const outward=chain?"Stopping to vote on the way home":"On the way to vote";
    const state={...leg,mode,detour:!!chain,kind:outgoing?"voting":"home",outing:outgoing?outward:cast===null?"Leaving before voting":"Returning from voting",
      metresPerMinute:mode==="walk"?this.report.walkMetresPerMinute:undefined};
    if(!rides)return state;
    const trip=[this.day.das[d],i,leg.start,leg.dur,outgoing?home:poll,outgoing?poll:home,...rides[outgoing?0:1]];
    const position=this.passengers.position(trip,minute,graph,true);
    if(position?.description.startsWith("Walking ")&&!position.routed){position.p=null;position.path=null;}
    return {...state,...position,scheduled:true,description:position?.description??"Loading the scheduled trip to or from the poll"};
  }
}

export async function attachVoting({root,versions,joint,day,places,json,refresh,draw,follow,focus,network,clock,onLoad}){
  const panel=el("voting"),params=new URLSearchParams(location.search);
  let version=params.get("votingRun");
  const requested=params.get("votingLayout")??params.get("voting");
  if(!version){
    const key=joint??[versions.atlas,versions.day,versions.streets].join("_");
    const response=await fetch(root+"voting/"+key+".json");
    if(response.status===404)return;
    if(!response.ok)throw Error("The voting scenario is unavailable.");
    ({version}=await response.json());
  }
  if(!/^[a-f0-9]{20}$/.test(version))throw Error("Invalid voting scenario release.");
  panel.hidden=false;
  let pending;
  const open=()=>{
    if(!panel.open||pending)return;
    pending=(async()=>{
      const directory=root+"voting/"+version+"/",report=await json(directory+"report.json");
      if(report.schema!==1||Object.entries(versions).some(([k,v])=>report.versions[k]!==v)||
        report.basePlaces>places.length||(report.joint??null)!==(joint??null))
        throw Error("The voting scenario uses a different population, day or road network.");
      const routeData=id=>loadRouteGeometry(json,root+"transit/"+report.transit.release+"/"+id+".json");
      const model=new Voting({version,report,day,places,load:name=>json(directory+name+".json"),routeData,refresh,draw,follow,focus,network,clock});
      onLoad(model);
      showBallotEvidence(root).catch(error=>{
        el("voting-ballot-status").textContent=error.message;
        el("voting-ballot-evidence").hidden=false;
      });
      try{
        const date=params.get("votingDate");
        await model.enable(Object.hasOwn(layouts,requested)?requested:"hall",
          Object.hasOwn(report.dates??{},date)?date:report.defaultDate,params.get("votingSchedule"));
        if(params.has("votingSite"))model.selectSite(Number(params.get("votingSite")));
      }catch(error){model.fail(error);}
    })().catch(error=>{el("voting-status").textContent=error.message;pending=null;});
    return pending;
  };
  panel.ontoggle=open;
  if(requested||params.has("votingRun")||params.has("votingDate")||params.has("votingSchedule")){panel.open=true;await open();}
}
