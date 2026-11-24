import {cityLink,preferredRun,weekdayQuery} from "../js/replay/replay.js";

const council="997ee475666d9cba5fd8";
const municipalDay="4f711d78c7e0f40698dd7dd0c10df51d85429318e20d12572de0bebaa5cc88a5";
const homeZoneDay="1fa75ab09e40f61cb1eb2a40a0e4b6006c3a48e5c0a00e918e0dcaec0f347796";
const region="06c504c638de40f775a7";
const bridgeChoice="6f09a6463ee864dcee5b";
const personalTransit="b563cceea412bde5eafd";
const market="4614fc4e7623f4a46b7aa5b2d575bbfbdb2b07c8a81c4d5dd78711ec2ced66a5";
const housingRun="dd2b618d51e61a158a99";
const corridorTimes="780aaf6b1c7d420aea5c";
const bridgeDecks="b90d91ccc87929d229c6";
const departureClock="33f20d3ea8c275eeb4f8";
const regional={coverage:"region",workplaceRun:region,workTransit:"9cec79f1fec091af7db6",
  outingsRun:"e7879ecee4c15a19e092",schoolRun:"1813a113cd76855c266f",recreationRun:"88c1b239375877b1c6b3",
  attendanceRun:"97d973e3124160288795",walks:"fit"};

const vancouver=[
  {label:"Drive through Downtown",description:"Start on Robson Street during the morning commute.",
    available:"data/vancouver/region/regional-workplaces/"+region+"/report.json",
    params:{...regional,street:"drive",camera:"eye",at:"-123.117576,49.279893,135",minute:480}},
  {label:"Cross Lions Gate Bridge",description:"Drive at street level over Burrard Inlet during the morning commute.",
    available:"data/vancouver/bridge-decks/"+bridgeDecks+"/decks.json",
    params:{...regional,decks:bridgeDecks,street:"drive",camera:"eye",at:"-123.139263,49.314678,31",minute:480}},
  {label:"Take transit to school or shops",description:"Follow a resident on foot, on board and through a connection.",
    available:"data/vancouver/region/personal-transit/"+personalTransit+"/report.json",
    params:{...regional,personalTransit,minute:540}},
  {label:"Open a grocery shop",description:"Choose when to open at Kingsway and follow the people who shop there.",
    available:"data/vancouver/market/archive/"+market+"/run.json",
    params:{marketRun:market,shop:"4654",hours:"full",shopPlay:1,minute:600}},
  {label:"Test higher housing costs near a shop",description:"Compare grocery budgets at the same Kingsway storefront.",
    available:"data/vancouver/household-market/housing/"+housingRun+"/report.json",
    params:{marketRun:market,shop:"4654",housingRun,shelterShock:10,minute:600}},
  {label:"Compare where residents live",description:"Compare two home placements against the census block counts.",
    available:"data/vancouver/home-placement/59b3bcac4137ca1483c9_dbd7a101357f3c27976f.json",
    anchor:"home-placement",params:{dayRun:municipalDay,homeBlock:"59154174",minute:300}},
  {label:"Compare travel by home zone",description:"Compare the same households’ weekday travel with the City’s survey.",
    available:"data/runs/"+homeZoneDay+".json",
    anchor:"diary-zone-check",params:{dayRun:homeZoneDay,minute:480}},
  {label:"Compare advance voting sites",description:"Put the same staff at City Hall or spread them across five locations.",
    available:"data/vancouver/voting/"+council+"/report.json",
    params:{dayRun:municipalDay,votingRun:council,votingLayout:"centres",votingSite:200,minute:1020}},
  {label:"Compare routes across Burrard Inlet",description:"Follow the same morning driver over Lions Gate or Ironworkers.",
    available:"data/vancouver/region/bridge-choice/"+bridgeChoice+"/report.json",
    params:{...regional,bridge:"Ironworkers",bridgeDirection:0,bridgeWindow:"am",bridgeMetric:"highway1",
      bridgeChoice,minute:480}},
  {label:"Use observed driving times",description:"Replay West Georgia, Granville and Highway 1 with measured weekday speeds.",
    available:"data/vancouver/region/drive-profile/corridor-times/"+corridorTimes+"/report.json",
    anchor:"road-traffic",params:{coverage:"region",workplaceRun:region,roadTraffic:corridorTimes,roadSection:"georgia",minute:480}},
  {label:"Replay the afternoon with spread departures",description:"Compare the same taxi and ride-hail fleets with departures spread within each hour.",
    available:"data/vancouver/region/hired-dispatch/2dca42367295ade1bdc7/dispatch.json",
    anchor:"hired-dispatch",params:{coverage:"region",workplaceRun:region,departureClock,hiredRides:"5f3a1a617d965e48d7c6",
      dispatchRun:"2dca42367295ade1bdc7",minute:1020}},
  {label:"Change the Lions Gate centre lane",description:"Compare morning crossings and queues under two lane allocations.",
    available:"data/vancouver/region/bridge-demand/879ba485218802dd3acc/arrivals.json",
    params:{...regional,bridge:"LionsGateBridge",bridgeDirection:0,bridgeWindow:"am",bridgeMetric:"highway1",
      bridgeQueue:1,lanePolicy:"north",easternOutingRun:"1890ea2cbe8d554d4003",minute:480}}
];

