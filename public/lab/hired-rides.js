const el=id=>document.getElementById(id);
const releaseId=/^[a-f0-9]{20}$/;
const key=(d,i)=>d*65536+i;
export const isHired=mode=>mode==="taxi"||mode==="ridehail";
export const hiredLabel=mode=>mode==="taxi"?"Taxi":"Ride-hail";

export class HiredRides {
  constructor({rows},places,enabled){
    Object.assign(this,{places,enabled});
    this.people=new Map();
    this.hours=Array.from({length:24},()=>[]);
    for(const row of rows){
      const [d,i,start,duration]=row,id=key(d,i);
      if(!this.people.has(id))this.people.set(id,[]);
      this.people.get(id).push(row);
      for(let hour=Math.floor(start/60);hour<Math.ceil((start+duration)/60);hour++)
        this.hours[hour-4].push(row);
    }
  }

  apply(state,d,i){
    if(!this.enabled||state.mode!=="car-passenger")return state;
    const ride=this.people.get(key(d,i))?.find(([, ,start,duration,a,b,,assigned])=>
      assigned&&start===state.start&&duration===state.dur&&this.places[a]===state.a&&this.places[b]===state.b);
    return ride?{...state,mode:ride[6],method:"survey-based passenger assignment",hired:true}:state;
  }

  streetRows(hour,overrides){
    const rows=[];
    for(const [d,i,start,duration,a,b,service,assigned] of this.hours[hour-4]??[]){
      if(assigned&&!this.enabled||overrides?.(d,i)?.size)continue;
      rows.push([d,i,start,duration,a,b,380,false,undefined,true,service]);
    }
    return rows;
  }
}

export async function loadHiredRides(root,versions,requested,json){
  const pointerUrl=root+"hired-rides/"+[versions.atlas,versions.day,versions.streets,versions.clock].filter(Boolean).join("_")+".json";
  let version=requested;
  if(!version||version==="fit"){
    const response=await fetch(pointerUrl);
    if(response.status===404&&!requested)return null;
    if(!response.ok)throw Error("Hired-ride evidence is unavailable for this weekday.");
    ({version}=await response.json());
  }
  if(!releaseId.test(version))throw Error("Unknown hired-ride release.");
  const report=await json(root+"hired-rides/"+version+"/rides.json");
  if(Object.entries(versions).some(([key,value])=>report.versions[key]!==value)||
     (report.versions.clock??null)!==(versions.clock??null))throw Error("Hired rides and weekday use different releases.");
  return {report,version,enabled:!!requested};
}

export function hiredRideControls({report,version,enabled},model,render,follow){
  const panel=el("hired-rides"),toggle=el("hired-replay"),button=el("hired-example");
  const setMode=(value,refresh=true)=>{
    toggle.checked=model.enabled=value;
    const url=new URL(location.href);
    if(value)url.searchParams.set("hiredRides",version);else url.searchParams.delete("hiredRides");
    history.replaceState(null,"",url);
    if(refresh)render();
  };
  panel.hidden=false;
  el("hired-map-key").hidden=false;
  setMode(enabled,false);
  toggle.onchange=()=>setMode(toggle.checked);
  const number=new Intl.NumberFormat("en-CA",{maximumFractionDigits:0});
  const {trips,original,target,assigned}=report.counts;
  const baseline=original.taxi+original.ridehail,total=baseline+assigned.taxi+assigned.ridehail;
  const share=n=>(100*n/trips).toFixed(2)+"%";
  el("hired-summary").textContent="Taxi or ride-hail accounts for "+share(baseline)+" of diary trips and "+share(total)+
    " after fitting the City’s "+(100*report.evidence.city.share).toFixed(1)+"% estimate.";
  el("hired-counts").textContent=number.format(assigned.taxi)+" taxi and "+number.format(assigned.ridehail)+
    " ride-hail assignments among Vancouver residents with a feasible passenger trip"+
    (total+0.5>=target?".":". The available trips fell short of the target.")+
    (report.missingCityAreas?.length?" This weekday covers a subset of the City’s census areas.":"");
  if(report.spread?.ridehail){
    const [before,after]=report.spread.ridehail.at17;
    const p=el("hired-spread");
    p.hidden=false;
    p.textContent="At exactly 17:00, ride-hail requests fall from "+number.format(before)+" to "+number.format(after)+
      ". The original hourly totals are preserved.";
  }
  el("hired-city-source").href=report.evidence.city.url;
  el("hired-split-source").href=report.evidence.split.url;
  if(report.example){
    button.hidden=false;
    const [d,i,start,duration]=report.example;
    button.onclick=()=>{setMode(true);follow(d,i,start+Math.floor(duration/2));};
  }
}
