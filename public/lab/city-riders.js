import {activeWalks,onwardRide,rideTiming,ScheduledPassengers} from "./transit-passenger.js";
import {lngLat} from "./vancouver-network.js";

const el=id=>document.getElementById(id);
const count=n=>(n||0).toLocaleString();

export class CityRiders{
  constructor(services,load,release,versions,places,refresh,follow,das,pinned=false){
    Object.assign(this,{services,load,release,versions,refresh,follow,das,pinned});
    this.passengers=new ScheduledPassengers(services,places,refresh,e=>this.error(e));
    this.shards=new Map();
    this.walkRows=new Map();this.walkRequest=0;this.visibleWalkers=false;
    const map=services.map;
    map.addSource("rider-walkers",{type:"geojson",data:{type:"FeatureCollection",features:[]}});
    map.addLayer({id:"rider-walkers",type:"circle",source:"rider-walkers",paint:{
      "circle-color":["case",["get","boarding"],"#c79bff","#ffb483"],
      "circle-radius":["interpolate",["linear"],["zoom"],10,3,18,6],"circle-stroke-color":"#292031","circle-stroke-width":1.5}});
    map.on("click","rider-walkers",e=>{
      const {d,i}=e.features[0].properties;
      this.follow(das[d],i,services.getTime()).catch(error=>this.error(error));
    });
    el("rider-walk-follow").onclick=()=>{
      if(!this.walkExample)return;
      const [start,duration,d,i]=this.walkExample,now=services.getTime()*60;
      this.follow(das[d],i,(now>=start&&now<start+duration?now:start+duration/2)/60).catch(error=>this.error(error));
    };
    el("transit-panel").addEventListener("toggle",()=>{if(!el("transit-panel").open)this.refresh();});
    services.onReady=()=>this.init().catch(e=>this.error(e));
    services.onSelection=id=>this.showRoute(id);
    el("rider-follow").onclick=()=>this.followExample().catch(e=>this.error(e));
  }
  error(e){
    el("city-riders").hidden=false;
    el("rider-route").textContent=e.message;
  }
  async init(){
    this.pending??=this.open().catch(e=>{this.pending=null;throw e;});
    return this.pending;
  }
  async open(){
    const {riders,transit}=await this.release();
    this.version=riders;
    this.base="data/vancouver/transit-riders/"+riders+"/";
    const report=await this.load(this.base+"riders.json");
    if(report.versions.transit!==transit||Object.entries(this.versions).some(([k,v])=>report.versions[k]!==v))
      throw Error("Transit assignments and weekday releases differ.");
    this.report=report;this.areas=new Set(report.das);
    if(this.pinned){
      const [sample,starts]=await Promise.all([this.load(this.base+"sample.json"),this.load(this.base+"departures.json")]);
      this.sample=this.byPerson(sample,true);
      this.departures=new Set(starts.map(row=>row.join("/")));
      if(starts.length!==report.matched||this.departures.size!==starts.length)
        throw Error("The scheduled rider index differs from the combined weekday.");
    }
    el("city-riders").hidden=false;
    el("rider-coverage").textContent=count(report.matched)+" of "+count(report.total)+
      (this.pinned?" transit trips on the fitted weekday":" diary trips involving transit")+
      (report.transfers?" fit a scheduled journey. "+count(report.transfers.added)+" use one transfer.":" fit a direct scheduled ride.");
    const e=report.excluded;
    el("rider-method").textContent="A rider walks up to 800 m on the street network at each end. The model keeps the direct match when it fits. "+
      (report.transfers?"For other trips it tests a single change of vehicle within the same diary window. ":"")+
      count(e.schedule)+(report.transfers?" trips had no journey that fit, ":" trips had no direct service that fit, ")+count(e.access)+" lacked a reachable stop, "+
      count(e.unlocated)+" lacked a trip endpoint, "+count(e.samePlace)+" had coincident endpoints, and "+count(e.mixed)+" included another vehicle mode. "+
      (e.capacity?count(e.capacity)+" feasible journeys lacked space under the bus capacity check. ":"")+
      "These counts describe synthetic residents of Vancouver.";
    this.showRoute(el("transit-route").value);this.refresh();
  }
  showRoute(id){
    if(!this.report)return;
    const name=this.services.manifest.routes.find(r=>r.id===id)?.name;
    el("rider-route").textContent=name?count(this.report.byRoute[id])+
      (this.report.transfers?" modeled city-resident boardings on ":" matched resident trips on ")+name+".":"";
    const observed=this.report.observedWeekday[id];
    el("rider-observed").textContent=observed!=null?"TransLink recorded an average of "+count(observed)+
      " weekday boardings across this entire route in 2025, including transfers and people living outside Vancouver.":"";
    el("rider-follow").hidden=!this.report.examples[id];
    const request=++this.walkRequest;
    this.walkView=null;this.walkExample=null;this.refresh();
    el("rider-walk-peak").textContent="";
    if(!this.report.walking||!this.report.byRoute[id])return;
    this.loadWalks(id).then(view=>{
      if(request===this.walkRequest){
        this.walkView=view;
        if(view.peak){
          const {minute,count,templates,largestGroup}=view.peak;
          const clock=[Math.floor(minute/60)%24,minute%60].map(n=>String(n).padStart(2,"0")).join(":");
          el("rider-walk-peak").textContent="The busiest departure minute is "+clock+", with "+count+
            " trips drawn from "+templates+" diary "+(templates===1?"template":"templates")+". The most common template supplies "+largestGroup+
            (largestGroup===1?" trip.":" trips.")+" Shared diary times can concentrate the simulated peak.";
        }
        this.refresh();
      }
    }).catch(e=>{if(request===this.walkRequest)el("rider-walk-now").textContent=e.message;});
  }
  async loadWalks(id){
    const root="data/vancouver/rider-walks/";
    this.walkIndex??=this.load(root+this.version+".json").then(async ptr=>{
      const dir=root+ptr.version+"/",manifest=await this.load(dir+"walks.json");
      if(manifest.riders!==this.version||manifest.transit!==this.report.versions.transit||
         Object.entries(this.versions).some(([k,v])=>manifest[k]!==v))throw Error("Walking index and rider day differ.");
      return {dir,manifest};
    }).catch(error=>{this.walkIndex=null;throw error;});
    const {dir,manifest}=await this.walkIndex;
    if(!this.walkRows.has(id))this.walkRows.set(id,this.load(dir+id+".json").catch(error=>{this.walkRows.delete(id);throw error;}));
    const [rows,data]=await Promise.all([this.walkRows.get(id),this.passengers.routeData(id)]);
    return {id,rows,data,...manifest.routes[id]};
  }
  renderWalks(time,network,selected){
    const visible=new Set(),dots=[],view=this.walkView,open=el("transit-panel").open;
    const sec=time*60,button=el("rider-walk-follow");
    if(view&&open){
      const active=activeWalks(view.rows,sec,view.maxSeconds);
      let boarding=0;
      for(const [start,duration,d,i,place,stop,direction] of active){
        if(!direction)boarding++;
        if(!network)continue;
        const state=this.passengers.walking(place,view.id,stop,view.data.stations[stop],direction===0,network,(sec-start)/duration);
        if(!state.routed)continue;
        visible.add(d+"/"+i);
        if(selected?.daIndex===d&&selected.i===i)continue;
        dots.push({type:"Feature",geometry:{type:"Point",coordinates:lngLat(state.p)},properties:{d,i,boarding:direction===0}});
      }
      const next=active.length?null:view.rows.find(row=>row[0]>sec);
      this.walkExample=active[0]||next||view.rows[0];
      el("rider-walk-now").textContent=boarding+" walking to stops (purple) · "+(active.length-boarding)+" walking from stops (orange).";
      button.textContent=active.length?"Follow a walking rider":next?"Follow the next walking rider":"Replay the first walking rider";
    }else{
      this.walkExample=null;
      el("rider-walk-now").textContent="";
    }
    button.hidden=!this.walkExample;
    if(dots.length||this.visibleWalkers){
      this.services.map.getSource("rider-walkers").setData({type:"FeatureCollection",features:dots});
      this.visibleWalkers=!!dots.length;
    }
    return visible;
  }
  async followExample(){
    const route=el("transit-route").value,row=this.report.examples[route];
    if(!row)return;
    const leg=row[6]===route?row:onwardRide(row);
    const data=await this.passengers.routeData(route),{boardAt,alightAt}=rideTiming(leg,data,true);
    await this.loadArea(row[0]);
    await this.follow(row[0],row[1],(boardAt+alightAt)/120);
  }
  async followTransfer(){
    const row=this.report.transfers?.example;
    if(!row)return;
    const next=onwardRide(row),[firstData,nextData]=await Promise.all([
      this.passengers.routeData(row[6]),this.passengers.routeData(next[6])
    ]);
    const first=rideTiming(row,firstData,true),last=rideTiming(next,nextData,true);
    const walk=row[12][4];
    const minute=(walk?first.alightAt+walk/2:(first.alightAt+last.boardAt)/2)/60;
    await this.loadArea(row[0]);
    await this.follow(row[0],row[1],minute);
  }
  loadArea(da){
    if(!this.shards.has(da)){
      const pending=this.load(this.base+da+".json").then(rows=>{
        this.shards.set(da,{people:this.byPerson(rows)});this.refresh();
      }).catch(e=>{this.shards.delete(da);throw e;});
      this.shards.set(da,{pending});
    }
    return this.shards.get(da).pending;
  }
  byPerson(rows,withArea=false){
    const people=new Map();
    for(const row of rows){
      const key=withArea?row[0]+"/"+row[1]:row[1];
      if(!people.has(key))people.set(key,[]);
      people.get(key).push(row);
    }
    return people;
  }
  hasTrip(d,i,start){return this.departures?.has(d+"/"+i+"/"+start);}
  loadResident(da){return Promise.resolve(this.areas?.has(da)?this.loadArea(da):null);}
  passenger(da,i,t,net,exact=true){
    if(!this.areas?.has(da)||(!this.pinned&&!el("transit-panel").open))return null;
    const shard=this.shards.get(da);
    if(!shard&&exact)this.loadArea(da).catch(e=>this.error(e));
    const rows=shard?.people?.get(i)??this.sample?.get(da+"/"+i);
    const row=rows?.find(r=>r[2]<=t&&t<r[2]+r[3]);
    let state=null;
    if(row?.[12]){
      const missing=[...new Set([row[6],row[12][0]])].filter(id=>!this.passengers.routes.has(id));
      for(const id of missing)this.passengers.routeData(id).catch(e=>this.error(e));
      if(!missing.length)state=this.passengers.transferPosition(row,t,net);
    }else if(row)state=this.passengers.position(row,t,net,true);
    return this.pinned&&state?.description?.startsWith("Walking ")&&!state.routed?
      {...state,p:null,path:null}:state;
  }
}