const link=(file,params)=>file+(Object.keys(params).length?"?"+new URLSearchParams(params):"");
const staticData=document.querySelector('meta[name="city-data"]')?.content;

function runScenes(runs,city){
  const whole=preferredRun(runs,city,"city");
  if(city==="stuttgart"){
    const page=staticData?location.pathname:"lab.html";
    const base=weekdayQuery(city,"city",whole?.release);
    return [
      {label:"Stuttgart weekday",description:"Follow journeys on an ordinary weekday.",href:link(page,{...base,view:"movement"})},
      ...(whole?.scenarios??[]).map(scenario=>({label:scenario.label,description:"See how spending shifts across districts.",
        href:link(page,{...base,scenario:scenario.key,view:"scenario"})}))
    ];
  }
  const region=preferredRun(runs,city,"region");
  const run=region??whole;
  return [{label:"Vancouver weekday",description:"Explore Vancouver, UBC and the North Shore.",
    href:link("cityday.html",weekdayQuery(city,run?.coverage??"region",run?.release))}];
}

async function localAsset(url){
  try{
    const response=await fetch(url,{method:"HEAD"});
    return response.ok&&response.headers.get("content-type")?.includes("json");
  }catch{return false;}
}

let catalogue,available;
function loadRuns(){
  const url=staticData?new URL("scenarios.json",new URL(staticData,document.baseURI)):"data/runs/current.json";
  catalogue??=fetch(url).then(response=>response.ok?response.json():null).then(data=>{
    if(staticData)return [{city:"stuttgart",coverage:"city",scenarios:data?.scenarios}];
    return Array.isArray(data)?data:[];
  }).catch(()=>[]);
  return catalogue;
}

const cityPicker=document.querySelector("[data-city-selector]");
if(cityPicker&&!staticData){
  const current=cityPicker.value;
  const status=document.getElementById("city-switch-status");
  cityPicker.closest("label").hidden=false;
  cityPicker.onchange=async()=>{
    const city=cityPicker.value;
    cityPicker.disabled=true;
    status.hidden=true;
    const clock=document.querySelector("[data-clock=seek]");
    const params=new URLSearchParams(location.search);
    const month=document.getElementById("clock-kind")?.value==="month"||
      (clock?.disabled&&params.get("clock-kind")==="month");
    const requested=current==="stuttgart"?Number(params.get("hour")??NaN)*60:Number(params.get("minute")??NaN);
    const minute=month?null:clock?.disabled&&Number.isFinite(requested)?requested:clock?.valueAsNumber;
    const href=cityLink(await loadRuns(),city,Number.isFinite(minute)?minute:null);
    if(href){location.assign(href);return;}
    cityPicker.value=current;
    cityPicker.disabled=false;
    status.hidden=false;
    status.textContent="Published weekday unavailable.";
  };
}

