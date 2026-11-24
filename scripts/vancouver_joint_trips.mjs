// Extract the legs of the tract-fitted replay using its ClojureScript workplace resolver.
import {readFileSync,writeFileSync} from "node:fs";
import {join} from "node:path";
import {residentTrips} from "../public/js/vancouver/workplaces.js";

const [root,input,output]=process.argv.slice(2);
const read=path=>JSON.parse(readFileSync(join(root,path),"utf8"));
const {atlas,day,streets,outbound,worksites,tracts,outings,priority,surveyModes,incomeBands,incomeModes,knownBands,vehicleAccess,vehicleTraffic,
  workplaceDrives}=JSON.parse(readFileSync(input,"utf8"));
const dayDir="cityday/"+day+"/",atlasDir="atlas/"+atlas+"/",outDir="outbound/"+outbound+"/";
const model=read(dayDir+"day.json"),population=read(atlasDir+"atlas.json"),places=read(dayDir+"places.json");
const report=read(outDir+"report.json"),tract=read("tract-workplaces/"+tracts+"/worksites.json");
if(report.atlas!==atlas||report.day!==day||report.neighbourhoodFit?.streets!==streets||
   tract.atlas!==atlas||tract.day!==day||tract.outbound!==outbound||tract.worksites!==worksites)
  throw Error("The tract workplace fit and weekday differ.");
const resolve=residentTrips(report,read(outDir+"assignments.json"),read(outDir+"local-modes.json"),null,tract,()=>"tracts");
const short=read("short-walks/"+day+"_"+streets+".json");
if(short.atlas!==atlas||short.day!==day||short.streets!==streets)
  throw Error("The short walks and weekday differ.");
const tours=read("discretionary-outings/"+outings+"/tours.json");
const parts=model.templates.map((t,j)=>t.parts.filter(row=>row[2]!=="stop").map(row=>{
  const [start,duration]=row;
  const modes=new Set(population.templates[j].episodes.filter(e=>start<=e[0]&&e[0]<start+duration).map(e=>e[3]));
  return {row,transit:modes.has("transit"),pure:[...modes].every(m=>m==="walk"||m==="transit"),driver:modes.has("car-driver"),singleDriver:modes.size===1&&modes.has("car-driver"),
    driving:modes.has("car-driver")&&[...modes].every(m=>m==="walk"||m==="car-driver"),
    primary:surveyModes[priority.find(mode=>modes.has(mode))]??"Other / unspecified"};
}));
const core=model.areas.indexOf("Downtown"),areaCount=model.areas.length;
const home=new Map(Object.entries(population.areas).flatMap(([name,group])=>
  group.das.map(da=>[da,model.areas.indexOf(name)])));
