const el=id=>document.getElementById(id);
const number=new Intl.NumberFormat(undefined,{maximumFractionDigits:1});
const clock=hour=>String(hour).padStart(2,"0")+":00";
const peak=hours=>hours.map(clock).join(", ")||"—";
const month=({month,year})=>month+" "+year;
const transitAnchor="#downtown-transit-audit";

function transitDemand(report,url){
  const {resident,incoming}=report;
  const origin=el("downtown-transit-origin"),window=el("downtown-transit-window"),rows=el("downtown-transit-counts");
  const groups=[resident,incoming].map((group,i)=>{
    const options=document.createElement("optgroup");options.label=i===0?"Vancouver neighbourhoods":"Incoming home municipalities";
    for(const name of Object.keys(group.byHome))options.append(new Option(name,i+"/"+name));
    return options;
  });
  origin.append(...groups);
  el("downtown-transit-data").href=url;
  const render=()=>{
    const direction=window.value,hours=direction==="arriving"?[7,8]:[16,17];
    const counts=[resident,incoming].map((group,i)=>{
      const series=origin.value?(origin.value.startsWith(i+"/")?group.byHome[origin.value.slice(2)]:null):group.hourly;
      return series?key=>hours.reduce((n,h)=>n+(series[direction][h][key]??0),0):null;
    });
    const items=[
      ["Modeled transit trips","demand"],["Missing usable stop access","access"],
      ["Accessible, unbooked","unbooked",null],["No itinerary found",null,"schedule"],
      ["Itinerary found, unbooked",null,"capacity"],["Booked","booked"],["Of which use SkyTrain","withSkyTrain"],
      ["Timetable misses feasible in the original window",null,"reachableInOriginalWindow"],
      ["Additional timetable misses feasible with 30 extra minutes",null,"reachableWith30ExtraMinutes"]
    ];
    rows.replaceChildren();
    for(const [label,key,incomingKey=key] of items){
      const values=[key,incomingKey].map((field,i)=>field&&counts[i]?counts[i](field):null);
      if(values.every(value=>value===null))continue;
      const row=rows.insertRow();
      const title=document.createElement("th");title.scope="row";title.textContent=label;row.append(title);
      for(const value of values)row.insertCell().textContent=value===null?"—":number.format(value);
    }
  };
  origin.onchange=window.onchange=render;
  render();
}

async function showBooking(url,release,incomingTransit){
  try{
    const response=await fetch(url);
    if(response.status===404)return;
    if(!response.ok)throw Error("Commute-window experiment unavailable.");
    const report=await response.json();
    if(report.schema!==1||report.release!==release||report.incomingTransit!==incomingTransit)
      throw Error("Commute-window experiment belongs to a different weekday.");
    const rows=el("downtown-booking-rows"),context=el("downtown-booking-context");
    function render(data,path){
      const paired=!!data.northShore;
      rows.replaceChildren();
      for(const scenario of data.scenarios){
        const row=rows.insertRow(),title=document.createElement("th");title.scope="row";
        const timing=scenario.extraMinutes?"+"+scenario.extraMinutes+" min":"Original windows";
        title.textContent=paired?(scenario.workplaces?"Fitted jobs":"Original jobs")+" · "+timing:
          scenario.extraMinutes===null?"Published":scenario.extraMinutes===0?"Original + new search":timing;
        row.append(title);
        for(const value of [scenario.added,...scenario.stationPeakCounts,scenario.duration.maePoints[1]])
          row.insertCell().textContent=number.format(value);
      }
      const scope=paired?"Added trips cover North Shore transit commuters and their matched partners. ":
        "Added trips are bookings to and from Downtown jobs across the day. ";
      context.textContent=scope+"Station exits and entries are the combined weekday totals. "+
        "Duration error is measured in percentage points across five Census bands for the same modeled cohort in each case.";
      el("downtown-booking-data").href=path;
    }
    render(report,url);
    el("downtown-booking").hidden=false;
    const pairedUrl=url.replace(/-booking\.json$/,"-workplace-timing.json");
    const pairedResponse=await fetch(pairedUrl);
    if(pairedResponse.status===404)return;
    if(!pairedResponse.ok)throw Error("Workplace and timing experiment unavailable.");
    const paired=await pairedResponse.json();
    if(paired.schema!==1||paired.release!==release||paired.parents.incomingTransit!==incomingTransit)
      throw Error("Workplace and timing experiment belongs to a different weekday.");
    const choice=el("downtown-booking-kind");
    el("downtown-booking-choice").hidden=false;
    choice.onchange=()=>choice.value==="workplaces"?render(paired,pairedUrl):render(report,url);
  }catch(error){console.warn(error.message);}
}