function loadVancouver(){
  available??=Promise.all(vancouver.map(async scene=>await localAsset(scene.available)?
    {...scene,href:link("cityday.html",scene.params)+(scene.anchor?"#"+scene.anchor:"")}:null)).then(scenes=>scenes.filter(Boolean));
  return available;
}

function menu(){
  const dialog=document.createElement("dialog");
  dialog.className="replay-menu";dialog.setAttribute("aria-labelledby","replay-menu-title");
  dialog.innerHTML=`<header><h2 id="replay-menu-title">Choose a scenario</h2><form method="dialog"><button>Close</button></form></header>
    <label for="replay-city">City</label><select id="replay-city"><option value="vancouver">Vancouver</option><option value="stuttgart">Stuttgart</option></select>
    <ul class="replay-list"></ul><p role="status" class="replay-loading" hidden></p>`;
  const library=document.createElement("a");
  if(document.getElementById("weekday-explorer")){
    library.id="library-link";
    library.textContent="Browse run library";
    dialog.append(library);
    library.addEventListener("click",event=>{
      if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
      const url=new URL(location.href);
      url.search=library.search;
      history.replaceState(history.state,"",url);
      dialog.close();
    });
  }
  document.body.append(dialog);
  const picker=dialog.querySelector("select"),list=dialog.querySelector("ul"),status=dialog.querySelector("p");
  if(staticData||document.getElementById("weekday-explorer")){dialog.querySelector('label[for="replay-city"]').hidden=true;picker.hidden=true;}
  let revision=0;
  function rows(scenes){
    list.replaceChildren(...scenes.map(({label,description,href})=>{
      const row=document.createElement("li"),anchor=document.createElement("a");
      const name=document.createElement("strong"),detail=document.createElement("span");
      name.textContent=label;detail.textContent=description;anchor.href=href;anchor.append(name,detail);row.append(anchor);
      return row;
    }));
  }
  async function show(){
    const city=picker.value,id=++revision;
    const libraryQuery=new URLSearchParams(location.search);
    libraryQuery.set("city",city);
    const camera=document.getElementById("overview-map")?.dataset.camera;
    if(camera)libraryQuery.set("camera",camera);
    library.href="runs.html?"+libraryQuery;
    status.hidden=false;status.textContent="Loading published scenarios…";
    list.replaceChildren();
    const [runs,extras]=await Promise.all([loadRuns(),city==="vancouver"&&!document.getElementById("overview-map")?loadVancouver():Promise.resolve([])]);
    if(id!==revision)return;
    const overlay=document.getElementById("metric");
    if(overlay && city===document.getElementById("run")?.value){
      const choices=[...overlay.querySelectorAll("[data-scenario]")].map(option=>{
        const url=new URL(location.href);
        url.searchParams.set("metric",option.value);
        return {label:option.text,description:"View on the weekday map.",href:url.href,metric:option.value};
      });
      rows(choices);
      for(const [index,choice] of choices.entries()){
        list.children[index].querySelector("a").onclick=event=>{
          if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
          event.preventDefault();
          overlay.value=choice.metric;
          overlay.dispatchEvent(new Event("change"));
          dialog.close();
        };
      }
    }else if(overlay){
      const run=preferredRun(runs,city,"region")??preferredRun(runs,city,"city");
      rows(run?[{label:run.label,description:"Open this city in the shared explorer.",
        href:link("explorer.html",{city,release:run.release})}]:[]);
    }else rows([...runScenes(runs,city),...extras]);
    status.hidden=true;
  }
  picker.onchange=show;
  return {open(city){picker.value=city;dialog.showModal();dialog.scrollTop=0;if(!picker.hidden)picker.focus();show();}};
}

let picker;
for(const button of document.querySelectorAll("[data-replay-menu]")){
  button.addEventListener("click",()=>{
    const city=document.getElementById("run")?.value||button.dataset.replayMenu||document.getElementById("library-city")?.value||"vancouver";
    (picker??=menu()).open(city);
  });
}