const flows=Array.from({length:24},()=>Array.from({length:areaCount},()=>[0,0]));
const walkChange=Array.from({length:1441},()=>Array(areaCount+2).fill(0));
const transit=[],excluded={mixed:0,unlocated:0},keptWalks=[],streetWalks=[];
const residentBlocks=new Map();
const stats={ridesFromModeChanges:0,ridesWithMovedEndpoints:0,walksWithWorkplaceChanges:0};
if(workplaceDrives&&!tract.preserveDiaryModes)throw Error("The driving comparison requires unchanged diary modes.");
const paid=workplaceDrives?report.slots.map(slots=>new Set(slots)):null;
const drives=workplaceDrives?{trips:[],all:0,mixed:0,external:0,unlocated:0}:null;
const adultFifths=age=>age>=4&&age<=13?5:age===3?2:0;
const adultModeDelta={};
const addMode=(mode,amount)=>{adultModeDelta[mode]=(adultModeDelta[mode]??0)+amount;};
const bands=incomeBands?JSON.parse(readFileSync(incomeBands,"utf8")):null;
const bandRows=()=>Array.from({length:knownBands.length+1},()=>Array(incomeModes.length).fill(0));
const income=bands?{original:bandRows(),combined:bandRows(),adultFifths:Array(knownBands.length+1).fill(0)}:null;
const modeIndex=new Map(incomeModes?.map((mode,i)=>[mode,i]));
const weights=[];
const noVehicle=vehicleAccess?JSON.parse(readFileSync(vehicleAccess,"utf8")):null;
const vehicle=noVehicle?{tours:[],driverTrips:0,driverByIncome:bands?Array(knownBands.length+1).fill(0):null}:null;
const trafficRows=vehicleTraffic?JSON.parse(readFileSync(vehicleTraffic,"utf8")):null;
const trafficModes=["car-driver","car-passenger","ridehail","taxi","bike","transit","walk","other"];
const traffic=trafficRows?new Map(trafficRows.map(row=>[row.slice(0,3).join("/"),row])):null;
const trafficDelta=traffic?Array.from({length:24},()=>Array.from({length:areaCount},()=>[0,1].map(()=>Array(trafficModes.length).fill(0)))):null;
if(traffic&&traffic.size!==trafficRows.length)throw Error("A vehicle scenario trip is listed twice.");
function changeTraffic(d,i,start,duration,a,b,oldMode){
  const key=d+"/"+i+"/"+start,row=traffic.get(key);
  if(!row)return;
  const [,,,window,origin,destination,mode]=row;
  const newIndex=trafficModes.indexOf(mode),oldIndex=trafficModes.indexOf(oldMode);
  if(window!==duration||origin!==a||destination!==b||newIndex<0||Math.min(a,b)<0)
    throw Error("A vehicle replacement changed a diary endpoint or its time window.");
  traffic.delete(key);
  const from=places[a][2],to=places[b][2];
  if(from<0||to<0||(from===core)===(to===core))return;
  const h=Math.floor((to===core?start+duration:start)/60)%24;
  const flow=trafficDelta[h][home.get(model.das[d])][to===core?0:1];
  flow[oldIndex<0?trafficModes.length-1:oldIndex]--;
  flow[newIndex]++;
}
const incomeTrip=(stage,d,i,mode,weight)=>{
  income[stage][bands[d][i]][modeIndex.get(mode)]+=weight;
};
const byArea=model.das.map(()=>[]);
for(const row of short.walks)byArea[row[0]].push(row);
function walkBoundary(d,a,b,start,duration){
  const from=places[a][2],to=places[b][2],area=home.get(model.das[d]);
  if(from!==core&&to===core)flows[Math.floor((start+duration)/60)%24][area][0]++;
  if(from===core&&to!==core)flows[Math.floor(start/60)%24][area][1]++;
}
function movedInterval(start,end,area,n){
  walkChange[start-240][area]+=n;
  walkChange[end-240][area]-=n;
}
let adultWalkFifths=0,age45Walks=0,age20Walks=0;
for(const [d,da] of model.das.entries()){
  const {people}=read(atlasDir+da+".json"),{plans}=read(dayDir+da+".json"),privateCount=population.das[da].private;
  if(people.length!==plans.length)throw Error("Household and weekday rosters differ.");
  if(bands&&bands[d].length!==people.length)throw Error("Household income and weekday rosters differ.");
  if(noVehicle&&noVehicle[d].length!==people.length)throw Error("Household vehicle access and weekday rosters differ.");
  if(income)weights[d]=new Uint8Array(people.length);
  for(const [i,person] of people.entries()){
    const template=person[7],plan=plans[i],adult=i<privateCount?adultFifths(person[0]):0;
    if(income&&adult){weights[d][i]=adult;income.adultFifths[bands[d][i]]+=adult;}
    const constrained=noVehicle?.[d][i]===1&&adult,slots=model.templates[template].slots;
    let tour=null;
    for(const {row,transit:diaryTransit,pure,primary,driving,driver,singleDriver} of parts[template]){
      const [start,duration,,a,b]=row,work=resolve(d,i,template,row);
      const assigned=work?.replaceMode??work?.assignedMode;
      if(income&&adult){
        incomeTrip("original",d,i,primary,adult);
        incomeTrip("combined",d,i,assigned?(surveyModes[assigned]??"Other / unspecified"):primary,adult);
      }
      const from=work?.external?-1:work?.overrides?.get(a)??plan[a]??-1;
      const to=work?.external?-1:work?.overrides?.get(b)??plan[b]??-1;
      if(drives&&driver&&(paid[template].has(a)||paid[template].has(b))){
        drives.all++;
        if(!singleDriver)drives.mixed++;
        else if(work?.external)drives.external++;
        else if(Math.min(from,to,plan[a]??-1,plan[b]??-1)<0)drives.unlocated++;
        else drives.trips.push([d,i,start,duration,plan[a],plan[b],from,to,Number(paid[template].has(a))]);
      }
      if(traffic)changeTraffic(d,i,start,duration,from,to,assigned??row[2]);
      if(constrained){
        const mode=assigned?(surveyModes[assigned]??"Other / unspecified"):primary;
        if(mode==="Auto driver"){
          vehicle.driverTrips++;
          if(bands)vehicle.driverByIncome[bands[d][i]]++;
        }
        if(slots[a]==="home")tour=[];
        if(!(assigned?assigned==="car-driver":driving)||Math.min(from,to)<0||from===to||
           (tour?.length&&tour.at(-1)[3]!==from))tour=null;
        tour?.push([start,duration,from,to]);
        if(slots[b]==="home"){
          if(tour?.length>1&&tour[0][2]===to)vehicle.tours.push([d,i,adult,tour]);
          tour=null;
        }
      }
      if(assigned&&adult){
        addMode(primary,-adult);
        addMode(surveyModes[assigned]??"Other / unspecified",adult);
      }
      if(assigned?assigned!=="transit":!diaryTransit)continue;
      if(!assigned&&!pure)excluded.mixed++;
      else if(Math.min(from,to)<0)excluded.unlocated++;
      else{
        transit.push([da,i,start,duration,from,to]);
        if(!diaryTransit)stats.ridesFromModeChanges++;
        if(from!==plan[a]||to!==plan[b])stats.ridesWithMovedEndpoints++;
      }
    }
  }
  for(const row of byArea[d]){
    const [,i,start,duration,a,b]=row,template=people[i][7],plan=plans[i];
    const work=resolve(d,i,template,[start,duration,"walk",a,b]);
    if(work?.external||(work?.overrides?.get(a)??plan[a])!==plan[a]||(work?.overrides?.get(b)??plan[b])!==plan[b]){
      stats.walksWithWorkplaceChanges++;
      continue;
    }
    const boundary=model.templates[template].parts.find((part,j,all)=>
      part[2]==="stop"&&part[3]===b&&part[0]>=start&&part[0]<=start+duration&&all[j-1]?.[3]===a)?.[0];
    if(boundary===undefined)throw Error("A reconstructed walk has lost its diary boundary.");
    const origin=plan[a],dest=plan[b],end=start+duration;
    movedInterval(start,boundary,places[origin][2],-1);
    movedInterval(boundary,end,places[dest][2],-1);
    movedInterval(start,end,areaCount,1);
    keptWalks.push(row);streetWalks.push([d,i,start,duration,origin,dest]);
    const age=i<privateCount?people[i][0]:0;
    adultWalkFifths+=adultFifths(age);age45Walks+=Number(age===9);age20Walks+=Number(age>=4&&age<=13);
    if(income&&adultFifths(age))incomeTrip("combined",d,i,"Walking",adultFifths(age));
    walkBoundary(d,origin,dest,start,duration);
    const key=d+"/"+i;
    if(!residentBlocks.has(key))residentBlocks.set(key,[]);
    residentBlocks.get(key).push([start,end]);
  }
}
for(const [d,i,a,b,,mode,start,there,dwell,back] of tours){
  if(mode!=="walk"||residentBlocks.get(d+"/"+i)?.some(([lo,hi])=>lo<start+there+dwell+back&&start<hi))
    throw Error("An added shopping outing overlaps a reconstructed trip.");
  walkBoundary(d,a,b,start,there);
  walkBoundary(d,b,a,start+there+dwell,back);
  if(income&&weights[d][i])incomeTrip("combined",d,i,"Walking",2*weights[d][i]);
}
for(let t=1;t<walkChange.length;t++)
  for(let k=0;k<walkChange[t].length;k++)walkChange[t][k]+=walkChange[t-1][k];
if(walkChange.some(row=>row.reduce((a,b)=>a+b,0)!==0)||walkChange.at(-1).some(Boolean))
  throw Error("Reconstructed walk occupancy does not conserve residents.");
if(traffic?.size)throw Error("Some vehicle replacements could not be joined to the combined weekday.");
writeFileSync(output,JSON.stringify({transit,excluded,flows,stats,adultModeDelta,income,vehicle,
  drives,
  traffic:trafficDelta&&{modes:trafficModes,delta:trafficDelta},
  short:{...short,gaps:{...short.gaps,resolved:keptWalks.length},walks:keptWalks,streetWalks,
    occupancyDelta:walkChange.slice(0,-1),adultWalks:adultWalkFifths/5,age45Walks,age20Walks}}));
