import {metroRoadNetwork} from "./vancouver-network.js";
import {track} from "../js/vancouver/route-timeline.js";

const id=/^[a-f0-9]{20}$/;
const fmt=n=>n.toLocaleString("en-CA");
const el=name=>document.getElementById(name);

export async function loadOutboundRoadJobs(root,joint,basePlaces,json,pinned){
  const family=root+"outbound-road-jobs/",requested=new URLSearchParams(location.search).get("outboundRoad");
  const active=requested!=="off"&&(requested||pinned);
  let version=active||pinned;
  if(!version){
    const response=await fetch(family+joint.id+".json");
    if(response.status===404)return null;
    if(!response.ok)throw Error("Outbound workplace evidence is unavailable.");
    ({version}=await response.json());
  }
  if(!id.test(version))throw Error("Invalid outbound workplace release.");
  const folder=family+version+"/",report=await json(folder+"report.json");
  if(report.joint!==joint.id||!id.test(report.network)||report.clock!=="free-flow"||report.basePlaces!==basePlaces.length||
    Object.entries(joint.versions).some(([key,value])=>report.versions[key]!==value)||
    Object.entries(joint.workplaces).some(([key,value])=>report.workplaces[key]!==value))
    throw Error("The outbound workplace release belongs to a different weekday.");
  const basis=el("outbound-road-status"),panel=el("outbound-road-jobs");
  const link=el("outbound-road-link");
  const data=Object.values(report.coverage);
  const total=key=>fmt(data.reduce((n,row)=>n+(row[key]??0),0));
  basis.textContent=total("locatedWorkers")+" residents receive a mapped job in their assigned municipality. "+
    total("locatedDriverLegs")+" of "+total("driverLegs")+" outbound work drives fit the full diary schedule.";
  link.textContent=active?"Return to municipality-only jobs":"Replay mapped outbound jobs";
  const writeLink=()=>{
    const url=new URL(location.href);
    if(active&&pinned)url.searchParams.set("outboundRoad","off");
    else if(active)url.searchParams.delete("outboundRoad");
    else url.searchParams.set("outboundRoad",version);
    url.hash="outbound-road-jobs";
    link.href=url;
  };
  writeLink();link.onfocus=writeLink;link.onpointerdown=writeLink;
  panel.hidden=false;
  if(!active)return null;

  const jobPoints=await json(folder+"places.json"),covered=new Set(report.areas),shards=new Map();
  const pending=new Map();
  let road,lastMinute=-1,lastTransit=-1;
  const routes=new Map();
  const evidence=fetch(root+"outbound-road-counts/"+version+".json").then(async response=>{
    if(!response.ok)return null;
    const result=await response.json();
    return result.jobs===version&&result.joint===joint.id&&result.network===report.network&&result.clock===report.clock?result:null;
  }).catch(()=>null);
  let clock;
  const preview=new Map();
  evidence.then(result=>{
    clock=result?.workClock?.counts;
    for(const [da,row] of result?.workClock?.sample??[])preview.set(da+"/"+row[0],row);
  });
  return {
    version, report, evidence,
    atWork(minute,transit=0){
      const index=Math.floor(minute)-240,row=clock?.[index];
      if(!row)return 0;
      const [unlocated,...counts]=row,placed=counts.reduce((a,b)=>a+b,0);
      if(index!==lastMinute||lastTransit!==transit){
        lastMinute=index;lastTransit=transit;
        const status=el("outbound-road-at-work");
        status.textContent=fmt(placed+transit)+" residents are at mapped jobs outside Vancouver. "+
          fmt(unlocated-transit)+" are at external jobs with a municipality only.";
        status.hidden=false;
      }
      return placed;
    },
    async mapContext(){
      const base=await json(root+"commuter-basemap/"+report.network+".json");
      if(base.network!==report.network)throw Error("The commuter map and street routes use different releases.");
      return base;
    },
    async loadResident(da){
      if(!covered.has(da))return;
      if(!pending.has(da))pending.set(da,json(folder+da+".json").then(rows=>shards.set(da,new Map(rows.map(row=>[row[0],row]))))
        .catch(error=>{pending.delete(da);throw error;}));
      await pending.get(da);
    },
    async loadRoad(){road??=await metroRoadNetwork(root,report.network,json);},
    state(da,i,part,minute,drawRoute){
      const resident=da+"/"+i,visible=preview.get(resident);
      const row=shards.get(da)?.get(i)??visible;
      if(!row)return null;
      const [,site,work,legs]=row,job=jobPoints[site];
      const [start,dur,mode,a]=part;
      if(mode==="stop"&&work.includes(a))return {mode,p:job,a:job,kind:"job",description:job[3]+" · "+job[4]};
      const leg=legs.find(([s])=>s===start);
      if(!leg||(!drawRoute&&!visible)||!road)return null;
      const [,,anchor,returning,driver,assigned]=leg;
      const [from,to]=returning?[job,basePlaces[anchor]]:[basePlaces[anchor],job];
      const key=resident+"/"+start;
      if(!routes.has(key)){
        const route=road.driveRoute(from,to,dur,start);
        if(!route||Math.abs(route.minutes-assigned)>1e-5)throw Error("The published outbound trip and road graph disagree.");
        routes.set(key,route);
      }
      const route=routes.get(key),elapsed=minute-start;
      const motion=track(route.path,route.offsets,Math.min(elapsed,route.minutes),0);
      const destination=returning?(to[3]||"next diary stop"):(job[3]+" · "+job[4]);
      const description=elapsed>=route.minutes?"At "+destination+" · waiting for the next diary activity":
        (driver?"Driving to ":"Car passenger to ")+destination+" · "+route.minutes.toFixed(1)+" min modeled drive";
      return {mode,start,dur,a:from,b:to,p:motion.position,path:route.path,routed:true,description};
    }
  };
}
