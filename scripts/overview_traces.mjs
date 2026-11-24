// Convert the publishers' routed trajectory samples to one local-clock representation.
import {readFileSync,writeFileSync,renameSync,mkdirSync,mkdtempSync,rmSync} from "node:fs";
import {execFileSync} from "node:child_process";
import {join} from "node:path";
import {createHash} from "node:crypto";
import {Network,lngLat,roadMode,BIKE,CAR,WALK} from "./vancouver-network.js";
import {findRoute,routeKey} from "./weekday-pathfinder.js";
import {bicycleMetresPerMinute} from "./street-pedestrians.js";

const root=process.argv[2]??"public/data";
const out=join(root,"overview");
mkdirSync(out,{recursive:true});
const read=(...parts)=>JSON.parse(readFileSync(join(root,...parts)));
function publish(name,bytes){
  const path=join(out,name+".json"),temp=path+"."+process.pid;
  writeFileSync(temp,bytes);renameSync(temp,path);
}
function shard(rows){
  const bytes=JSON.stringify(rows),hash=createHash("sha256").update(bytes).digest("hex");
  publish(hash,bytes);return hash;
}
function stuttgart(run){
  const temp=mkdtempSync(join(out,".routing-"));
  try{
    const archive=process.argv[3]??"../Simulations/city";
    execFileSync("clojure",["-J-Xmx3g","-M","-m","city.street-replay",
      join(archive,"data/raw/osm-overpass/stuttgart_highways.json"),
      join(root,"stuttgart",run.release,"trips.json"),temp],{stdio:"inherit"});
    const hours=Array.from({length:24},(_,h)=>{
      const lines=readFileSync(join(temp,h+".jsonl"),"utf8").trim();
      return shard(lines?lines.split("\n").map(line=>JSON.parse(line)):[]);
    });
    return {hours,timing:JSON.parse(readFileSync(join(temp,"timing.json"),"utf8"))};
  }finally{rmSync(temp,{recursive:true,force:true});}
}
function regionalCommuterTraces(run,dir,places){
  const hours=Array.from({length:24},()=>[]);
  if(!run.regionalWorkers)return hours;
  const folder=[dir,"incoming-workers",run.regionalWorkers], report=read(...folder,"commuters.json");
  const graph=new Network(read(dir,"streets",run.streets,"network.json"),null,read(dir,"drive-profile",run.streets+".json"));
  let ordinal=0;
  for(const group of Object.keys(report.groups).sort()){
    const shard=read(...folder,group+".json");
    for(const [i,[h,j,,,mode,start,duration,span,attending]] of shard.people.entries()){
      if(!attending)continue;
      const agent=run.population+ordinal++;
      if((agent-run.population)%32!==0)continue;
      const label=report.modes[mode];
      const networkMode=["Car driver","Car passenger","Taxi","Ride-hail"].includes(label)?CAR:label==="Walking"?WALK:null;
      if(!networkMode)continue;
      const home=shard.homePoints[h],work=places[j];
      for(const [from,to,t,purpose] of [[home,work,start,"inbound work"],[work,home,start+duration+span,"return home"]]){
        const route=findRoute(graph,networkMode,from,to,duration,networkMode===CAR?380:150,false,t);
        if(!route?.minutes)continue;
        const path=route.path.map(p=>lngLat(p).map(x=>+x.toFixed(6)));
        for(let hour=Math.floor(t/60);hour<Math.ceil((t+duration)/60);hour++){
          const begin=t-Math.floor(hour/24)*1440;
          hours[hour%24].push({id:"incoming/"+group+"/"+i,agent,mode:label,purpose,path,
            times:route.offsets.map(dt=>begin+dt/route.minutes*duration)});
        }
      }
    }
  }
  if(ordinal!==run.inbound)throw Error("Regional commuter route IDs disagree with the roster");
  return hours;
}
function vancouver(run){
  const dir=run.coverage==="region"?"vancouver/region":"vancouver", day=read(dir,"cityday",run.day,"day.json");
  const places=read(dir,"cityday",run.day,"places.json"),atlas=read(dir,"atlas",run.atlas,"atlas.json");
  const cache=read(dir,"overview-routes",[run.atlas,run.day,run.streets].join("_")+".json").version;
  const meta=read(dir,"overview-routes",cache,"manifest.json");
  if(["day","atlas","streets"].some(k=>meta[k]!==run[k]))throw Error("Route cache parents disagree");
  let population=0;
  const incoming=regionalCommuterTraces(run,dir,places);
  const offsets=day.das.map(da=>{
    const offset=population;
    population+=atlas.das[da].population;
    return offset;
  });
  if(population!==run.population)throw Error("Trace IDs and population disagree");
  const legs=day.templates.map((t,i)=>t.parts.filter(([s,d,m])=>roadMode(m)&&
    atlas.templates[i].episodes.every(([start,n,,mode])=>start>=s+d||start+n<=s||mode===m)));
  const hours=Array.from({length:24},()=>[]);
  for(let h=0;h<24;h++){
    const hour=h<4?h+24:h, routes=new Map(read(dir,"overview-routes",cache,hour+".json")), rows=[];
    for(const [district,person,template,plan] of day.sample){
      for(const [start,duration,recorded,a,b] of legs[template]){
        if(start>=(hour+1)*60||start+duration<=hour*60)continue;
        const from=places[plan[a]],to=places[plan[b]],mode=roadMode(recorded);
        if(!from||!to)continue;
        const route=routes.get(routeKey(mode,from,to,duration,mode===CAR?380:mode===BIKE?bicycleMetresPerMinute:150,false));
        if(!route?.minutes)continue;
        const origin=start-(hour-h)*60;
        rows.push({id:day.das[district]+"/"+person,agent:offsets[district]+person,mode:recorded,purpose:day.templates[template].slots[b],
          path:route.path.map(p=>lngLat(p).map(x=>+x.toFixed(6))),
          times:route.offsets.map(t=>origin+t/route.minutes*duration)});
      }
    }
    for(const leg of rows.concat(incoming[h])){
      if(Math.floor(leg.times[0]/60)!==h)continue;
      if(run.regionalWorkers){
        // Same roster ordinal and phase as city.vancouver.diary-clock.
        const shift=5*((leg.agent+1)*7919%10007+0.5)/10007-2.5;
        const resident=leg.agent<run.population;
        const start=leg.times[0], end=leg.times.at(-1);
        const pinned=t=>resident && (t-240)%1440===0;
        const a=start+(pinned(start)?0:shift), b=end+(pinned(end)?0:shift);
        leg.times=leg.times.map(t=>a+(t-start)*(b-a)/(end-start));
      }
      for(let hour=Math.floor(leg.times[0]/60);hour<Math.ceil(leg.times.at(-1)/60);hour++){
        const wrap=Math.floor(hour/24)*1440;
        hours[(hour+24)%24].push(wrap?{...leg,times:leg.times.map(t=>t-wrap)}:leg);
      }
    }
  }
  return hours.map(legs=>shard(legs.sort((a,b)=>(Math.imul(a.agent,2654435761)>>>0)-(Math.imul(b.agent,2654435761)>>>0))));
}
function streets(run){
  let groups;
  if(run.city==="stuttgart"){
    const archive=process.argv[3]??"../Simulations/city";
    const osm=JSON.parse(readFileSync(join(archive,"data/raw/osm-overpass/stuttgart_highways.json")));
    groups={street:[],arterial:[],bridge:[]};
    for(const {tags,geometry} of osm.elements){
      if(!geometry||geometry.length<2||!tags?.highway)continue;
      if(tags.area==="yes"||["proposed","construction","raceway","platform","elevator","rest_area"].includes(tags.highway))continue;
      const cls=tags.bridge&&tags.bridge!=="no"?"bridge":/^(primary|secondary|trunk|motorway)/.test(tags.highway)?"arterial":"street";
      groups[cls].push(geometry.map(p=>[Math.round(p.lon*1e6)/1e6,Math.round(p.lat*1e6)/1e6]));
    }
  }else{
    groups=read(run.coverage==="region"?"vancouver/region":"vancouver","atlas",run.atlas,"basemap.json").roads;
  }
  return shard({type:"FeatureCollection",features:Object.entries(groups).map(([kind,coordinates])=>({
    type:"Feature",properties:{kind},geometry:{type:"MultiLineString",coordinates}}))});
}
function commuterOrigins(){
  const archive=process.argv[3]??"../Simulations/city";
  const origins=readFileSync(join(archive,"data/derived/stuttgart_incommuter_origins.jsonl"),"utf8")
    .trim().split("\n").map(line=>JSON.parse(line));
  const byCode=new Map(origins.map(origin=>[origin.ags,origin]));
  const municipalities=JSON.parse(readFileSync(new URL("../resources/city/stuttgart-municipalities.json",import.meta.url)));
  const features=municipalities.features.flatMap(({properties,geometry})=>{
    const origin=byCode.get(properties.ags);
    return origin?[{type:"Feature",geometry,properties:{name:origin.name,flow:origin.flow}}]:[];
  });
  return shard({type:"FeatureCollection",features});
}
for(const run of read("runs","current.json").filter(r=>!process.argv[4]||r.release===process.argv[4])){
  const traces=run.city==="stuttgart"?stuttgart(run):{hours:vancouver(run)};
  publish(run.release+"-traces",JSON.stringify({release:run.release,...traces,roads:streets(run),...(run.city==="stuttgart"?{origins:commuterOrigins()}:{})}));
  console.log(run.city,run.release);
}
