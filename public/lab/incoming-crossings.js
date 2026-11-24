const el=id=>document.getElementById(id);
const fmt=n=>n.toLocaleString("en-CA");
const clock=h=>String(h).padStart(2,"0")+":00";
const emptyHours=Array(24).fill(0);

const vehicleOptions={all:"All modeled vehicles",incoming:"Incoming work drivers",residentWork:"Residents’ work drives",
  outboundWork:"Residents’ work drives outside Vancouver",residentOther:"Other resident drives",buses:"Scheduled buses"};

export function attachIncomingRoadCrossings(report,fitted,followIncoming,followResident){
  const panel=el("incoming-road-crossings"),siteSelect=el("incoming-road-site"),direction=el("incoming-road-direction");
  const status=el("incoming-road-count"),body=el("incoming-road-hours");
  const vehicles=el("road-vehicles"),components=el("road-vehicle-components");
  const params=new URLSearchParams(location.search);
  let requestedVehicles=params.get("roadVehicles");
  let hours=[7,8];
  for(const site of report.sites)siteSelect.add(new Option(site.name,site.key));
  if(report.sites.some(site=>site.key===params.get("roadGate")))siteSelect.value=params.get("roadGate");
  const current=()=>report.sites.find(site=>site.key===siteSelect.value);
  const selectDirection=index=>{
    direction.replaceChildren(...current().directions.map((label,i)=>new Option(label,String(i))));
    direction.value=index?"1":"0";
  };
  const selectVehicles=()=>{
    const layers=current().layers;
    const keys=layers?Object.keys(vehicleOptions).filter(k=>k==="all"||k==="incoming"||layers[k]):["incoming"];
    vehicles.replaceChildren(...keys.map(k=>new Option(vehicleOptions[k],k)));
    vehicles.value=keys.includes(requestedVehicles)?requestedVehicles:keys[0];
    el("road-vehicles-label").hidden=keys.length===1;
  };
  selectDirection(params.get("roadDirection")==="1");
  selectVehicles();
  const update=()=>{
    const url=new URL(location.href);
    url.searchParams.set("roadGate",siteSelect.value);
    url.searchParams.set("roadDirection",direction.value);
    if(requestedVehicles)url.searchParams.set("roadVehicles",requestedVehicles);
    history.replaceState(null,"",url);
    render(hours);
  };
  siteSelect.onchange=()=>{selectDirection(0);selectVehicles();update();};direction.onchange=update;
  vehicles.onchange=()=>{requestedVehicles=vehicles.value;update();};
  panel.ontoggle=()=>{if(panel.open)render(hours);};
  panel.hidden=false;
  if(params.has("roadGate")||location.hash==="#incoming-road-crossings")panel.open=true;

  function render(visibleHours){
    hours=visibleHours;
    if(!panel.open)return;
    const site=current(),d=Number(direction.value),observed=site.counters?.[d];
    const key=vehicles.value,layers=site.layers,bothHomes=key==="all"||key==="incoming";
    const counts=k=>(k==="buses"?layers.buses?.[d]:layers[k]?.counts[d])??emptyHours;
    const sum=h=>counts("residentWork")[h]+counts("residentOther")[h]+counts("buses")[h]+(layers.outboundWork?.counts[d][h]??0);
    const selectedSeries=column=>key==="incoming"?site.counts[column][d]:key==="all"?
      site.counts[column][d].map((n,h)=>n+sum(h)):counts(key);
    const original=selectedSeries(0),calibrated=selectedSeries(1);
    const total=series=>hours.reduce((n,h)=>n+series[h],0);
    status.textContent=(bothHomes?fmt(total(original))+" modeled passages with the original incoming homes and "+
      fmt(total(calibrated))+" with the Census incoming homes.":fmt(total(calibrated))+" modeled passages.")+
      (observed?" The counter’s weekday average was "+fmt(total(observed.counts))+" vehicles in these hours.":"");
    components.hidden=key!=="all";
    if(key==="all"){
      const terms=[fmt(total(site.counts[1][d]))+" incoming work drives"];
      for(const [type,label] of [["residentWork","resident work drives within Vancouver"],
        ["outboundWork","resident work drives to or from external jobs"],["residentOther","other resident drives"],["buses","scheduled buses"]])
        if(layers[type])terms.push(fmt(total(counts(type)))+" "+label);
      components.textContent="The Census-home replay counts "+new Intl.ListFormat("en-CA").format(terms)+".";
    }
    el("road-original").hidden=!bothHomes;
    el("road-fitted").textContent=bothHomes?"Census incoming homes":"Modeled vehicles";
    el("incoming-road-observed").hidden=!observed;
    const source=el("incoming-road-source");
    source.href=site.source;
    source.textContent=observed?`${observed.month} ${observed.year} traffic counts`:"City of Vancouver legal boundary";
    el("incoming-road-basis").textContent=(layers?.residentWork?"Drivers follow free-flow routes. Resident drives require two mapped endpoints and time for the full route. Work drives touch a paid work stop. Buses use the "+report.schedule.date+" timetable. ":
      layers?.outboundWork?"Incoming and outbound work drivers follow free-flow routes. ":
      "Incoming work trips from all home municipalities, timed along free-flow driving routes. ")+
      (site.nearStation?"The route screen is on the city-side approach near the named counter. ":"")+
      (observed?"The counter includes all vehicles.":"Each route contributes one entry or exit near its workplace end.");
    body.replaceChildren();
    for(const h of hours){
      const row=body.insertRow();
      for(const value of [clock(h),...(bothHomes?[fmt(original[h])]:[]),fmt(calibrated[h]),...(observed?[fmt(observed.counts[h])]:[])])
        row.insertCell().textContent=value;
      const controls=row.insertCell();
      const resident=key==="all"?layers.residentWork?.examples[d][h]??layers.outboundWork?.examples[d][h]??layers.residentOther?.examples[d][h]:
        layers?.[key]?.examples?.[d][h];
      const incoming=bothHomes&&site.examples[fitted?1:0][d][h];
      const example=resident||incoming;
      if(example){
        const button=document.createElement("button");
        button.type="button";button.textContent="Follow";
        button.setAttribute("aria-label",`Follow a driver near ${clock(h)}`);
        button.onclick=()=>(resident?followResident(example):followIncoming(...example.slice(0,3)))
          .catch(error=>{status.textContent=error.message;});
        controls.append(button);
      }
    }
  }
  return render;
}