export function attachDowntownAudit(root,release,openAnchor){
  const parent=el("downtown"),panel=el("downtown-audit"),select=el("downtown-audit-site");
  const url=root+"downtown-audit/"+release+".json";
  const transit=el("downtown-transit-audit"),transitUrl=root+"downtown-audit/"+release+"-transit.json";
  let transitPending;
  async function showTransit(site,parents){
    transit.hidden=true;
    if(!site.stations)return;
    transitPending??=fetch(transitUrl).then(async response=>{
      if(response.status===404)return false;
      if(!response.ok)throw Error("Transit booking evidence unavailable.");
      const data=await response.json();
      if(data.schema!==1||data.release!==release||data.joint!==parents.jointRun||
        data.residentRiders!==parents.residentRiders||data.incomingTransit!==parents.incomingTransit)
        throw Error("Transit booking evidence belongs to a different weekday.");
      transitDemand(data,transitUrl);
      void showBooking(root+"downtown-audit/"+release+"-booking.json",release,parents.incomingTransit);
      return true;
    }).catch(error=>{console.warn(error.message);return false;});
    if(await transitPending&&select.value===site.key){
      transit.hidden=false;
      if(location.hash===transitAnchor)openAnchor();
    }
  }
  async function load(){
    if(!parent.open)return;
    parent.removeEventListener("toggle",load);
    try{
      const response=await fetch(url);
      if(response.status===404)return;
      if(!response.ok)throw Error("Count benchmark unavailable.");
      const report=await response.json();
      if(report.schema!==1||report.release!==release)throw Error("Count benchmark belongs to a different weekday.");
      const rows=el("downtown-audit-counts"),source=el("downtown-audit-source");
      el("downtown-audit-data").href=url;
      el("downtown-audit-peak").textContent="Peak starts are the busiest hours within "+
        report.windows.map(window=>window.peakHours.map(clock).join("–")).join(" and ")+".";
      select.replaceChildren(...report.sites.map(site=>new Option(site.label,site.key)));
      if(location.hash===transitAnchor)select.value="downtownSkyTrain";
      const render=()=>{
        const site=report.sites[select.selectedIndex];
        source.href=site.source;
        const [first,second]=site.directions.map(direction=>direction.reference);
        const reference=site.matchedReferencePeriod?month(first):
          `${month(first)} southbound and ${month(second)} northbound`;
        el("downtown-audit-context").textContent=site.stations
          ? "2025 weekday average passenger events. Modeled counts include assigned resident riders and scheduled incoming and external-work riders."
          : `Average weekday vehicle counts from ${reference}. Modeled counts include routed resident drivers, incoming work drivers and scheduled buses. Streets use free-flow timing.`;
        rows.replaceChildren();
        for(const [i,window] of report.windows.entries()){
          for(const {label,windows} of site.directions){
            const values=windows[i],row=rows.insertRow();
            const heading=document.createElement("th");heading.scope="row";
            heading.textContent=window.label+" · "+label;row.append(heading);
            row.insertCell().textContent=number.format(values.observed);
            row.insertCell().textContent=number.format(values.modeled);
            row.insertCell().textContent=peak(values.observedPeakStarts)+" → "+peak(values.modeledPeakStarts);
          }
        }
        void showTransit(site,report.parents);
      };
      select.onchange=render;
      render();el("downtown-audit-report").hidden=false;panel.hidden=false;
      if(location.hash==="#downtown-audit"||location.hash===transitAnchor)openAnchor();
    }catch(error){
      const status=el("downtown-audit-error");
      status.textContent=error.message;status.hidden=false;
      panel.hidden=false;
      if(location.hash==="#downtown-audit"||location.hash===transitAnchor)openAnchor();
    }
  }
  parent.addEventListener("toggle",load);
  if(location.hash==="#downtown-audit"||location.hash===transitAnchor)parent.open=true;
  if(parent.open)void load();
}
