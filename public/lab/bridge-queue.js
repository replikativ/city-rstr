const el=id=>document.getElementById(id);
const number=n=>n.toLocaleString("en-CA");
const clock=minute=>String(Math.floor(minute/60)%24).padStart(2,"0")+":"+String(minute%60).padStart(2,"0");
const policies={
  LionsGateBridge:[["weekday","Weekday counterflow"],["north","Centre lane stays toward the North Shore"],
    ["south","Centre lane stays toward Vancouver"]],
  Ironworkers:[["normal","Three lanes each way"],["closure","One lane closed toward Vancouver, 07:00–09:00"]]
};

function windowTotals(rows,hours,start){
  const totals={arrivals:0,crossings:0,waiting:0,peak:0,peakMinute:null};
  const bins=hours.map(h=>(h*60-start+1440)%1440).sort((a,b)=>a-b);
  for(const i of bins){
    for(let j=i;j<i+60;j++){
      const [enter,served,waiting]=rows[j];
      totals.arrivals+=enter;totals.crossings+=served;
      if(waiting>totals.peak){totals.peak=waiting;totals.peakMinute=start+j;}
    }
    totals.waiting=rows[i+59][2];
  }
  return totals;
}

function drawPlot(canvas,rows,reference,minute,start){
  const ctx=canvas.getContext("2d");
  const {width,height}=canvas,x0=42,y0=8,w=width-x0-13,h=height-y0-23;
  const scale=Math.max(1,...rows.map(row=>row[2]),...reference.map(row=>row[2]));
  ctx.clearRect(0,0,width,height);
  ctx.font="12px system-ui";ctx.fillStyle="#c4d3cc";
  ctx.fillText(number(scale),2,y0+10);ctx.fillText("0",2,y0+h);
  ctx.strokeStyle="#6a8076";ctx.beginPath();ctx.moveTo(x0,y0);ctx.lineTo(x0,y0+h);ctx.lineTo(x0+w,y0+h);ctx.stroke();
  for(let i=0;i<1440;i+=240){
    const x=x0+i*w/1440;
    ctx.fillText(clock(start+i),x-12,height-5);
  }
  const line=(series,color)=>{
    ctx.beginPath();ctx.strokeStyle=color;ctx.lineWidth=2;
    for(const [i,row] of series.entries()){
      const x=x0+i*w/1440,y=y0+h*(1-row[2]/scale);
      if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
    }
    ctx.stroke();
  };
  if(reference!==rows)line(reference,"#94b2ae");
  line(rows,"#ffce76");
  const x=x0+minute*w/1440;
  ctx.strokeStyle="#ecf1ef";ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,y0);ctx.lineTo(x,y0+h);ctx.stroke();
}

