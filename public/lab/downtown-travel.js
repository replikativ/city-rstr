import {attachIncomingRoadCrossings} from "./incoming-crossings.js";

const el=id=>document.getElementById(id);
const fmt=n=>n.toLocaleString();

export class DowntownTravel{
  constructor(areas,load,getTime,commuters,outbound,transfers=false,loadIncoming=null,outboundTransit=null){
    this.commuters=commuters;
    this.outbound=outbound;
    this.outboundTransit=outboundTransit;
    this.transfers=transfers;
    this.panel=el("downtown");this.panel.hidden=false;
    const window=el("downtown-window"),home=el("downtown-home");
    const residents=document.createElement("optgroup");residents.label="City residents by neighbourhood";
    for(const [i,name] of areas.entries())residents.append(new Option(name,String(i)));
    home.append(residents);
    const update=()=>{
      this.last=null;
      const url=new URL(location.href);
      if(this.panel.open)url.searchParams.set("downtown",window.value);else url.searchParams.delete("downtown");
      if(this.panel.open&&["inbound","combined"].includes(home.value))url.searchParams.set("commuters",home.value);
      else url.searchParams.delete("commuters");
      history.replaceState(null,"",url);this.render(getTime());
    };
    const needWorkers=()=>["inbound","combined"].includes(home.value)||el("incoming").open;
    const loadWorkers=()=>{el("incoming-origin").hidden=!needWorkers();if(needWorkers())commuters.init().then(()=>{this.last=null;this.render(getTime());}).catch(e=>{
      el("commuter-stock").textContent=e.message;if(home.value==="inbound"||home.value==="combined")el("downtown-summary").textContent=e.message;
    });};
    home.onchange=()=>{update();loadWorkers();};window.onchange=update;
    el("incoming").ontoggle=loadWorkers;
    commuters.onCity=()=>{this.last=null;this.render(getTime());};
    const open=async()=>{
      update();if(!this.panel.open)return;loadWorkers();if(this.report)return;
      try{
        this.pending??=load();
        this.report=await this.pending;
        if(this.report.areas.join("|")!==areas.join("|"))throw Error("Downtown and resident geography differ.");
        this.render(getTime());
      }catch(e){this.report=null;this.pending=null;el("downtown-summary").textContent=e.message;}
      if(this.report&&loadIncoming&&!this.incomingPending){
        this.incomingPending=loadIncoming().then(data=>{
          if(data&&JSON.stringify(data.report.rail.observed)!==JSON.stringify(this.report.rail.observed))
            throw Error("The resident and incoming counts use different station observations.");
          if(data?.timingPresence)this.commuters.applyTiming(data.timingPresence);
          if(data?.loadHomeFit)this.commuters.applyHomeFit(data.loadHomeFit);
          this.scheduledIncoming=data;
          if(data){
            this.commuters.followWorker=data.followWorker;this.commuters.followDriver=data.followDriver;
            this.commuters.showScheduledFollow();
            if(data.crossings)this.crossings=attachIncomingRoadCrossings(data.crossings,!!data.report.homeFit,
              (group,person,minute)=>data.followDriver(group,person,minute,()=>true,true),data.followResident);
          }
        }).catch(e=>{this.incomingError=e.message;}).then(()=>{this.last=null;this.render(getTime());});
      }
    };
    this.panel.addEventListener("toggle",open);
    const qs=new URLSearchParams(location.search),selected=qs.get("downtown");
    if(["inbound","combined"].includes(qs.get("commuters")))home.value=qs.get("commuters");
    if(["am","pm","clock","day"].includes(selected)){window.value=selected;this.panel.open=true;}
    if(qs.has("roadGate")||location.hash==="#incoming-road-crossings")this.panel.open=true;
    if(this.panel.open)void open();
  }
  render(minute,market=this.market,tours=this.tours){
    this.market=market;this.tours=tours;
    if(!this.report||!this.panel.open)return;
    const window=el("downtown-window").value,area=el("downtown-home").value;
    const incoming=["inbound","combined"].includes(area);
    this.commuters.describe(minute);
    this.commuters.presence(minute,incoming||el("incoming").open);
    if(incoming&&!this.commuters.report){
      el("downtown-summary").textContent="Loading incoming workers…";el("downtown-modes").replaceChildren();return;
    }
    const hour=Math.floor(minute/60)%24;
    const rule=this.outbound?.commuteRule();
    const adjustment=rule==="tracts"?this.outbound.tractDelta:rule==="usual"?this.outbound.report.usualDelta:(rule==="local"||rule==="sites")?this.outbound.report.neighbourhoodFit.delta:null;
    const municipality=el("commuter-city").value;
    const key=[window,area,municipality,window==="clock"?hour:"",rule,market?.revision,tours?.mode()].join("/");
    if(key===this.last)return;
    this.last=key;
    const hours=window==="day"?Array.from({length:24},(_,h)=>h):window==="clock"?[hour]:window==="pm"?[16,17]:[7,8];
    this.crossings?.(hours);
    const {counts,modes,rail}=this.report;
    const timed=this.outboundTransit?.downtownDelta;
    const regionalRail=this.outboundTransit?.rail;
    const extraRail=regionalRail&&JSON.stringify(regionalRail.observed)===JSON.stringify(rail.observed)?regionalRail.matched:null;
    const trips=modes.map(()=>[0,0]),observed=[0,0],matched=[0,0];
    for(const h of hours){
      for(const [i,flows] of counts[h].entries()){
        if(area==="inbound"||(area!==""&&area!=="combined"&&i!==Number(area)))continue;
        for(let k=0;k<2;k++)flows[k].forEach((n,m)=>{
          const changed=tours?.flow(h,i,k)??0,mode=modes[m],effects=market?.effects;
          const shopping=mode==="Walking"?effects?.walkingFlow(h,i,k):mode==="Bicycle"?effects?.cyclingFlow(h,i,k):mode==="Car driver"?effects?.drivingFlow(h,i,k):0;
          const fitted=this.report.joint?0:(this.outbound?.report.delta[h][i][k][m]||0)+(adjustment?adjustment[h][i][k][m]:0);
          trips[m][k]+=n+fitted+(timed?.[h][i][k][m]??0)+
            (shopping??0)+(mode==="Bicycle"?changed:mode==="Car driver"?-changed:0);
        });
      }
      if(incoming){
        for(const group of this.commuters.groups()){
          for(let k=0;k<2;k++)group.flows[h][k].forEach((n,m)=>{trips[m][k]+=n;});
        }
      }
      for(let k=0;k<2;k++){
        observed[k]+=rail.observed[h][k];
        matched[k]+=rail.matched[h][k]+(extraRail?.[h][k]??0);
      }
    }
    const total=k=>trips.reduce((n,row)=>n+row[k],0);
    el("downtown-summary").textContent=fmt(total(0))+(incoming?" trips":" resident trips")+" arrive in Downtown and "+fmt(total(1))+" leave.";
    el("downtown-source-limit").hidden=!incoming;
    const rows=el("downtown-modes");rows.replaceChildren();
    for(const [m,name] of modes.entries()){
      const row=rows.insertRow();
      const unavailable=area==="inbound"&&(name==="Ride-hail"||name==="Taxi");
      for(const value of [name,...trips[m].map(v=>unavailable?"—":fmt(v))])row.insertCell().textContent=value;
    }
    el("downtown-stations").textContent="2025 average weekday, all riders · "+fmt(observed[0])+" alight and "+fmt(observed[1])+" board.";
    const basis=this.report.vehicleAccess?"Scheduled city-resident journeys with household vehicle access · ":
      this.transfers||this.report.transfers?"Scheduled city-resident journeys with up to one transfer"+
        (this.report.capacityChecked?" and bus capacity limits · ":" · "):
      this.report.capacityChecked?"Direct scheduled journeys with bus capacity limits, city residents · ":
      this.report.joint?"Direct scheduled journeys on the fitted weekday, city residents · ":
      "Direct scheduled journeys matched to the city-address baseline, all home neighbourhoods · ";
    const line=([alight,board])=>fmt(alight)+" alight and "+fmt(board)+" board.";
    const incomingReport=incoming&&this.scheduledIncoming?.report;
    const incomingPanel=el("downtown-incoming-rail"),status=el("downtown-incoming-status"),button=el("downtown-incoming-follow");
    incomingPanel.hidden=!(incomingReport||incoming&&this.incomingError);
    button.hidden=true;
    if(incomingReport){
      const series=municipality?incomingReport.railByOrigin[municipality]:incomingReport.rail.matched;
      const workers=[0,1].map(d=>hours.reduce((n,h)=>n+(series?.[h][d]??0),0));
      el("downtown-matched").textContent=area==="combined"?"Scheduled city residents and incoming workers · "+
        line(matched.map((n,i)=>n+workers[i])):"Scheduled incoming workers · "+line(workers);
      status.textContent=area==="combined"?"Incoming workers account for "+fmt(workers[0])+" alightings and "+fmt(workers[1])+" boardings.":
        "The model uses the dated transit schedule and the workers’ assigned commute windows.";
      const comparison=this.scheduledIncoming.comparison;
      el("downtown-timing").hidden=!comparison;
      if(comparison){
        const timing=incomingReport.timing,href=new URL(location.href),link=el("downtown-timing-link");
        const extra=timing?.stages.at(-1).extraMinutes;
        el("downtown-timing-status").textContent=timing?fmt(timing.added)+" more incoming work trips fit with up to "+
          extra+" extra minutes per trip and the same work shifts.":"";
        href.searchParams.set("incomingTransit",comparison);
        href.hash="downtown";
        link.href=href;
        link.textContent=timing?"Replay the original commute windows":
          incomingReport.homeFit?"Test timing with the original homes":
          incomingReport.transferComparison?"Test longer windows on the one-transfer replay":"Test longer commute windows";
      }
      const census=this.scheduledIncoming.durations;
      el("downtown-duration-check").hidden=!census;
      if(census){
        const row=census.retimedTowardWork,[original,extended,expected]=row.meanMinutes.map(n=>n.toFixed(1));
        el("downtown-duration-status").textContent="Among "+fmt(row.compared)+" retimed trips to work with comparable data, planned travel averaged "+
          original+" minutes originally and "+extended+" with longer windows. The Census benchmark averages "+expected+
          " minutes for the same mix of home municipalities and distance ranges.";
        el("downtown-duration-source").href=census.source;
      }
      const homeFit=incomingReport.homeFit,homeComparison=this.scheduledIncoming.homeComparison;
      el("downtown-home-fit").hidden=!homeComparison;
      if(homeComparison){
        const href=new URL(location.href),link=el("downtown-home-fit-link");
        el("downtown-home-fit-status").textContent=homeFit?fmt(homeFit.moved)+" workers exchange home census areas within their municipality. "+
          fmt(homeFit.added)+" trips gain an itinerary and "+fmt(homeFit.lost)+" lose one.":"";
        href.searchParams.set("incomingTransit",homeComparison);
        href.hash="downtown";
        link.href=href;
        link.textContent=homeFit?"Replay the original home locations":"Test Census-calibrated homes";
      }
      const driving=this.scheduledIncoming.drive,roadNote=el("downtown-incoming-driving");
      roadNote.hidden=!driving;
      if(driving){
        const fitted=homeFit?1:0;
        roadNote.textContent="Across the incoming cohort, "+fmt(driving.day.feasible[fitted])+" of "+fmt(driving.day.trips)+
          " driver trips fit their assigned windows at free-flow road speeds. "+
          (fitted?"The original homes fit "+fmt(driving.day.feasible[0])+". ":"")+
          "You can follow drivers from the worker inspector.";
      }
      const examples=municipality?incomingReport.examplesByOrigin?.[municipality]:incomingReport.examples;
      const example=examples?.[window==="pm"?"fromWork":"towardWork"];
      if(example){
        button.hidden=false;
        button.onclick=()=>this.scheduledIncoming.follow(example).catch(e=>{status.textContent=e.message;});
      }
    }else{
      el("downtown-matched").textContent=area==="inbound"?"Scheduled incoming worker counts are unavailable for this replay.":basis+line(matched);
      if(incoming&&this.incomingError)status.textContent=this.incomingError;
    }
  }
}
