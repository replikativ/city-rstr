// Score the same directed routes, workplace choices and time budgets as the street view.
import {readFileSync,writeFileSync} from "node:fs";
import {join} from "node:path";
import {activeStreetLeg,activeStreetMode,budgetRoute,streetLegs} from "../public/lab/street-pedestrians.js";
import {Network,BIKE,distance,xy,lngLat} from "../public/lab/vancouver-network.js";
import {residentTrips} from "../public/js/vancouver/workplaces.js";

const root=process.argv[2],read=p=>JSON.parse(readFileSync(join(root,p)));
const input=JSON.parse(readFileSync(0)),{versions:v,sites}=input;
const day=read("cityday/"+v.day+"/day.json"),places=read("cityday/"+v.day+"/places.json");
const net=read("cycling/"+v.cycling+"/network.json"),shortest=new Network(net);
const profile=v.bikeways&&read("bikeways/"+v.bikeways+"/profile.json");
if(profile&&profile.cycling!==v.cycling)throw Error("Bikeways use a different street graph");
const graph=profile?new Network(net,profile):shortest;
const withoutHills=profile?.parentBikeways?new Network(net,{...profile,uphillArcs:null}):null;
const dir="street-walks/"+v.legs+"/",manifest=read(dir+"walks.json");
if(!Number.isInteger(manifest.bike)||manifest.day!==v.day||manifest.atlas!==v.atlas||manifest.clock!==v.clock||
   read("cycling/"+v.cycling+"/source.json").streets!==v.streets)throw Error("Mismatched cyclist releases");
const nodesOn=name=>new Set(net.ways.filter(([,i])=>net.names[i]===name).flatMap(([, ,nodes])=>nodes));
for(const site of sites){
  const streets=site.junction??(site.key==="arbutus"?["Arbutus Street","West 10th Avenue"]:null);
  if(streets){
    const left=nodesOn(streets[0]),both=[...nodesOn(streets[1])].filter(i=>left.has(i));
    if(both.length!==1)throw Error("Ambiguous junction at "+site.name);
    site.point=net.nodes[both[0]];
  }else site.point=xy(site.lonLat);
  site.lonLat??=lngLat(site.point);
}
// Count the junction when the rider reaches it along one network edge and leaves on another.
// Midblock counts use a finite cross-section through the reported location.
function passage(route,site){
  const p=route.points,c=site.point,screen=site.screen??(site.key==="powell"?[1,0,22]:null);
  let elapsed=0;
  for(let i=1;i<p.length;i++){
    const a=p[i-1],b=p[i],length=distance(a,b);
    if(i>=2&&i<p.length-1){
      if(!screen){
        if(i<p.length-2&&b===c){
          const dx=a[0]-c[0],dy=a[1]-c[1];
          const approach=Math.abs(dx)>Math.abs(dy)?(dx>0?"From East":"From West"):(dy>0?"From South":"From North");
          return [(elapsed+length)/route.metres,approach];
        }
      }else{
        const [dx,dy,width]=screen,east=a[0]-c[0],south=a[1]-c[1];
        const start=east*dx+south*dy,end=(b[0]-c[0])*dx+(b[1]-c[1])*dy;
        if((start<0)!==(end<0)){
          const f=-start/(end-start),lateral=(south+f*(b[1]-a[1]))*dx-(east+f*(b[0]-a[0]))*dy;
          if(Math.abs(lateral)<=width&&(!site.screen||Math.abs(end-start)>=length/2))
            return [(elapsed+f*length)/route.metres,start<0?"From West":"From East"];
        }
      }
    }
    elapsed+=length;
  }
  return null;
}
let rule="city",work=null,speeds=null;
const rules=["city"];
if(v.outbound){
  const base="outbound/"+v.outbound+"/",report=read(base+"report.json");
  const sites=v.worksites&&read("worksites/"+v.worksites+"/worksites.json");
  const tracts=v["tract-workplaces"]&&read("tract-workplaces/"+v["tract-workplaces"]+"/worksites.json");
  if(report.day!==v.day||report.atlas!==v.atlas||report.neighbourhoodFit?.cycling!==v.cycling||
    (sites&&sites.outbound!==v.outbound)||(tracts&&tracts.worksites!==v.worksites))throw Error("Different bicycle and workplace releases");
  work=residentTrips(report,read(base+"assignments.json"),read(base+"local-modes.json"),sites,tracts,()=>rule);
  speeds=report.neighbourhoodFit.activeSpeeds;
  rules.push("diary","usual","local");if(sites)rules.push("sites");if(tracts)rules.push("tracts");
}
const tourRows=Array.from({length:28},()=>[]);
const workplaceRules=rules.filter(name=>name!=="city");
const tourRules=v.tours?["cycleTours","cycleAccess"]:[];
if(v.tours){
  const base="cycle-tours/"+v.tours+"/",report=read(base+"report.json");
  if(v.clock||["atlas","day","cycling","streets"].some(k=>report.versions[k]!==v[k]))
    throw Error("Discretionary outings refer to a different weekday");
  const tourLegs=new Set();
  for(const [d,i,tpl,,,legs,access] of read(base+"tours.json"))for(const [s,n,a,b] of legs){
    const key=[d,i,s].join("/");
    if(tourLegs.has(key))throw Error("Duplicate bicycle outing leg: "+key);
    tourLegs.add(key);
    if(work){
      const original=day.templates[tpl].parts.find(p=>p[0]===s);
      if(original?.[1]!==n||original[2]!=="car-driver")throw Error("Bicycle outing must replace a diary driver leg: "+key);
      for(rule of workplaceRules){
        if(work(d,i,tpl,original))throw Error("Commute and discretionary outing affect the same leg: "+key);
      }
    }
    tourRows[Math.floor(s/60)].push([d,i,tpl,[s,n,"bike"],a,b,access]);
  }
}
const runs=Object.fromEntries([...rules,...tourRules.map(name=>name+"-added")].map(name=>[name,{coverage:{legs:0,unlocated:0,colocated:0,rejected:0,routed:0},
  sites:sites.map(s=>({counts:s.hours.map(()=>0),examples:s.hours.map(()=>null),
    approaches:Object.fromEntries(Object.keys(s.approaches).map(d=>[d,0])),diaries:new Map()}))}]));
