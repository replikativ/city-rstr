import {BIKE,WALK,positionOnSegment} from "./vancouver-network.js";

const el=id=>document.getElementById(id);
const fmt=n=>n.toLocaleString("en-CA");

export class GranvilleVisitors {
  constructor(report,version,active,change,follow,clock){
    Object.assign(this,{report,version,active,change,follow});
    const {samples,passages,visits,presence,sources}=report;
    const panel=el("granville-visitors"),toggle=el("granville-toggle"),select=el("granville-guest");
    panel.hidden=false;
    if(active||location.hash==="#granville-visitors")panel.open=true;
    toggle.checked=active;
    toggle.onchange=()=>this.enable(toggle.checked);
    el("granville-sample").textContent=fmt(visits.length)+" modeled bike visits · peak presence "+fmt(Math.max(...presence))+" at the market.";
    el("granville-method").textContent="The City estimated "+fmt(samples.annualTouristVisits)+
      " annual tourist visits. "+samples.cyclists+" of "+samples.responses+
      " tourist interviews reported cycling. The replay uses an average calendar day, assumes a 45–90 minute visit during market hours, and weights hotel origins by licensed employment as a size proxy.";
    for (const [name,url] of Object.entries(sources))el("granville-source-"+name).href=url;
    for(const [key,site] of Object.entries(passages)){
      const row=el("granville-counts").insertRow();
      const link=document.createElement("a");
      link.href=site.source;
      link.textContent=site.name;
      row.insertCell().append(link);
      row.insertCell().textContent=fmt(key==="anderson"?site.inbound:site.inbound+site.outbound);
      row.insertCell().textContent=fmt(Math.round(site.observed));
    }
    for(const [i,[route,,arrival]] of visits.entries())
      select.add(new Option(clock(arrival)+" · "+report.routes[route].origin,i));
    select.selectedIndex=visits.findIndex(row=>row[2]>=720);
    if(select.selectedIndex<0)select.selectedIndex=0;
    for(const button of el("granville-stages").querySelectorAll("button")){
      button.onclick=()=>{
        const index=select.selectedIndex,[route,start,arrival,dwell]=visits[index];
        const back=arrival+dwell+report.walk[1][0]+report.routes[route].cycling[1][0];
        follow(index,[start,arrival,back][Number(button.value)]);
      };
    }
  }

  pin(url){
    url.searchParams.delete("granville");
    if(this.active)url.searchParams.set("granvilleRun",this.version);
    else url.searchParams.delete("granvilleRun");
  }

  enable(active){
    this.active=active;
    el("granville-toggle").checked=active;
    const url=new URL(location.href);
    this.pin(url);
    if(!active)url.searchParams.delete("granvilleGuest");
    history.replaceState(null,"",url);
    this.change();
  }

  state(index,minute){
    const [id,start,arrival,dwell]=this.report.visits[index];
    const end=arrival+dwell;
    const {origin,cycling:[outbound,returning]}=this.report.routes[id];
    const [walkIn,walkOut]=this.report.walk;
    const hotel=outbound[1][0];
    for(const [from,[length,path],mode,activity] of [
      [start,outbound,BIKE,"Cycling to Granville Island"],
      [arrival-walkIn[0],walkIn,WALK,"Walking to the Public Market"],
      [end,walkOut,WALK,"Walking back to bike parking"],
      [end+walkOut[0],returning,BIKE,"Cycling back to the hotel"]]){
      if(minute>=from&&minute<from+length){
        const {point:p,segment}=positionOnSegment(path,(minute-from)/length);
        return {index,p,path,segment,mode,activity,origin,visible:true};
      }
    }
    if(minute>=arrival&&minute<end)
      return {index,p:this.report.market,mode:WALK,activity:"Visiting the Public Market",origin,visible:true};
    return {index,p:hotel,mode:WALK,activity:"At the hotel",origin,visible:false};
  }

  render(minute){
    el("granville-now").textContent=this.active?
      fmt(this.report.presence[Math.floor(minute)-240]??0)+" of "+fmt(this.report.visits.length)+" modeled visitors at the market now.":"";
    if(!this.active)return [];
    return this.report.visits.map((_,i)=>this.state(i,minute)).filter(frame=>frame.visible);
  }
}

export async function loadGranville(root,parents,json,change,follow,clock){
  const params=new URLSearchParams(location.search);
  const base=root+"granville-visitors/";
  let version=params.get("granvilleRun");
  const active=!!version||params.get("granville")==="on";
  if(!version){
    const res=await fetch(base+parents.streets+"_"+parents.cycling+".json");
    if(res.status===404&&!active)return null;
    if(!res.ok)throw Error("Granville Island visitor replay is unavailable.");
    ({version}=await res.json());
  }
  if(!/^[a-f0-9]{20}$/.test(version))throw Error("Invalid Granville Island visitor release.");
  const report=await json(base+version+"/visits.json");
  if(Object.entries(parents).some(([key,value])=>report.versions[key]!==value))
    throw Error("The Granville Island visitors use a different street network.");
  return new GranvilleVisitors(report,version,active,change,follow,clock);
}
