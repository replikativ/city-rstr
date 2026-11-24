import {ScheduledPassengers} from "./transit-passenger.js";

const el=id=>document.getElementById(id);
const fmt=n=>n.toLocaleString();
const sum=row=>row.reduce((a,b)=>a+b,0);

function drawHourly(counts,reference,jumpTime){
  const svg=el("campus-chart"),ns="http://www.w3.org/2000/svg";
  function add(tag,attrs,text){
    const node=document.createElementNS(ns,tag);
    for(const [k,v] of Object.entries(attrs))node.setAttribute(k,v);
    if(text)node.textContent=text;
    svg.append(node);return node;
  }
  const ceiling=Math.ceil(Math.max(...counts.flat(),reference.amIn,reference.amOut,reference.pmIn,reference.pmOut)/1000)*1000;
  const y=n=>82-68*n/ceiling;
  for(const n of [0,ceiling/2,ceiling]){
    add("line",{x1:16,x2:304,y1:y(n),y2:y(n),stroke:"#58645c","stroke-width":.7});
    add("text",{x:16,y:y(n)-2},n===0?"0":(n/1000)+"k");
  }
  add("rect",{id:"campus-hour",y:14,width:12,height:69,fill:"#ebf0e2",opacity:.13});
  for(let index=0;index<24;index++){
    const hour=(index+4)%24,x=16+12*index;
    const ref=hour===9?[reference.amIn,reference.amOut]:hour===17?[reference.pmIn,reference.pmOut]:[];
    for(const [direction,n] of counts[hour].entries()){
      const start=x+1+5*direction;
      add("rect",{x:start,y:y(n),width:4,height:82-y(n),fill:direction?"#ecb17e":"#8ac6dd"});
      if(ref.length)add("circle",{cx:start+2,cy:y(ref[direction]),r:2.3,fill:"white"});
    }
    if(index%4===0)add("text",{x:x+1,y:96},String(hour).padStart(2,"0"));
    const target=add("rect",{x,y:11,width:12,height:74,fill:"transparent"});
    const tip=document.createElementNS(ns,"title");
    tip.textContent=hour+":00 · "+fmt(counts[hour][0])+" arriving, "+fmt(counts[hour][1])+" leaving";target.append(tip);
    target.onclick=()=>jumpTime(240+60*index);
  }
}

export class CampusDay {
  constructor(report,services,places,follow,refresh,jumpTime){
    this.report=report;this.services=services;this.places=places;this.refresh=refresh;
    this.residents=new Map();
    this.passengers=new ScheduledPassengers(services,places,refresh,e=>{el("campus-rides").textContent=e.message;});
    for(const row of report.rides){
      const key=row[0]+"/"+row[1];
      if(!this.residents.has(key))this.residents.set(key,[]);
      this.residents.get(key).push(row);
    }
    const counts=report.flow.map(hour=>hour.map(sum));
    const model={daily:sum(counts.flat()),amIn:counts[9][0],amOut:counts[9][1],pmIn:counts[17][0],pmOut:counts[17][1]};
    for(const [key,label] of [["daily","Both directions, all day"],["amIn","09–10 arriving"],["amOut","09–10 leaving"],["pmIn","17–18 arriving"],["pmOut","17–18 leaving"]]){
      const row=el("campus-comparison").insertRow();
      const heading=document.createElement("th");heading.scope="row";heading.textContent=label;row.append(heading);
      row.insertCell().textContent=fmt(model[key]);row.insertCell().textContent=fmt(report.totals[key]);
    }
    drawHourly(counts,report.totals,jumpTime);
    el("campus-mode").textContent=fmt(sum(report.flow.map(hour=>hour[0][1]+hour[1][1])))+
      " modelled daily transit trips across the campus boundary · "+fmt(report.reference.daily[1])+" in UBC’s count.";
    el("campus-rides").textContent=fmt(report.rides.length)+" of "+fmt(report.transitBouts)+
      " modelled campus transit trips fit a direct scheduled ride and a street walk of up to 800 m at each end.";
    el("campus-reference").href=report.source;
    el("campus-example").hidden=!report.rides.length;
    el("campus-example").onclick=async()=>{
      const row=report.rides.find(r=>r[2]>=420&&r[2]<660)||report.rides[0];
      try{
        await services.init();
        el("transit-panel").open=true;
        await services.select(row[6]);
        const data=await this.passengers.routeData(row[6]), ride=data.rides[row[7]];
        const start=ride[1]+ride[2][2*row[8]+1],end=ride[1]+ride[2][2*row[9]];
        await follow(row[0],row[1],(start+end)/120);
      }catch(e){el("campus-rides").textContent=e.message;}
    };
    el("campus-panel").hidden=false;
  }

  render(t){
    const row=this.report.presence[Math.floor(t)-240],hour=this.report.flow[Math.floor(t/60)%24];
    el("campus-hour").setAttribute("x",String(16+12*((Math.floor(t/60)+20)%24)));
    el("campus-presence").textContent=fmt(sum(row))+" people at assigned campus locations · "+fmt(sum(row.slice(4)))+" live outside the campus area.";
    el("campus-activities").textContent=fmt(row[1]+row[5])+" at work · "+fmt(row[2]+row[6])+" at school · "+
      fmt(row[0]+row[4])+" at home · "+fmt(row[3]+row[7])+" at other places.";
    el("campus-flow").textContent=fmt(sum(hour[0]))+" arrivals and "+fmt(sum(hour[1]))+" departures in this clock hour.";
  }

  passenger(da,index,t,network){
    const row=this.residents.get(da+"/"+index)?.find(r=>t>=r[2]&&t<r[2]+r[3]);
    if(!row)return null;
    return this.passengers.position(row,t,network);
  }
}
