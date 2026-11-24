import {lngLat} from "./vancouver-network.js";

const el=id=>document.getElementById(id);
const fmt=n=>n.toLocaleString();
const slug=name=>name.toLowerCase().replaceAll(" ","-");
const clock=t=>String(Math.floor(t/60)%24).padStart(2,"0")+":"+String(t%60).padStart(2,"0");
const fc=features=>({type:"FeatureCollection",features});
const point=(coord,properties)=>({type:"Feature",geometry:{type:"Point",coordinates:lngLat(coord)},properties});

export class CampusVisitors{
  constructor(map,getData,getTime,locate){
    this.map=map;this.time=getTime;this.load=getData;this.locate=locate;
    this.group="residents";this.site=0;this.activeBuilding=null;this.lastKey="";
    for(const [id,paint] of [
      ["campus-attendees",{"circle-color":["case",["get","near"],"#f9d37e","#a69dda"],"circle-radius":["interpolate",["linear"],["get","count"],0,2,20,4,100,7,300,10],"circle-opacity":.86}],
      ["campus-shop",{"circle-color":"#293733","circle-stroke-color":"#ffdc84","circle-stroke-width":3,"circle-radius":6}]
    ]){
      map.addSource(id,{type:"geojson",data:fc([])});map.addLayer({id,type:"circle",source:id,paint});
    }
    map.on("click","campus-attendees",e=>{
      this.activeBuilding=e.features[0].properties.building;this.render(this.time(),true);
    });
    const panel=el("campus-shops"),params=new URLSearchParams(location.search);
    panel.hidden=false;
    panel.ontoggle=()=>{
      if(panel.open)this.open().catch(e=>el("visitor-status").textContent=e.message);
      else{
        this.draw([],null);this.lastKey="";
      }
    };
    if(params.has("cafe")||params.has("cohort"))panel.open=true;
  }
  async open(){
    if(!this.result){
      this.pending??=this.load().catch(e=>{this.pending=null;throw e;});
      const r=await this.pending;
      if(!this.result){
        this.result=r;
        const params=new URLSearchParams(location.search);
        this.site=Math.max(0,r.sites.findIndex(s=>slug(s.name)===params.get("cafe")));
        this.group=Object.hasOwn(r.cohorts,params.get("cohort"))?params.get("cohort"):"residents";
        for(const s of r.sites)el("visitor-site").add(new Option(s.name,slug(s.name)));
        el("visitor-site").value=slug(r.sites[this.site].name);el("visitor-group").value=this.group;
        el("visitor-controls").hidden=false;el("visitor-status").textContent="";
        el("visitor-group").onchange=()=>this.change(false);
        el("visitor-site").onchange=()=>this.change(true);
        el("visitor-locate").onclick=()=>this.locate(this.result.sites[this.site].point);
        const refs=el("visitor-sources");
        for(const [key,label] of [["enrolment","Enrolment"],["studentOrigins","Student survey"],["employeeCounts","Employee counts"],["employeeOrigins","Employee origins"]]){
          const link=document.createElement("a");link.href=r.sources[key];link.textContent=label;
          if(refs.childNodes.length)refs.append(" · ");refs.append(link);
        }
        if(params.has("cafe")&&el("campus-shops").open)this.locate(r.sites[this.site].point);
      }
    }
    if(el("campus-shops").open)this.render(this.time(),true);
  }
  change(move){
    this.site=this.result.sites.findIndex(s=>slug(s.name)===el("visitor-site").value);
    this.group=el("visitor-group").value;this.activeBuilding=null;
    const url=new URL(location.href);url.searchParams.set("cafe",el("visitor-site").value);
    if(this.group==="residents")url.searchParams.delete("cohort");else url.searchParams.set("cohort",this.group);
    history.replaceState(null,"",url);
    if(move)this.locate(this.result.sites[this.site].point);
    this.render(this.time(),true);
  }
  draw(features,site){
    this.map.getSource("campus-attendees").setData(fc(features));
    this.map.getSource("campus-shop").setData(fc(site?[point(site.point,{name:site.name})]:[]));
  }
  render(t,force=false){
    if(!this.result||!el("campus-shops").open)return;
    const minute=Math.floor(t),key=[this.site,this.group,minute,this.activeBuilding].join("/");
    if(!force&&this.lastKey===key)return;this.lastKey=key;
    const site=this.result.sites[this.site],cohort=this.result.cohorts[this.group],at=minute-240;
    const residents=site.residents[at],extra=cohort?.presence[this.site+1][at]||0;
    el("visitor-now").textContent=fmt(residents+extra)+" people within a five-minute walk at "+clock(minute)+
      " · "+fmt(residents)+" residents"+(cohort?" + "+fmt(extra)+" external "+this.group:"");
    el("visitor-lunch").textContent=fmt(site.lunch+(cohort?.lunch[this.site]||0))+" distinct people within reach at least once from 11:00 to 14:00"+
      (cohort?" ("+fmt(cohort.lunch[this.site])+" external)":"")+".";
    const buildings=this.result.buildings,counts=new Uint32Array(buildings.length),near=new Set(site.buildings);
    let first=null;
    if(cohort){
      const present=cohort.templates.map(spans=>spans.some(([s,e])=>s<=minute&&minute<e));
      for(const g of cohort.groups){
        g.roster.forEach(([d,b],i)=>{
          if(!present[d])return;counts[b]++;
          if(!first&&b===this.activeBuilding)first={g,i,d};
        });
      }
      el("visitor-origin").textContent=cohort.groups.map(g=>g.city+" "+fmt(g.attending)).join(" · ")+
        " attended at some point in this weekday. "+fmt(cohort.presence[0][at])+" are at campus buildings now.";
      const pct=s=>Math.round(s.weekdayShare*100)+"%";
      el("visitor-diaries").textContent=cohort.fit.attending+" of "+cohort.fit.diaries+" eligible training diaries recorded on-site "+
        (this.group==="students"?"study":"work")+" ("+pct(cohort.fit)+" weighted). The held-out diaries give "+pct(cohort.holdout)+
        " ("+cohort.holdout.attending+" of "+cohort.holdout.diaries+").";
    }else{
      el("visitor-origin").textContent="The resident weekday covers Vancouver, UBC and the North Shore.";
      el("visitor-diaries").textContent="";
    }
    const features=[];
    buildings.forEach((b,i)=>{
      if(counts[i]||near.has(i))features.push(point(b.point,{building:i,count:counts[i],near:near.has(i)}));
    });
    this.draw(features,site);
    if(this.activeBuilding!==null){
      const label=buildings[this.activeBuilding].name;
      el("visitor-inspect").textContent=label+" · "+(near.has(this.activeBuilding)?"within":"outside")+" the five-minute catchment"+
        (cohort?" · "+fmt(counts[this.activeBuilding])+" external "+this.group:"")+".";
      if(first){
        const spans=cohort.templates[first.d].map(([s,e])=>clock(s)+"–"+clock(e)).join(", ");
        el("visitor-inspect").textContent+=" Example "+first.g.city+" "+(this.group==="students"?"student":"employee")+" #"+(first.i+1)+" is assigned here "+spans+".";
      }
    }else el("visitor-inspect").textContent="";
  }
}
