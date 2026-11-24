import {cityLink,preferredRun,weekdayQuery} from "../js/replay/replay.js";

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
  return run ? [{label:"Vancouver regional weekday",description:"Explore Vancouver, UBC and the North Shore.",
    href:link("explorer.html",{city,release:run.release})}] : [];
}

let catalogue;
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
    if(library.isConnected)library.href="runs.html?"+libraryQuery;
    status.hidden=false;status.textContent="Loading published scenarios…";
    list.replaceChildren();
    const runs=await loadRuns();
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
    }else rows(runScenes(runs,city));
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
