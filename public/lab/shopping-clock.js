const el=id=>document.getElementById(id);
const release=/^[a-f0-9]{20}$/;
const count=n=>n.toLocaleString("en-CA");

export function shiftedShopping(row,minute,places,speed){
  const [,,original,there,dwell,back,origin,shop,home,,shift]=row;
  const start=original+shift,arrive=start+there,leave=arrive+dwell,end=leave+back;
  if(minute<Math.min(start,original)||minute>=Math.max(end,end-shift))return null;
  const a=places[origin], b=places[shop], c=places[home];
  const stop=(point,kind,activityLabel)=>({mode:"stop",a:point,p:point,kind,activityLabel});
  function ride(from,to,begin,dur,kind){
    return {mode:"bike",a:from,b:to,kind,start:begin,dur,metresPerMinute:speed,
      activityLabel:kind==="store"?"Cycling to shop · shifted timing":"Cycling home from the shop · shifted timing"};
  }
  if(minute<start)return stop(a,"recreation","Finishing recreation before shopping");
  if(minute<arrive)return ride(a,b,start,there,"store");
  if(minute<leave)return stop(b,"store","Shopping · shifted timing");
  if(minute<end)return ride(b,c,leave,back,"home");
  return stop(c,"home","At home after shopping");
}

async function publishedClock(root,joint,cycling,json,requested){
  const wanted=requested??(await json(root+joint.id+".json")).version;
  if(!release.test(wanted))throw Error("Invalid bicycle shopping clock release.");
  const path=root+wanted+"/",report=await json(path+"report.json");
  if(report.schema!==1||report.joint!==joint.id||report.cycling!==cycling||report.outings!==joint.outings||
     Object.entries(joint.versions).some(([key,value])=>report.versions[key]!==value))
    throw Error("This bicycle shopping clock uses a different weekday or street network.");
  return {wanted,path,report};
}

export async function loadShoppingClock(root,joint,cycling,places,json,requested){
  const {wanted,path,report}=await publishedClock(root,joint,cycling,json,requested);
  const rows=await json(path+"tours.json");
  if(!rows.length)throw Error("The bicycle shopping clock has no tours.");
  const residents=new Map(),originals=new Set(),byHour=Array.from({length:28},()=>[]);
  for(const row of rows){
    const [d,i,start,there,dwell,back,a,b,c,,shift]=row,id=d+"/"+i;
    const tours=residents.get(id)??[];
    tours.push(row);residents.set(id,tours);
    for(const [old,duration,from,to] of [[start,there,a,b],[start+there+dwell,back,b,c]]){
      originals.add(id+"/"+old);
      const minute=old+shift;
      for(let h=Math.floor(minute/60);h<=Math.floor((minute+duration-1)/60);h++)
        byHour[h].push([d,i,minute,duration,from,to,report.speed,false,"shopping-clock"]);
    }
  }
  return {
    version:wanted,report,
    state(d,i,minute){
      for(const row of residents.get(d+"/"+i)??[]){
        const state=shiftedShopping(row,minute,places,report.speed);
        if(state)return state;
      }
      return null;
    },
    replaces:(d,i,minute)=>originals.has(d+"/"+i+"/"+minute),
    rows:hour=>byHour[hour],
    delta:minute=>report.occupancyDelta[minute-240],
  };
}

export async function showShoppingClock(root,joint,cycling,active,day,json,follow,clock){
  const panel=el("shopping-clock-info");
  let published;
  if(active)published={wanted:active.version,report:active.report};
  else{
    const response=await fetch(root+joint.id+".json");
    if(response.status===404)return;
    if(!response.ok)throw Error("The bicycle shopping comparison is unavailable.");
    published=await publishedClock(root,joint,cycling,json,(await response.json()).version);
  }
  const {report,wanted}=published,{recorded=0,booked=0,slack=0}=report.transitAt1630;
  const {before,after,atOriginal}=report.tripPeaks["pre-pm"];
  const {connected=0,candidate=0,changed=0}=report.counts["pre-pm"]??{};
  el("shopping-clock-report").textContent=count(connected)+" of "+count(candidate)+
    " eligible bicycle tours fit both street routes. The comparison shifts "+count(changed)+
    " tours by up to "+report.radius+" minutes. Departures at "+clock(before[0])+" change from "+
    count(before[1])+" to "+count(atOriginal)+". The largest count in this period becomes "+count(after[1])+" at "+clock(after[0])+".";
  el("shopping-clock-transit").textContent="The main 16:30 shopping diary has "+count(recorded)+" work-to-shop transit departures. "+
    count(booked)+" fit a scheduled journey and "+count(slack)+" of those have a minute of slack after the boarding margin. These transit schedules stay fixed.";
  const link=el("shopping-clock-link"),button=el("shopping-clock-follow");
  link.textContent=active?"Replay recorded shopping times":"Spread eligible bicycle departures";
  const update=()=>{
    const url=new URL(location.href);
    if(active)url.searchParams.delete("shoppingClock");else url.searchParams.set("shoppingClock",wanted);
    url.searchParams.set("jointRun",joint.id);
    url.searchParams.set("tripTiming","pre-pm");
    url.hash="shopping-clock-info";
    link.href=url;
  };
  update();
  for(const event of ["focus","pointerdown"])link.addEventListener(event,update);
  if(active){
    const [d,i,start,there,,,,,,,shift]=report.example;
    button.hidden=false;
    button.onclick=()=>follow(day.das[d],i,start+shift+Math.floor(there/2));
  }
  panel.hidden=false;
  if(location.hash==="#shopping-clock-info"||active)panel.open=true;
}
