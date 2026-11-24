import {BIKE,CAR} from "./vancouver-network.js";
import {driverSampleDenominator,sampleDriver,streetLegs} from "./street-pedestrians.js";
import {isScenarioTrip,scenarioStreetTags} from "./street-scenarios.js";
const el=id=>document.getElementById(id);
async function binary(url){
  const r=await fetch(url);
  if(!r.ok)throw Error("Street trips for this hour are unavailable.");
  const bytes=await r.arrayBuffer();
  if(bytes.byteLength%16)throw Error("Incomplete street trip record.");
  return new DataView(bytes);
}

export function mergeStreetActors(street,scenario){
  const people=new Map();
  for(const row of [...street,...scenario]){
    const id=row[0]+"/"+row[1],prior=people.get(id);
    if(!prior||row[7])people.set(id,row);
  }
  return [...people.values()].sort((a,b)=>a[4]-b[4]||a[0]-b[0]||a[1]-b[1]);
}

export class NearbyWalks{
  constructor({root,versions,network,cycling,bikeways,driving,day,places,json,resolve,extraCyclists,extraWalkers,extraHired,scenarios,groceryWalks,draw,follow,clock}){
    Object.assign(this,{root,versions,network,cycling,bikeways,driving,day,places,json,resolve,extraCyclists,extraWalkers,extraHired,scenarios,groceryWalks,draw,follow,clock});
    this.on=false;this.ticket=0;this.revision=0;this.requests=new Map();
    for(const [button,mode] of [["nearby-follow",1],["nearby-cycle",BIKE],["nearby-drive",CAR]])
      el(button).onclick=()=>{if(this.nearest[mode])this.follow(...this.nearest[mode]).catch(e=>this.fail(e));};
    el("nearby-scenario").onclick=()=>{if(this.nearestScenario)this.follow(...this.nearestScenario).catch(e=>this.fail(e));};
  }
  setActive(on){
    if(this.on===on)return;
    this.on=on;this.failed=false;this.context=null;this.ticket++;this.revision++;this.last=null;this.pending=null;
    this.clear();
    if(!on){
      this.worker?.terminate();this.worker=null;this.ready=false;this.busy=false;this.hour=null;
      return;
    }
    el("nearby-count").textContent="Locating nearby residents…";
    this.worker=new Worker(new URL("./street-pedestrians-worker.js",import.meta.url),{type:"module"});
    this.sentPlaces=0;
    this.worker.onerror=e=>this.fail(Error(e.message||"Unable to load nearby residents."));
    this.worker.onmessage=({data})=>{
      if(data.error){this.fail(Error(data.error));return;}
      if(data.ready){this.ready=true;this.driverGraph=data.drivers;this.send();return;}
      this.busy=false;
      if(data.dots&&data.revision===this.revision){
        this.snapshot=data;
        this.refreshScenarios();
      }
      this.send();
    };
    this.worker.postMessage({bikeways:this.bikeways,network:new URL(this.network,document.baseURI).href,
      cycling:this.cycling&&new URL(this.cycling,document.baseURI).href,
      driving:this.driving&&new URL(this.driving,document.baseURI).href});
  }
  refreshScenarios(){
    if(!this.on||!this.snapshot)return;
    if(this.scenarios&&this.scenarios.context()!==this.sceneContext)return;
    const {dots,minute,centre,checkingDrivers}=this.snapshot;
    const {actors,loading,error}=this.scenarios?.actorsAt(minute,centre)??{actors:[]};
    const grocery=this.groceryWalks?.();
    const remaining=rows=>grocery?rows.filter(([d,i])=>!grocery.visit(d,i,minute)):rows;
    const local=mergeStreetActors(remaining(dots),[...remaining(actors),...(grocery?.nearby(minute,centre)??[])]);
    const signature=JSON.stringify([minute,local]);
    if(signature!==this.lastDrawn){this.lastDrawn=signature;this.draw(local,minute);}
    const labels=[];
    const identity=row=>row?[this.day.das[row[0]],row[1],minute]:null;
    for(const [mode,button,label] of [[1,"nearby-follow","pedestrian"],[BIKE,"nearby-cycle","cyclist"],[CAR,"nearby-drive","car"]]){
      const people=local.filter(row=>row[5]===mode),first=people[0];
      this.nearest[mode]=identity(first);
      el(button).hidden=!first;
      if(people.length||mode===1||mode===BIKE&&this.showsBikes||mode===CAR&&this.showsCars&&this.driverGraph){
        if(mode===CAR){
          const hired=people.filter(row=>row[10]).length,drivers=people.length-hired;
          labels.push(drivers+" private "+label+(drivers===1?"":"s")+" (1 in "+driverSampleDenominator+" drivers sampled)");
          if(hired)labels.push(hired+" hired "+label+(hired===1?"":"s"));
          el(button).textContent=first?.[10]?"Follow passenger":"Follow driver";
        }else{
          const total=people.reduce((count,row)=>count+(row[8]??1),0);
          labels.push(total+" "+label+(total===1?"":"s"));
        }
      }
    }
    const added=local.filter(row=>isScenarioTrip(row[7]));
    const first=added[0],action=el("nearby-scenario");
    this.nearestScenario=identity(first);
    action.hidden=!first;
    action.title=first?scenarioStreetTags[first[7]]:"";
    const status=labels.join(" · ")+" within 250 m · "+this.clock(minute)+
      (added.length?" · "+added.length+" scenario "+(added.length===1?"trip":"trips"):"")+
      (checkingDrivers?" · Checking more car routes":"")+
      (loading?" · Loading scenario trips":"")+(error?" · Some scenario trips are unavailable":"");
    if(el("nearby-count").textContent!==status)el("nearby-count").textContent=status;
  }
  clear(){
    this.nearest={};this.nearestScenario=null;this.snapshot=null;this.lastDrawn=null;
    for(const button of ["nearby-follow","nearby-cycle","nearby-drive","nearby-scenario"])el(button).hidden=true;
    this.draw([]);
  }
  fail(error){
    this.ticket++;this.revision++;this.hour=null;this.context=null;this.pending=null;this.failed=true;
    this.clear();el("nearby-count").textContent=error.message;
  }
  async directory(){
    const {atlas,day,clock}=this.versions;
    const key=[atlas,day,clock].filter(Boolean).join("_");
    const pointer=await this.json(this.root+key+".json"),dir=this.root+pointer.version+"/";
    const manifest=await this.json(dir+"walks.json");
    if(manifest.atlas!==atlas||manifest.day!==day||manifest.clock!==(clock??null)||manifest.residents!==this.day.population)
      throw Error("The street trip index and the resident day have different releases.");
    this.indexHasBikes=Number.isInteger(manifest.bike);
    this.showsBikes=!!this.cycling&&this.indexHasBikes;
    this.showsCars=!!this.driving&&Number.isInteger(manifest.car);
    return dir;
  }
  async rows(hour,census){
    const key=hour+"/"+census;
    if(!this.requests.has(key)){
      this.release??=this.directory().catch(e=>{this.release=null;throw e;});
      const request=this.release.then(dir=>{
        const kinds=["walk"];
        if(this.showsBikes||(census&&this.indexHasBikes))kinds.push("bike");
        if(this.showsCars)kinds.push("car");
        if(census)kinds.push("commute");
        return Promise.all(kinds.map(async kind=>[kind,await binary(dir+kind+"-"+hour+".bin")]));
      });
      if(this.requests.size>=4)this.requests.delete(this.requests.keys().next().value);
      this.requests.set(key,request.catch(e=>{this.requests.delete(key);throw e;}));
    }
    return this.requests.get(key);
  }
  async load(hour,census){
    const ticket=++this.ticket;
    try{
      const [chunks,extra]=await Promise.all([this.rows(hour,census),this.scenarios?.routeRows(hour)]);
      if(this.ticket!==ticket)return;
      const rows={1:[],[BIKE]:[],[CAR]:[]};
      const carLegs=census?new Set():null;
      chunks.forEach(([kind,chunk])=>{
        for(const [d,i,tpl,part,a,b] of streetLegs(chunk,this.day)){
          const trip=(d*65536+i)*1680+part[0];
          if(kind==="commute"&&carLegs?.has(trip))continue;
          if(kind==="car")carLegs?.add(trip);
          const leg=this.resolve(d,i,tpl,part,a,b,kind==="commute");
          if(leg){
            const [origin,dest,speed,mode,shortest]=leg;
            if(mode===CAR&&(!this.showsCars||!sampleDriver(d,i)))continue;
            rows[mode].push([d,i,part[0],part[1],origin,dest,speed,shortest]);
          }
        }
      });
      for(const row of this.extraCyclists?.(hour)??[])rows[BIKE].push(row);
      for(const row of this.extraWalkers?.(hour)??[])rows[1].push(row);
      if(this.showsCars)rows[CAR].push(...(this.extraHired?.(hour)??[]));
      if(extra)for(const mode of [1,BIKE,CAR])rows[mode].push(...extra[mode]);
      this.worker.postMessage({rows,places:this.places.slice(this.sentPlaces).map(p=>p.slice(0,2))});
      this.busy=false;
      this.sentPlaces=this.places.length;
      this.hour=hour;this.send();
    }catch(e){if(this.ticket===ticket)this.fail(e);}
  }
  view(minute,centre,variant,census){
    if(!this.on||this.failed)return;
    this.sceneContext=this.scenarios?.context()??"";
    const hour=Math.floor(minute/60),context=hour+"/"+variant+"/"+this.sceneContext;
    if(context!==this.context){
      this.context=context;this.revision++;this.hour=null;this.last=null;this.clear();
      el("nearby-count").textContent="Locating nearby residents…";
      this.load(hour,census);
    }
    const last=this.last;
    if(last&&last.minute===minute&&last.centre[0]===centre[0]&&last.centre[1]===centre[1])return;
    this.last=this.pending={minute,centre,revision:this.revision};this.send();
  }
  send(){
    if(!this.on||!this.ready||this.busy||!this.pending||this.hour===null)return;
    this.busy=true;this.worker.postMessage(this.pending);this.pending=null;
  }
}
