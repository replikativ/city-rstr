import {BIKE,CAR,WALK,distance,roadMode} from "./vancouver-network.js";
import {radius,sampleDriver} from "./street-pedestrians.js";

export const scenarioStreetTags={
  "recreation-loops":"Recreational walk",
  "recreational-ride":"Recreational bike ride",
  "recorded-walk":"Recorded recreational walk",
  "school-escorts":"School escort",
  "weekday-attendance":"On-site work trip",
  "work-transit":"Walk to or from work transit",
  "personal-transit":"Walk to or from transit",
  "transit-riders":"Walk to or from scheduled transit",
  "vehicle-access":"Trip switched after assigning household vehicle access",
  "discretionary-outings":"Shopping or recreation outing",
  "grocery-opening":"Grocery visit diverted by an opening",
  "shopping-clock":"Shifted bicycle shopping trip",
  "workplace-lunch":"Lunch walk from work",
  "eastern-outings":"Burnaby or New Westminster outing",
  "voting":"Advance voting trip",
  "short-walks":"Reconstructed short walk"
};

export const isScenarioTrip=tag=>!!tag&&tag!=="recorded-walk"&&tag!=="grocery-walk";

function hourBuckets(records) {
  const buckets=Array.from({length:24},()=>[]);
  for(const row of records){
    const [, ,start,end]=row;
    for(let hour=Math.floor(start/60);hour<Math.ceil(end/60);hour++)buckets[hour-4].push(row);
  }
  return buckets;
}

export function streetOutings(rows,report,tag="discretionary-outings",shops) {
  const moving={[WALK]:[],[BIKE]:[],[CAR]:[]};
  for(const row of rows){
    const [d,i,home,originalSite,,mode,start,there,dwell,back]=row;
    const origin=tag==="voting"?row[10]??home:home;
    const site=shops?.get(d+"/"+i)??originalSite;
    const leave=start+there+dwell;
    const road=roadMode(mode);
    if(!moving[road]||road===CAR&&!sampleDriver(d,i))continue;
    const speed=road===WALK?report.walkMetresPerMinute:road===BIKE?report.cycleProfile.metresPerMinute:380;
    for(const [a,b,s,n] of [[origin,site,start,there],[site,home,leave,back]])
      moving[road].push([d,i,s,s+n,a,b,speed,false,tag,false]);
  }
  return Object.fromEntries(Object.entries(moving).map(([mode,records])=>[mode,hourBuckets(records)]));
}

function activeSegment(path,offsets,time) {
  if(!path||!offsets||path.length<2)return null;
  let lo=0,hi=path.length-1;
  while(lo+1<hi){
    const mid=(lo+hi)>>1;
    if(offsets[mid]<=time)lo=mid;else hi=mid;
  }
  return [path[lo],path[hi]];
}

export function scenarioActor(d,i,minute,centre,state,kind) {
  if(!state?.p||!state.routed)return null;
  const mode=state.scheduled&&state.description?.startsWith("Walking ")?WALK:roadMode(state.mode);
  if(!mode||mode===CAR&&(state.mode!=="car-driver"||!sampleDriver(d,i)))return null;
  const range=distance(state.p,centre);
  if(range>radius)return null;
  const segment=activeSegment(state.path,state.offsets,minute-state.start);
  const bearing=mode===CAR&&segment?Math.atan2(segment[1][0]-segment[0][0],segment[0][1]-segment[1][1])*180/Math.PI:null;
  const tag=kind==="recreation-loops"?(mode===BIKE?"recreational-ride":state.added?kind:"recorded-walk"):kind;
  const actor=[d,i,...state.p.slice(0,2),range,mode,bearing,tag,state.streetParty??1];
  return segment?[...actor,segment]:actor;
}

export function nearbyScenarioRecords(records,minute,centre,include=true) {
  const [x,y]=centre;
  return records.filter(([, ,start,end,left,top,right,bottom,enabled])=>
    start<=minute&&minute<end&&(include||!enabled)&&
    x+radius>=left&&x-radius<=right&&y+radius>=top&&y-radius<=bottom);
}

function scheduledWalker(model,d,i,minute,graph,da){
  const passenger=model.passenger(da,i,minute,graph,true);
  return passenger&&{...passenger,mode:"transit",scheduled:true};
}

const rich=[
  ["recreation","recreation-loops",(model,d,i,minute)=>model.state(d,i,minute,false,true)],
  ["schools","school-escorts",(model,d,i,minute)=>model.state(d,i,minute,false,true)],
  ["attendance","weekday-attendance",(model,d,i,minute,graph)=>model.state(d,i,minute,graph,false,true)],
  ["workTransit","work-transit",scheduledWalker],
  ["personalTransit","personal-transit",scheduledWalker],
  ["cityTransit","transit-riders",scheduledWalker],
  ["vehicleAccess","vehicle-access",(model,d,i,minute)=>model.state(d,i,minute,false)],
  ["outings","discretionary-outings",(model,d,i,minute,graph)=>model.state(d,i,minute,graph)]
];

export class StreetScenarios {
  constructor({root,versions,day,json,layers,graph,refresh}){
    Object.assign(this,{root,versions,day,json,layers,graph,refresh});
    this.indexes=new Map();
    this.shards=new Map();
    this.outingIndexes=new WeakMap();
  }

