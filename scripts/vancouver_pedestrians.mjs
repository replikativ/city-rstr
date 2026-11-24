// Score the full roster with the same workplace lookup and A* router used to follow a resident.
import {readFileSync,writeFileSync} from "node:fs";
import {join} from "node:path";
import {Network, distance, roadMode} from "../public/lab/vancouver-network.js";
import {onwardRide,rideTiming} from "../public/lab/transit-passenger.js";
import {residentTrips} from "../public/js/vancouver/workplaces.js";
import {possibleHours} from "./vancouver_walk_reach.mjs";

const root=process.argv[2], read=path=>JSON.parse(readFileSync(join(root,path)));
const {radius,sites,joint,versions,boundsOnly}=JSON.parse(readFileSync(0));
if(boundsOnly&&!joint)throw Error("The walking reach comparison requires a combined weekday.");
const basis=joint??versions;
const pointer=basis?{atlas:basis.atlas,version:basis.day}:read("cityday/current.json");
const dayDir="cityday/"+pointer.version+"/",atlasDir="atlas/"+pointer.atlas+"/";
const day=read(dayDir+"day.json"),places=read(dayDir+"places.json");
const streets=basis?.streets??read("streets/current.json").version,graph=new Network(read("streets/"+streets+"/network.json"));
const version=(family,parent)=>read(family+"/"+parent+".json").version;
const outbound=joint?.outbound??version("outbound",pointer.atlas+"_"+pointer.version),outDir="outbound/"+outbound+"/";
const matched=joint?.worksites??version("worksites",outbound),tracts=joint?.tracts??version("tract-workplaces",matched);
const tract=read("tract-workplaces/"+tracts+"/worksites.json"),report=read(outDir+"report.json");
const short=joint?JSON.parse(readFileSync(joint.short,"utf8")):read("short-walks/"+pointer.version+"_"+streets+".json");
if(tract.day!==pointer.version||tract.atlas!==pointer.atlas||tract.worksites!==matched||tract.outbound!==outbound||
   report.day!==tract.day||report.atlas!==tract.atlas||report.neighbourhoodFit.streets!==streets||
   short.day!==tract.day||short.atlas!==tract.atlas||short.streets!==streets)throw Error("Different source releases for walking counts");
const tripState=residentTrips(report,read(outDir+"assignments.json"),read(outDir+"local-modes.json"),null,tract,()=>"tracts");
const walking=roadMode("walk"),maxSpeed=150,commuteSpeed=report.neighbourhoodFit.activeSpeeds.Walking;
const widerRadius=2*radius;
const inferred=day.das.map(()=>[]);
for(const row of short.walks)inferred[row[0]].push(row);
const release=joint??read("transit-riders/"+pointer.atlas+"_"+pointer.version+"_"+streets+".json");
const riderDir="transit-riders/"+release.riders+"/",transitDir="transit/"+release.transit+"/";
const riders=read(riderDir+"riders.json"),timetable=read(transitDir+"transit.json");
const stopWalk=riders.walking??{maxMetres:800,metresPerMinute:80};
if(riders.versions.day!==pointer.version||riders.versions.atlas!==pointer.atlas||riders.versions.streets!==streets||
   riders.versions.transit!==release.transit||timetable.date!==riders.date||
   (joint&&riders.versions.workplaces!==tracts))throw Error("Transit and pedestrian releases differ");
const riderAreas=new Set(riders.das),routes=new Map(),stationPlaces=new Map(),placeCount=places.length;
for(const route of timetable.routes.filter(route=>riders.byRoute[route.id])){
  const data=read(transitDir+route.id+".json");
  for(const station of data.stations){
    const key=station.slice(0,2).join(",");
    if(!stationPlaces.has(key))stationPlaces.set(key,places.push(station.slice(0,2))-1);
  }
  routes.set(route.id,{name:route.name,data});
}
const modes=["city","tracts","inferred","access","egress","replaced"];
if(joint)modes.push("shopping");
if(riders.transfers)modes.push("transfer");
const coverage=Object.fromEntries(modes.map(k=>[k,{walks:0,missing:0,colocated:0,outsideSurveyHours:0,
  outsideReach:0,routeRejected:0,routedCandidates:0}]));