const cache=new Map(),crossings=new WeakMap();
const shortestCache=new Map(),nodeIds=profile&&new Map(net.nodes.map((p,i)=>[p,i]));
const flatCache=new Map(),climbing=new WeakMap();
const distances=new WeakMap();
function metresOn(route,arcs,cache){
  if(!cache.has(route)){
    let metres=0;
    for(let i=2;i<route.points.length-1;i++){
      const a=route.points[i-1],b=route.points[i];
      if(arcs.has(nodeIds.get(a)*net.nodes.length+nodeIds.get(b)))metres+=distance(a,b);
    }
    cache.set(route,metres);
  }
  return cache.get(route);
}
const onBikeway=route=>metresOn(route,graph.bikeways,distances);
const uphillMetres=route=>metresOn(route,graph.uphill,climbing);
if(profile)for(const run of Object.values(runs))
  run.detours={longer:0,shortestMetres:0,riddenMetres:0,shortestBikewayMetres:0,riddenBikewayMetres:0};
if(withoutHills)for(const run of Object.values(runs))
  run.hills={changed:0,baselineMetres:0,riddenMetres:0,baselineUphillMetres:0,riddenUphillMetres:0};
const audit=process.argv[3]?[]:null;
function rows(kind,hour){
  if(kind==="tour")return tourRows[hour];
  const bytes=readFileSync(join(root,dir+kind+"-"+hour+".bin"));
  return streetLegs(new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength),day);
}
const kinds=work?["walk","bike","commute"]:["bike"];
if(v.tours)kinds.push("tour");
for(let hour=4;hour<28;hour++)for(const kind of kinds){
  for(const [d,i,tpl,part,a,b,access] of rows(kind,hour)){
    const [start,duration]=part;if(Math.floor(start/60)!==hour)continue;
    for(rule of (kind==="tour"?(access?["cycleTours-added","cycleAccess-added"]:["cycleTours-added"]):rules)){
      const state=rule==="city"||!work||kind==="tour"?null:work(d,i,tpl,part);
      if(activeStreetMode(state,part,kind==="commute")!=="bike")continue;
      const run=runs[rule],c=run.coverage;c.legs++;
      const leg=activeStreetLeg(state,part,a,b,kind==="commute",speeds);
      if(!leg){c.unlocated++;continue;}
      const [from,to,speed]=leg;
      if(!distance(places[from],places[to])){c.colocated++;continue;}
      if(audit&&sites.some(s=>distance(places[from],s.point)+distance(places[to],s.point)<=duration*speed+44))
        audit.push([rule,from,to,start,duration,speed*duration]);
      const route=budgetRoute(graph,places,cache,from,to,BIKE,speed*duration);
      if(profile){
        const base=budgetRoute(shortest,places,shortestCache,from,to,BIKE,speed*duration);
        if(!!base!==!!route)throw Error("Route preference changed the feasible cohort");
        if(route){
          const d=run.detours;
          if(route.metres>base.metres+1)d.longer++;
          d.shortestMetres+=base.metres;d.riddenMetres+=route.metres;
          d.shortestBikewayMetres+=onBikeway(base);d.riddenBikewayMetres+=onBikeway(route);
        }
      }
      if(!route){
        if(kind==="tour")throw Error("Admitted outing cannot be ridden in the replay: "+[d,i,start]);
        c.rejected++;continue;
      }
      c.routed++;
      if(withoutHills){
        const plain=budgetRoute(withoutHills,places,flatCache,from,to,BIKE,speed*duration);
        if(!plain)throw Error("Grade preference changed the feasible cohort");
        const h=run.hills;
        if(plain.points.length!==route.points.length||plain.points.some((p,i)=>p!==route.points[i]))h.changed++;
        h.baselineMetres+=plain.metres;h.riddenMetres+=route.metres;
        h.baselineUphillMetres+=uphillMetres(plain);h.riddenUphillMetres+=uphillMetres(route);
      }
      if(!crossings.has(route))crossings.set(route,sites.map(site=>passage(route,site)));
      crossings.get(route).forEach((hit,j)=>{
        if(!hit)return;
        const [f,approach]=hit,minute=start+duration*f,h=sites[j].hours.indexOf(Math.floor(minute/60));if(h<0)return;
        const site=run.sites[j];
        site.counts[h]++;site.approaches[approach]++;
        site.diaries.set(tpl,(site.diaries.get(tpl)??0)+1);
        site.examples[h]??=[day.das[d],i,minute];
      });
    }
  }
}
if(runs.city.coverage.legs!==manifest.bike)throw Error("Incomplete bicycle diary index");
if(v.tours){
  // These rows have disjoint resident/leg keys. Combine their observations
  // before summarizing diary support so a diary used by both counts once.
  const add=(a,b)=>Object.fromEntries(Object.entries(a).map(([key,n])=>[key,n+(b[key]??0)]));
  const legsByRule=new Map();
  for(const leg of audit??[]){
    const name=leg[0];
    if(!legsByRule.has(name))legsByRule.set(name,[]);
    legsByRule.get(name).push(leg);
  }
  for(const workplace of rules)for(const tour of tourRules){
    const name=workplace==="city"?tour:workplace+"+"+tour;
    const commute=runs[workplace], outings=runs[tour+"-added"];
    const combined={coverage:add(commute.coverage,outings.coverage),sites:[]};
    if(profile)combined.detours=add(commute.detours,outings.detours);
    if(withoutHills)combined.hills=add(commute.hills,outings.hills);
    for(let i=0;i<sites.length;i++){
      const a=commute.sites[i], b=outings.sites[i], diaries=new Map(a.diaries);
      for(const [tpl,n] of b.diaries)diaries.set(tpl,(diaries.get(tpl)??0)+n);
      combined.sites.push({
        counts:a.counts.map((n,h)=>n+b.counts[h]),
        examples:a.examples.map((example,h)=>example??b.examples[h]),
        approaches:add(a.approaches,b.approaches),
        diaries
      });
    }
    runs[name]=combined;
    if(audit)for(const row of [...(legsByRule.get(workplace)??[]),...(legsByRule.get(tour+"-added")??[])])
      audit.push([name,...row.slice(1)]);
  }
  for(const tour of tourRules)delete runs[tour+"-added"];
}
for(const {coverage:c,sites} of Object.values(runs)){
  if(c.legs!==c.unlocated+c.colocated+c.rejected+c.routed)throw Error("Unaccounted bicycle legs");
  for(const s of sites){
    s.largestDiary=Math.max(0,...s.diaries.values());s.diaries=s.diaries.size;
    if(Object.values(s.approaches).reduce((a,b)=>a+b,0)!==s.counts.reduce((a,b)=>a+b,0))
      throw Error("Bicycle approaches and hours differ");
  }
}
if(audit)writeFileSync(process.argv[3],JSON.stringify(audit));
console.log(JSON.stringify({...input,runs}));
