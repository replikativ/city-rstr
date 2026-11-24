import {BIKE,CAR,Network} from "./vancouver-network.js";
import {scanDrivers,nearbyPositions} from "./street-pedestrians.js";

const modes=new Map();
let places=[],rows={},scan;
function publishDrivers(job){
  if(job!==scan)return;
  try{
    const until=performance.now()+60;
    let next;
    do{
      next=job.iterator.next();
      if(next.value)job.drivers.push(next.value);
    }while(!next.done&&performance.now()<until);
    if(next.done||job.shown!==job.drivers.length){
      job.shown=job.drivers.length;
      job.drivers.sort((a,b)=>a[4]-b[4]||a[0]-b[0]||a[1]-b[1]);
      self.postMessage({dots:[...job.dots,...job.drivers],minute:job.minute,centre:job.centre,revision:job.revision,
        checkingDrivers:!next.done});
    }else self.postMessage({revision:job.revision});
    if(!next.done)setTimeout(()=>publishDrivers(job),0);
  }catch(error){self.postMessage({error:error.message});}
}
self.onmessage=async({data})=>{
  try{
    if(data.network){
      const profile=data.driving?await fetch(data.driving).then(r=>r.ok?r.json():null):null;
      await Promise.all([[1,data.network],[BIKE,data.cycling]].filter(([,url])=>url).map(async([mode,url])=>{
        const r=await fetch(url);
        if(!r.ok)throw Error("Unable to load the street network for "+(mode===1?"walking.":"cycling."));
        const graph=new Network(await r.json(),mode===BIKE?data.bikeways:null,mode===1?profile:null);
        modes.set(mode,{graph,paths:new Map()});
        if(mode===1&&graph.driveSpeed)modes.set(CAR,{graph,paths:new Map()});
      }));
      self.postMessage({ready:true,drivers:modes.has(CAR)});
    }else if(data.rows){
      scan=null;rows=data.rows;places=places.concat(data.places);
    }else{
      const dots=[];
      for(const [mode,{graph,paths}] of modes){
        if(mode!==CAR)for(const [d,i,x,y,away,tag,segment] of nearbyPositions(graph,places,paths,rows[mode]||[],data.minute,data.centre,mode,true))
          dots.push([d,i,x,y,away,mode,null,tag,null,segment]);
      }
      const driver=modes.get(CAR),{minute,revision,centre}=data;
      if(!driver||!rows[CAR]?.length)self.postMessage({dots,minute,centre,revision});
      else{
        scan={minute,centre,revision,dots,drivers:[],iterator:scanDrivers(driver.graph,places,driver.paths,rows[CAR],minute,centre,true)};
        publishDrivers(scan);
      }
    }
  }catch(error){self.postMessage({error:error.message});}
};