  context() {
    const {recreation,schools,attendance,outings,lunch,easternOutings,voting,workTransit,personalTransit,cityTransit,vehicleAccess,shortWalks}=this.layers();
    return [recreation?.version,recreation?.active&&!recreation.differentLayers,
      schools?.version,attendance?.version,outings?.version,lunch?.version,easternOutings?.version,
      voting?.version,voting?.layout,voting?.date,voting?.schedule,
      workTransit?.version,personalTransit?.version,cityTransit?.version,vehicleAccess?.version,!!shortWalks].join("/");
  }

  pin(params){
    const {recreation,schools,attendance,outings,lunch,easternOutings,voting,shortWalks}=this.layers();
    for(const [name,key,model] of [
      ["recreation","recreationRun",recreation?.active&&!recreation.differentLayers?recreation:null],
      ["schools","schoolRun",schools],["attendance","attendanceRun",attendance],["outings","outingsRun",outings],
      ["easternOutings","easternOutingRun",easternOutings]]){
      if(!model)continue;
      params.delete(name);
      params.set(key,model.version);
    }
    if(shortWalks)params.set("walks","fit");
    if(lunch)params.set("lunch","walk");
    if(voting){
      params.set("votingRun",voting.version);params.set("votingLayout",voting.layout);
      if(voting.date)params.set("votingDate",voting.date);
      if(voting.schedule!=="recorded")params.set("votingSchedule",voting.schedule);
    }
  }

  request(cache,version,read,decode){
    if(!cache.has(version)){
      const entry={loading:true};
      cache.set(version,entry);
      entry.promise=read().then(decode).then(value=>{
        entry.value=value;entry.loading=false;this.refresh();
        return value;
      }).catch(error=>{
        entry.error=error;entry.loading=false;this.refresh();
      });
    }
    return cache.get(version);
  }

  index(kind,release,decode){
    return this.request(this.indexes,kind+"/"+release,
      ()=>this.json(this.root+kind+"_"+release+".json"),
      report=>{
        if(report.schema!==1||report.kind!==kind||report.release!==release||
           Object.entries(this.versions).some(([key,v])=>report.versions[key]!==v))
          throw Error("The scenario street index and weekday differ.");
        return decode(report.records);
      });
  }

  forOutings(model,tag,shops){
    let cached=this.outingIndexes.get(model);
    if(!cached||cached.shops!==shops){
      cached={shops,rows:streetOutings(model.rows,model.report,tag,shops)};
      this.outingIndexes.set(model,cached);
    }
    return cached.rows;
  }

  async routeRows(hour){
    const {outings,outingShops,lunch,easternOutings,voting,shortWalks}=this.layers();
    const moving=outings?this.forOutings(outings,undefined,outingShops):null;
    const rows=Object.fromEntries([WALK,BIKE,CAR].map(mode=>[mode,[...(moving?.[mode][hour-4]??[])]]));
    if(lunch)rows[WALK].push(...this.forOutings(lunch,"workplace-lunch")[WALK][hour-4]);
    if(easternOutings)rows[CAR].push(...this.forOutings(easternOutings,"eastern-outings")[CAR][hour-4]);
    if(voting){
      const roads=this.forOutings(voting.roadTrips,"voting");
      for(const mode of [WALK,CAR])rows[mode].push(...roads[mode][hour-4]);
    }
    if(shortWalks){
      const [a,b]=[this.versions.day,this.versions.streets];
      const decode=records=>{
        if(records.length!==shortWalks.walks.length||records.some((row,i)=>
          row.slice(0,4).some((value,j)=>shortWalks.walks[i][j]!==value)))
          throw Error("The street index and inferred walks differ.");
        return hourBuckets(records.map(([d,i,s,n,from,to])=>[d,i,s,s+n,from,to,shortWalks.speed,false,"short-walks"]));
      };
      const entry=shortWalks.streetWalks?
        this.request(this.indexes,"short-walks/combined",()=>Promise.resolve(shortWalks.streetWalks),decode):
        this.index("short-walks",a+"_"+b,decode);
      const table=entry.value??await entry.promise;
      rows[WALK].push(...(table?.[hour-4]??[]));
    }
    for(const mode of [WALK,BIKE,CAR]){
      rows[mode]=rows[mode].map(([d,i,start,end,...rest])=>[d,i,start,end-start,...rest]);
    }
    return rows;
  }

  actorsAt(minute,centre){
    const layers=this.layers(),hour=Math.floor(minute/60)-4,actors=[];
    let loading=false,error=!!(layers.shortWalks&&this.indexes.get(
      "short-walks/"+this.versions.day+"_"+this.versions.streets)?.error);
    for(const [name,kind,state] of rich){
      const model=layers[name];
      if(!model||name==="outings"&&!model.report.transit)continue;
      const index=this.index(kind,model.version,hourBuckets);
      loading||=index.loading;
      error||=!!index.error;
      if(!index.value)continue;
      const include=name!=="recreation"||model.active&&!model.differentLayers;
      for(const [d,i] of nearbyScenarioRecords(index.value[hour],minute,centre,include)){
        const da=this.day.das[d];
        if(model.loadResident){
          const shard=this.request(this.shards,kind+"/"+model.version+"/"+da,
            ()=>model.loadResident(da,false),()=>true);
          loading||=shard.loading;
          error||=!!shard.error;
          if(!shard.value)continue;
        }
        const actor=scenarioActor(d,i,minute,centre,state(model,d,i,minute,this.graph(),da),kind);
        if(actor)actors.push(actor);
      }
    }
    return {actors,loading,error};
  }
}
