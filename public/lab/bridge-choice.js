const el=id=>document.getElementById(id);
const number=n=>n.toLocaleString("en-CA");

export async function loadBridgeChoice(root,versions,routing,json,follow){
  const folder=root+"../bridge-choice/";
  const chosen=new URLSearchParams(location.search);
  let version=chosen.get("bridgeChoice");
  if(!version||version==="1"){
    const key=["atlas","day","streets"].map(part=>versions[part]).join("_");
    const response=await fetch(folder+key+".json");
    if(response.status===404)return null;
    if(!response.ok)throw Error("Bridge route choices are unavailable.");
    ({version}=await response.json());
  }
  if(!/^[a-f0-9]{20}$/.test(version))throw Error("Invalid bridge route choice release.");
  const report=await json(folder+version+"/report.json");
  if(["atlas","day","streets"].some(k=>report.versions[k]!==versions[k])||
     report.routing.profileDigest!==routing.profileDigest)
    throw Error("Bridge route choices belong to a different weekday or speed profile.");

  const panel=el("bridge-choice"),destination=el("bridge-choice-destination");
  report.groups.forEach((name,i)=>destination.add(new Option(name,String(i))));
  el("bridge-choice-source").href=report.survey;
  el("bridge-choice-method").textContent=number(report.fit)+" of "+number(report.eligible)+
    " recorded drives by North Shore residents fit at least one bridge on their way south. "+
    number(report.dual)+" fit either bridge. This comparison uses the same mapped one-way streets, road speeds and hourly Highway 1 adjustments as the main check. "+
    "Allow alternatives gives a slower feasible route less chance of being chosen as the travel-time difference grows. "+
    "The "+report.scale+"-minute scale is a sensitivity assumption. Each trip keeps its recorded departure, destination and arrival time. "+
    "Could use counts trips that could cross at that bridge in the selected period. One trip can appear in both rows.";

  if(report.example){
    const example=report.example;
    const label=el("bridge-choice-example");
    label.textContent="Follow the same resident toward "+example.group+
      " by either bridge. Each button jumps to the crossing.";
    for(const [index,path] of example.routes.entries()){
      const bridge=report.bridges[path.bridge],button=document.createElement("button");
      button.type="button";
      button.textContent=bridge+" · "+Math.round(path.minutes)+" min";
      button.onclick=()=>{
        for(const control of el("bridge-choice-routes").querySelectorAll("button"))
          control.setAttribute("aria-pressed",String(control===button));
        follow(example,path,bridge);
      };
      button.setAttribute("aria-pressed","false");
      button.title=index===0?"Fastest route":"Feasible alternative";
      el("bridge-choice-routes").append(button);
    }
  }

  let hours=[],windowName="";
  function update(){
    const all=destination.value==="";
    const groups=all?report.counts:[report.counts[Number(destination.value)]];
    const rows=el("bridge-choice-counts");
    rows.replaceChildren();
    for(const [b,name] of report.bridges.entries()){
      const sums=[0,0,0];
      for(const group of groups)for(const hour of hours)
        group[b][hour].forEach((n,k)=>{sums[k]+=n;});
      const row=rows.insertRow();
      for(const value of [name,...sums.map(number)])row.insertCell().textContent=value;
    }
    el("bridge-choice-hours").textContent=windowName+" · North Shore resident drivers";
    const shares=all?null:report.surveyShares[Number(destination.value)];
    el("bridge-choice-survey").textContent=shares?
      "For daily person trips to this destination, the 2025 survey reports "+
      shares[0]+"% Lions Gate, "+shares[1]+"% Ironworkers and "+shares[2]+"% SeaBus.":"";
  }
  if([...destination.options].some(option=>option.value===chosen.get("bridgeDestination")))
    destination.value=chosen.get("bridgeDestination");
  destination.onchange=()=>{
    update();
    const url=new URL(location.href);
    if(destination.value)url.searchParams.set("bridgeDestination",destination.value);
    else url.searchParams.delete("bridgeDestination");
    history.replaceState(null,"",url);
  };
  el("bridge-choice-results").hidden=false;
  panel.hidden=false;
  panel.addEventListener("toggle",()=>{
    const url=new URL(location.href);
    if(panel.open)url.searchParams.set("bridgeChoice",version);
    else url.searchParams.delete("bridgeChoice");
    history.replaceState(null,"",url);
  });
  if(chosen.has("bridgeChoice"))panel.open=true;
  return (nextHours,name)=>{
    hours=nextHours;
    windowName=name;
    update();
  };
}