const boundKinds=["work","school","other","inferred","access","egress","transfer","shopping"];
const refs=sites.map(site=>{
  for(const mode of modes){site[mode]=site.hours.map(()=>0);}
  site.at80=site.hours.map(()=>0);
  site.wider=site.hours.map(()=>0);
  site.purposes=site.hours.map(()=>[0,0,0]);
  site.lunch=Object.fromEntries(["city","tracts"].map(k=>[k,{workers:0,walks:0,errands:0}]));
  site.examples=Object.fromEntries(modes.map(mode=>[mode,site.hours.map(()=>null)]));
  site.examples.retained=site.hours.map(()=>null);
  if(boundsOnly)site.walkReach=Object.fromEntries(boundKinds.map(key=>[key,{legs:0,hourly:site.hours.map(()=>0)}]));
  return {dist:Float64Array.from(places,p=>distance(p,site.point)),hours:new Map(site.hours.map((h,i)=>[h,i]))};
});
const cache=new Map();
const auditRows=process.argv[3]?[]:null;
let residents=0,matchedRides=0;
function geometry(a,b,maxLength,fixed){
  const key=a*places.length+b,prior=cache.get(key);
  if(!fixed&&prior&&(prior.metres!==null||maxLength<=prior.limit))return prior;
  const path=fixed??graph.route(places[a],places[b],walking,maxLength);
  const result={metres:null,limit:maxLength,hits:[]};
  if(path){
    const lengths=path.slice(1).map((p,i)=>distance(path[i],p)),total=lengths.reduce((x,y)=>x+y,0);
    result.metres=total;
    for(const [s,site] of sites.entries()){
      const {dist}=refs[s];
      if(dist[a]<=radius||dist[b]<=radius||dist[a]+dist[b]>total+2*widerRadius)continue;
      let best=widerRadius,along=0,elapsed=0;
      for(let i=0;i<lengths.length;i++){
        const len=lengths[i];
        if(!len)continue;
        const [x,y]=path[i],[u,v]=path[i+1],[cx,cy]=site.point;
        const f=Math.max(0,Math.min(1,((cx-x)*(u-x)+(cy-y)*(v-y))/(len*len)));
        const d=Math.hypot(x+f*(u-x)-cx,y+f*(v-y)-cy);
        if(d<best){best=d;along=elapsed+f*len;}
        elapsed+=len;
      }
      if(best<widerRadius)result.hits.push([s,along/total,best<radius,dist[a]>widerRadius&&dist[b]>widerRadius]);
    }
  }
  if(!fixed)cache.set(key,result);
  return result;
}
function score(mode,d,i,part,a,b,speed,purpose,service,path){
  const c=coverage[mode];c.walks++;
  if(a==null||b==null||a<0||b<0){c.missing++;return;}
  if(a===b||distance(places[a],places[b])===0){c.colocated++;return;}
  const [start,dur]=part,end=start+dur;
  const transitWalk=mode==="access"||mode==="egress"||mode==="transfer";
  const limit=transitWalk?Math.min(stopWalk.maxMetres,dur*speed)+1e-7:dur*speed;
  if(boundsOnly){
    if(mode==="city"||mode==="replaced")return;
    const kind=mode==="tracts"?boundKinds[purpose]:mode;
    let possible=false;
    for(const [j,site] of sites.entries()){
      const {dist,hours}=refs[j];
      const available=possibleHours(dist[a],dist[b],start,dur,speed,limit,radius,site.hours);
      if(available.length){
        possible=true;
        const item=site.walkReach[kind];item.legs++;
        for(const h of available)item.hourly[hours.get(h)]++;
      }
    }
    if(auditRows&&possible&&!transitWalk){
      const {metres}=geometry(a,b,limit);
      if(metres!==null&&metres<=limit) auditRows.push([kind,a,b,start,dur,limit,speed,metres]);
    }
    return;
  }
  // Validate both walks of every matched ride, including rides outside the survey windows.
  let route=transitWalk?geometry(a,b,limit,path):null;
  if(route&&(route.metres===null||route.metres>limit)){c.routeRejected++;return;}
  if(!sites.some(site=>site.hours.some(h=>start<h+60&&end>h))){c.outsideSurveyHours++;return;}
  if(!refs.some(({dist})=>dist[a]+dist[b]<=limit+2*widerRadius)){c.outsideReach++;return;}
  auditRows?.push([mode,a,b,start,dur,limit]);
  route??=geometry(a,b,limit);
  if(route.metres===null||route.metres>limit){c.routeRejected++;return;}
  c.routedCandidates++;
  for(const [s,fraction,inside,wide] of route.hits){
    const when=start+dur*fraction,h=refs[s].hours.get(Math.floor(when/60)*60);
    if(h===undefined)continue;
    const site=sites[s];
    if(mode==="tracts"&&wide)site.wider[h]++;
    if(!inside)continue;
    site[mode][h]++;
    if(mode==="tracts"){
      site.purposes[h][purpose]++;
      if(route.metres<=dur*80)site.at80[h]++;
    }
    const instant=transitWalk?Math.floor(when*60)/60:Math.min(end-1,Math.round(when));
    const example=[day.das[d],i,instant,start,dur,a,b];
    if(transitWalk)example.push(service);
    site.examples[mode][h]??=example;
    if(mode==="city"&&!service)site.examples.retained[h]??=example;
  }
}
const paid=report.slots.map(slots=>new Set(slots));
const parts=day.templates.map(t=>t.parts.filter(p=>p[2]!=="stop"));
const lunch=read(atlasDir+"atlas.json").templates.map((diary,t)=>{
  const at=diary.episodes.find(([start,dur])=>start<=690&&690<start+dur);
  if(at?.[2]!=="paid-work")return null;
  const {parts,slots}=day.templates[t],k=parts.findIndex(([start,dur])=>start<=690&&690<start+dur);
  const stop=parts[k],next=parts[k+1];
  if(stop[2]!=="stop"||!paid[t].has(stop[3]))return null;
  return {stop,leg:next&&next[0]<780&&next[2]!=="stop"?next:null,destination:slots[next?.[4]]};
});
function scoreLunch(d,i,t,plan){
  const row=lunch[t];if(!row)return;
  const {stop,leg,destination}=row,x=stop[3],work=tripState(d,i,t,stop);
  const move=leg&&tripState(d,i,t,leg);
  for(const mode of ["city","tracts"]){
    const census=mode==="tracts";
    if(census&&work?.external)continue;
    const job=census?work?.overrides?.get(x)??plan[x]:plan[x];
    if(job<0)continue;
    const walked=leg&&(census?(move?.mode??move?.replaceMode??leg[2]):leg[2])==="walk";
    for(let j=0;j<sites.length;j++)if(refs[j].dist[job]<=400){
      const cohort=sites[j].lunch[mode];cohort.workers++;
      if(walked){cohort.walks++;if(destination==="restaurant"||destination==="store")cohort.errands++;}
    }
  }
}
for(const [d,da] of day.das.entries()){
  const {people}=read(atlasDir+da+".json"),{plans}=read(dayDir+da+".json");
  const journeys=new Map();
  if(riderAreas.has(da))for(const row of read(riderDir+da+".json")){
    const [home,i,start]=row,key=i+"/"+start;
    if(home!==da||journeys.has(key))throw Error("Invalid scheduled journey at "+da+"/"+key);
    journeys.set(key,row);
  }
  if(plans.length!==people.length)throw Error("Resident roster differs at "+da);
  residents+=people.length;
  for(const [i,p] of people.entries()){
    const tpl=p[7],plan=plans[i],slots=day.templates[tpl].slots;
    if(!boundsOnly)scoreLunch(d,i,tpl,plan);
    for(const part of parts[tpl]){
      const [,,mode,x,y]=part,a=plan[x],b=plan[y];
      const key=i+"/"+part[0],journey=journeys.get(key);
      const work=tripState(d,i,tpl,part);
      const external=work?.external,override=work?.overrides;
      if(mode==="walk")score("city",d,i,part,a,b,maxSpeed,null,joint?null:journey);
      if(journey){
        const origin=joint?override?.get(x)??a:a,dest=joint?override?.get(y)??b:b;
        if(journey[3]!==part[1]||journey[4]!==origin||journey[5]!==dest||joint&&external)
          throw Error("Transit journey differs from resident diary");
        const stopPlace=stop=>stationPlaces.get(stop.slice(0,2).join(","));
        const {name,data}=routes.get(journey[6]),leg=rideTiming(journey,data,true);
        const onward=onwardRide(journey);
        const lastRoute=onward?routes.get(onward[6]):{name,data};
        const last=onward?rideTiming(onward,lastRoute.data,true):leg;
        if(leg.accessStart+leg.access>leg.boardAt||last.egressStart+last.egress>(part[0]+part[1])*60)
          throw Error("Walking leg exceeds its scheduled journey");
        if(onward){
          const [,,,,walkSeconds,required,path]=journey[12];
          if(leg.alightAt+required>last.boardAt||leg.accessStart+leg.access+riders.transfers.marginSeconds>leg.boardAt||
             distance(path[0],leg.to)>0||distance(path.at(-1),last.from)>0)
            throw Error("The transfer path or timetable exceeds its window");
          if(walkSeconds)score("transfer",d,i,[leg.alightAt/60,walkSeconds/60],stopPlace(leg.to),stopPlace(last.from),
            stopWalk.metresPerMinute,null,lastRoute.name,path);
        }
        if(mode==="walk"&&!joint)score("replaced",d,i,part,a,b,maxSpeed);
        score("access",d,i,[leg.accessStart/60,leg.access/60],origin,stopPlace(leg.from),stopWalk.metresPerMinute,null,name);
        score("egress",d,i,[last.egressStart/60,last.egress/60],stopPlace(last.to),dest,stopWalk.metresPerMinute,null,lastRoute.name);
        journeys.delete(key);matchedRides++;
      }
      if(joint&&journey)continue;
      if((work?.replaceMode??work?.mode??mode)!=="walk")continue;
      const purpose=paid[tpl].has(x)||paid[tpl].has(y)?0:slots[x]==="school"||slots[y]==="school"?1:2;
      score("tracts",d,i,part,external?null:override?.get(x)??a,external?null:override?.get(y)??b,
            work?.replaceMode||override?commuteSpeed:maxSpeed,purpose);
    }
  }
  if(journeys.size)throw Error("Scheduled journeys absent from diary at "+da);
  for(const [,i,start,dur,x,y] of inferred[d])score("inferred",d,i,[start,dur],plans[i][x],plans[i][y],joint?short.speed:maxSpeed);
  if(!boundsOnly&&d%100===0)console.error(da,residents,"residents,",cache.size,"survey candidate routes");
}
if(joint){
  const folder="discretionary-outings/"+joint.outings+"/";
  const tours=read(folder+"tours.json"),shopping=read(folder+"report.json");
  for(const [d,i,a,b,,mode,start,there,dwell,back] of tours){
    if(mode!=="walk")throw Error("Expected a walking shopping outing.");
    score("shopping",d,i,[start,there],a,b,shopping.walkMetresPerMinute);
    score("shopping",d,i,[start+there+dwell,back],b,a,shopping.walkMetresPerMinute);
  }
}
if(residents!==day.population||matchedRides!==riders.matched)throw Error("Incomplete resident or rider roster");
if(boundsOnly){
  if(auditRows)writeFileSync(process.argv[3],JSON.stringify({legs:auditRows,stations:places.slice(placeCount)}));
  console.log(JSON.stringify({day:pointer.version,atlas:pointer.atlas,streets,tracts,riders:release.riders,residents,radius,
    sites:sites.map(({name,hours,walkReach})=>({name,hours,walkReach}))}));
  process.exit(0);
}
if(riders.walking?.nearestNodeTie==="lowest network ID"&&(coverage.access.routeRejected||coverage.egress.routeRejected))
  throw Error("A scheduled station walk exceeds its distance or timetable budget: "+
              coverage.access.routeRejected+" to stops, "+coverage.egress.routeRejected+" from stops");
if(coverage.transfer?.routeRejected)throw Error("Some walks between vehicles exceed their published time");
for(const [k,{walks,...counts}] of Object.entries(coverage)){
  if(Object.values(counts).reduce((x,y)=>x+y,0)!==walks)throw Error("Missing walking legs in "+k);
}
if(auditRows)writeFileSync(process.argv[3],JSON.stringify({legs:auditRows,stations:places.slice(placeCount)}));
const transit={riders:release.riders,transit:release.transit,date:riders.date,matched:matchedRides,total:riders.total};
console.log(JSON.stringify({day:pointer.version,atlas:pointer.atlas,streets,tracts,residents,radius,widerRadius,maxSpeed,commuteSpeed,transit,coverage,sites}));