export async function loadBridgeQueue({root,versions,json,profileDigest,time,focus,draw,bridgeOpen}){
  const locationParams=new URLSearchParams(location.search);
  const folder=new URL("../bridge-demand/",new URL(root,location.href));
  const key=[versions.atlas,versions.day,versions.streets].join("_");
  const response=await fetch(new URL(key+".json",folder));
  if(response.status===404)return null;
  if(!response.ok)throw Error("Minute bridge demand is unavailable.");
  const {version}=await response.json();
  const [demand,model]=await Promise.all([json(new URL(version+"/arrivals.json",folder)),import("../js/vancouver/bridge-queue.js")]);
  if(demand.schema!==1||demand.start!==240||demand.roads.profileDigest!==profileDigest||
     Object.entries(versions).some(([k,v])=>demand.versions[k]!==v))
    throw Error("The bridge queue uses a different weekday or road profile.");
  const panel=el("bridge-queue"), select=el("bridge-lane-policy"), status=el("bridge-queue-status");
  let current, rows, reference, lastMinute, policySite;

  const atMinute=minute=>{
    if(!panel.open||!bridgeOpen()||!rows){
      if(lastMinute!==null)draw(null);
      lastMinute=null;
      return;
    }
    const cursor=Math.floor(minute)-demand.start;
    if(cursor===lastMinute)return;
    lastMinute=cursor;
    const [arrivals,crossings,waiting,capacity]=rows[cursor];
    el("bridge-queue-clock").textContent=clock(cursor+demand.start)+" · "+number(arrivals)+" arriving · "+number(crossings)+
      " crossing · "+number(waiting)+" waiting · "+number(capacity)+" crossing slots this minute";
    draw(current.bridge.point,waiting);
    drawPlot(el("bridge-queue-plot"),rows,reference,cursor,demand.start);
  };

  function recompute(){
    if(!current||!panel.open||!bridgeOpen())return;
    const {bridge,heading,hours,playback,active}=current, id=bridge.key, choices=policies[id];
    if(!choices||!demand.capacities[id])return;
    if(policySite!==id){
      const preferred=policySite===undefined?locationParams.get("lanePolicy"):null;
      select.replaceChildren(...choices.map(([value,text])=>new Option(text,value)));
      if(choices.some(([value])=>value===preferred))select.value=preferred;
      policySite=id;
    }
    const url=new URL(location.href);
    url.searchParams.set("bridgeQueue","1");url.searchParams.set("lanePolicy",select.value);
    history.replaceState(null,"",url);
    const index=playback.bridges.indexOf(id);
    const parts=[demand.residents[id]?.[heading],demand.incoming[id]?.[heading],playback.buses.sites[index]?.minutes?.[heading]];
    for(const [name,release] of Object.entries(active)){
      if(!release)continue;
      const layer=playback.layers[name];
      parts.push(layer?.release===release?layer.sites[index]?.minutes?.[heading]:null);
    }
    if(parts.some(part=>part?.length!==1440)){
      status.textContent="Minute counts are unavailable for part of the active replay.";
      el("bridge-queue-results").hidden=true;rows=null;atMinute(time());return;
    }
    const arrivals=Array.from({length:1440},(_,i)=>parts.reduce((sum,part)=>sum+part[i],0));
    const capacity=demand.capacities[id];
    const solve=policy=>model.replay(id,policy,heading,demand.start,capacity.byLanes,arrivals);
    rows=solve(select.value);reference=select.value===choices[0][0]?rows:solve(choices[0][0]);
    const body=el("bridge-queue-rows");body.replaceChildren();
    for(const [label,series] of [[choices[0][1],reference],...(reference===rows?[]:[[select.selectedOptions[0].text,rows]])]){
      const {arrivals,crossings,peak,waiting}=windowTotals(series,hours,demand.start), row=body.insertRow();
      for(const value of [label,number(arrivals),number(crossings),number(peak),number(waiting)])row.insertCell().textContent=value;
    }
    const {peakMinute}=windowTotals(rows,hours,demand.start),jump=el("bridge-queue-peak");
    jump.hidden=peakMinute===null;jump.onclick=()=>focus(bridge.point,peakMinute);
    el("bridge-queue-legend").hidden=reference===rows;
    el("bridge-queue-capacity").href=capacity.source;
    const operation=el("bridge-counterflow-source");operation.hidden=!capacity.operations;
    if(capacity.operations)operation.href=capacity.operations;
    el("bridge-queue-method").textContent=id==="LionsGateBridge"?
      "The weekday case sends the centre lane toward Vancouver from 06:00 to 09:30 and toward the North Shore at other times. Real operators change the lane in response to traffic. The model allows 1,500 vehicles an hour with one lane and 3,500 with two.":
      "The model allows 1,700 vehicles per lane per hour. The closure removes one lane toward Vancouver from 07:00 to 09:00.";
    status.textContent="";el("bridge-queue-results").hidden=false;lastMinute=null;atMinute(time());
  }

  select.onchange=recompute;
  panel.ontoggle=()=>{
    if(panel.open)recompute();
    else{
      const url=new URL(location.href);url.searchParams.delete("bridgeQueue");url.searchParams.delete("lanePolicy");
      history.replaceState(null,"",url);atMinute(time());
    }
  };
  panel.hidden=false;
  if(locationParams.has("bridgeQueue"))panel.open=true;
  return {update:state=>{current=state;recompute();},atMinute};
}
