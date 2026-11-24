const el=id=>document.getElementById(id);
const dayId=/^[a-f0-9]{20}$/;
const runId=/^[a-f0-9]{64}$/;
const count=n=>n.toLocaleString();

export async function homePlacement({root,versions,day,atlas,json,selectOnMap,showBlocks,autoZoom,replayUrl}){
  const panel=el("home-placement"), current=versions.version;
  const baseline=day.homePlacement?.baselineDay??current;
  const response=await fetch(`${root}home-placement/${versions.atlas}_${baseline}.json`);
  if(response.status===404)return;
  if(!response.ok)throw Error("The census-block home comparison is unavailable.");
  const pair=await response.json();
  if(pair.atlas!==versions.atlas||pair.baselineDay!==baseline||!dayId.test(pair.day)||
     !runId.test(pair.baselineRun)||!runId.test(pair.dayRun)||![pair.day,baseline].includes(current))
    throw Error("The two home placements use different weekday releases.");
  const fit=current===pair.day,base=`${root}cityday/${pair.day}/`;
  const report=await json(base+"home-placement.json");
  const {summary}=report;
  if(report.atlas!==versions.atlas||report.baselineDay!==baseline||summary.population!==day.population||summary.homeError!==0)
    throw Error("The block report and the resident roster differ.");
  panel.hidden=false;
  el("home-placement-current").textContent=fit?"Census-block homes":"Address points sampled within each census area";
  el("home-placement-summary").textContent=
    `The fitted day places ${count(summary.households)} households across ${count(summary.occupiedBlocks)} occupied blocks. `+
    `It matches the census resident count on ${count(summary.exactPopulationBlocks)} of ${count(summary.blocks)} blocks.`;
  const selector=el("home-placement-da"),link=el("home-placement-switch"),measure=el("home-placement-measure");
  for(const [name,area] of Object.entries(atlas.areas)){
    const group=document.createElement("optgroup");group.label=name;
    for(const da of area.das)group.append(new Option(da,da));
    selector.append(group);
  }
  const requested=new URLSearchParams(location.search).get("homeBlock");
  selector.value=Object.hasOwn(atlas.das,requested)?requested:report.example;
  link.textContent=fit?"Replay the original home locations":"Replay census-block homes";
  function refreshLink(){link.href=replayUrl(fit?pair.baselineRun:pair.dayRun,selector.value);}
  link.addEventListener("focus",refreshLink);
  link.addEventListener("pointerdown",refreshLink);
  let request=0;
  const cache=new Map();
  async function show({zoom=false}={}){
    refreshLink();
    const da=selector.value,id=++request,table=el("home-placement-rows"),status=el("home-placement-selection");
    const previous=showBlocks();
    table.replaceChildren();status.textContent="Loading census blocks…";
    try{
      if(!cache.has(da))cache.set(da,await json(base+"homes-"+da+".json"));
      const blocks=cache.get(da);
      if(id!==request||!panel.open)return;
      const homes=measure.value==="homes";
      const keys=homes?["dwellings","beforeHomes","homes"]:["population","beforePeople","people"];
      const settled=blocks.features.filter(({properties:b})=>keys.some(key=>b[key]));
      status.textContent=`${count(settled.length)} blocks in the table. Blue marks a shortfall, orange marks an excess, and green marks a match.`;
      for(const {properties:b} of settled){
        const row=table.insertRow(),label=document.createElement("th");
        row.dataset.block=b.block;label.scope="row";label.textContent=b.block;row.append(label);
        for(const key of keys)row.insertCell().textContent=count(b[key]);
      }
      for(const feature of blocks.features){
        const b=feature.properties;
        b.homeDifference=b[keys[fit?2:1]]-b[keys[0]];
      }
      if(zoom||previous)selectOnMap(blocks,zoom);
    }catch(error){if(id===request)status.textContent=error.message;}
  }
  // Start with the table. The map outline is optional when a resident is being followed.
  selector.onchange=()=>{
    const url=new URL(location.href);url.searchParams.set("homeBlock",selector.value);history.replaceState(null,"",url);
    show({zoom:showBlocks()});
  };
  measure.onchange=()=>show();
  el("home-placement-view").onclick=()=>show({zoom:true});
  panel.ontoggle=()=>{
    if(panel.open)show({zoom:autoZoom()});
    else{request++;selectOnMap(null,false);}
  };
  refreshLink();
}
