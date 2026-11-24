// Materialize the ordinary timetable's route cache so opening and scrubbing
// the map do not have to repeat the full A* workload.
import {readFileSync,writeFileSync,mkdirSync,mkdtempSync,renameSync,existsSync,rmSync} from "node:fs";
import {createHash} from "node:crypto";
import {join} from "node:path";
import {Network,roadMode,BIKE} from "../public/lab/vancouver-network.js";
import {findRoute,routeKey} from "../public/lab/weekday-pathfinder.js";
import {bicycleMetresPerMinute} from "../public/lab/street-pedestrians.js";

const root=process.argv[2]??"public/data/vancouver";
const requested=process.argv[3];
const read=name=>JSON.parse(readFileSync(join(root,name)));
const joint=requested==="--joint"?process.argv[4]:null;
if(requested==="--joint"&&!/^[a-f0-9]{20}$/.test(joint??""))throw Error("Expected a combined weekday ID");
const current=joint?read("joint-weekday/"+joint+"/report.json").versions:
  existsSync(join(root,"current.json"))?read("current.json"):null;
const dayVersion=(joint?current.day:requested)??current?.day??read("cityday/current.json").version;
const streets=current?.streets??read("streets/current.json").version;
const atlas=current?.atlas??read("cityday/current.json").atlas;
const profileBytes=readFileSync(join(root,"drive-profile/"+streets+".json"));
const profile=JSON.parse(profileBytes);
const [day,places,roster]=[
  read("cityday/"+dayVersion+"/day.json"),read("cityday/"+dayVersion+"/places.json"),
  read("atlas/"+atlas+"/atlas.json")
];
if(day.population!==roster.city.population||day.das.length!==Object.keys(roster.das).length||
   day.das.some(da=>!Object.hasOwn(roster.das,da))||profile.streets!==streets)
  throw Error("The waypoint, atlas and street files refer to different releases");
const graph=new Network(read("streets/"+streets+"/network.json"),null,profile);
const cyclePointer="cycling/"+streets+".json";
const cycling=existsSync(join(root,cyclePointer))?read(cyclePointer).version:null;
const cycles=cycling&&new Network(read("cycling/"+cycling+"/network.json"));
const pure=day.templates.map((template,i)=>template.parts.filter(([s,d,m])=>roadMode(m)&&
  roster.templates[i].episodes.every(([start,n,,mode])=>start>=s+d||start+n<=s||mode===m)));
const byHour=Array.from({length:24},()=>new Set()), routes=new Map();
for(const [, ,template, plan] of day.sample) {
  for(const [start,duration,recorded,a,b] of pure[template]){
    const from=places[plan[a]],to=places[plan[b]],mode=roadMode(recorded);
    if(!from||!to||mode===BIKE&&!cycles)continue;
    const speed=mode===2?380:mode===BIKE?bicycleMetresPerMinute:150;
    const key=routeKey(mode,from,to,duration,speed,false);
    if(!routes.has(key))routes.set(key,[mode,from,to,duration,speed,false]);
    for(let h=Math.floor(start/60);h<Math.ceil((start+duration)/60);h++)byHour[h-4].add(key);
  }
}
const key=[atlas,dayVersion,streets].join("_");
const parent=join(root,"overview-routes");
mkdirSync(parent,{recursive:true});
const target=mkdtempSync(join(parent,".building-"));
const hash=createHash("sha256");
const results=new Map();
for(const hour of [8,9,7,16,17,...Array.from({length:24},(_,i)=>i+4)].filter((h,i,order)=>h<28&&order.indexOf(h)===i)){
  const batch=[];
  for(const id of byHour[hour-4]){
    if(!results.has(id)){
      const [mode,...args]=routes.get(id);
      results.set(id,findRoute(mode===BIKE?cycles:graph,mode,...args));
    }
    batch.push([id,results.get(id)]);
  }
  const file=hour+".json",content=JSON.stringify(batch);
  hash.update(file).update(content);writeFileSync(join(target,file),content);
  console.log(root,dayVersion,hour,batch.length,batch.filter(([,route])=>route).length);
}
const metadata=JSON.stringify({atlas,day:dayVersion,streets,cycling,sourceDigest:profile.sourceDigest,
  driveProfileDigest:createHash("sha256").update(profileBytes).digest("hex")});
hash.update(metadata);writeFileSync(join(target,"manifest.json"),metadata);
const version=hash.digest("hex").slice(0,20);
const destination=join(parent,version);
if(!existsSync(destination))renameSync(target,destination);
else rmSync(target,{recursive:true});
const ptr=join(parent,"."+key+"-"+process.pid+".json");
writeFileSync(ptr,JSON.stringify({version}));renameSync(ptr,join(parent,key+".json"));
console.log("Published",version,routes.size,"unique sample routes");
