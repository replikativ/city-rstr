import {distance,lngLat} from "./vancouver-network.js";

const el=id=>document.getElementById(id);
const fc=features=>({type:"FeatureCollection",features});
const fmt=t=>{
  const m=Math.floor(t/60);return String(Math.floor(m/60)%24).padStart(2,"0")+":"+String(m%60).padStart(2,"0")+(m>=1440?" +1":"");
};
const geom=(geometry,properties={})=>({type:"Feature",geometry,properties});

export function pointAt(pattern,d){
  const line=pattern.line,axis=pattern.axis;
  let lo=0,hi=axis.length-1;
  while(lo+1<hi){const mid=(lo+hi)>>1;if(axis[mid]<=d)lo=mid;else hi=mid;}
  const f=Math.max(0,Math.min(1,(d-axis[lo])/(axis[hi]-axis[lo]||1)));
  return [line[lo][0]+(line[hi][0]-line[lo][0])*f,line[lo][1]+(line[hi][1]-line[lo][1])*f];
}

export function vehicleAt(ride,pattern,second){
  const [,first,times]=ride,t=second-first;
  if(t<0||t>times.at(-1))return null;
  let stop=0;
  while(stop+1<pattern.stops.length&&times[2*stop+2]<=t)stop++;
  const next=Math.min(stop+1,pattern.stops.length-1),dep=times[2*stop+1],arr=times[2*next];
  const f=t<=dep||arr<=dep?0:(t-dep)/(arr-dep);
  const d=pattern.dist[stop]+f*(pattern.dist[next]-pattern.dist[stop]);
  return {p:pointAt(pattern,d),stop:pattern.stops[t<=dep?stop:next],atStop:t<=dep};
}

export async function loadRouteGeometry(load,url){
  const data=await load(url);
  for(const p of data.patterns){
    p.axis=[0];
    for(let i=1;i<p.line.length;i++)p.axis.push(p.axis[i-1]+distance(p.line[i-1],p.line[i]));
  }
  return data;
}

export class RegionalTransit{
  constructor(map,load,getTime,version,cityRelease=null,studyArea=null){
    this.map=map;this.version=version;this.load=load;this.getTime=getTime;this.request=0;this.routes=new Map();
    this.cityRelease=cityRelease;
    this.studyArea=studyArea;
    this.root=cityRelease?"data/vancouver/transit/":"data/vancouver/region/transit/";
    this.base=version?"data/vancouver/region/transit/"+version+"/":null;
    for(const [id,type,paint] of [
      ["service-line","line",{"line-color":"#76c8ef","line-width":3,"line-opacity":.85}],
      ["service-stops","circle",{"circle-radius":2.3,"circle-color":"#d4f3ff"}],
      ["service-vehicles","circle",{"circle-radius":5,"circle-color":"#2c94d9","circle-stroke-color":"white","circle-stroke-width":1.5}]
    ]){
      map.addSource(id,{type:"geojson",data:fc([])});map.addLayer({id,source:id,type,paint});
    }
    el("transit-panel").hidden=false;
    el("transit-panel").ontoggle=()=>{if(el("transit-panel").open)this.init().catch(e=>this.status(e.message));};
    el("transit-route").onchange=()=>this.select(el("transit-route").value).catch(e=>this.status(e.message));
    el("transit-fit").onclick=()=>{
      if(!this.current)return;
      const box=new window.maplibregl.LngLatBounds();
      for(const p of this.current.patterns)for(const q of p.line)box.extend(lngLat(q));
      this.map.fitBounds(box,{padding:40,pitch:0,bearing:0,maxZoom:15,duration:0});
    };
    map.on("click","service-vehicles",e=>this.status(e.features[0].properties.title));
    map.on("click","service-stops",e=>this.status(e.features[0].properties.name));
    if(new URL(location.href).searchParams.has("service"))el("transit-panel").open=true;
  }
  status(text){el("transit-status").textContent=text;}
  async init(){
    if(this.manifest)return;
    this.pending??=(this.version?Promise.resolve({version:this.version}):this.cityRelease?this.cityRelease().then(p=>({version:p.transit})):this.load(this.root+"current.json")).then(async p=>{
      this.base=this.root+p.version+"/";
      return this.load(this.base+"transit.json");
    }).catch(e=>{this.pending=null;throw e;});
    const data=await this.pending;if(this.manifest)return;this.manifest=data;
    for(const r of data.routes)el("transit-route").add(new Option(r.label===r.name?r.name:r.name+" · "+r.label,r.id));
    el("transit-source").textContent="TransLink scheduled service · "+data.date+" · "+data.routes.length+" routes serving "+(this.studyArea??(this.cityRelease?"Vancouver":"UBC or the North Shore"))+". Vehicle positions are interpolated between scheduled stops.";
    const key=new URL(location.href).searchParams.get("service");
    const initial=key??(this.studyArea?"":this.cityRelease?"99":"SeaBus");
    const route=data.routes.find(r=>r.name.toLowerCase()===initial.toLowerCase());
    await this.select(route?.id||"");
    this.onReady?.();
  }
  routeData(id){
    if(!this.routes.has(id)){
      const request=loadRouteGeometry(this.load,this.base+id+".json")
        .catch(e=>{this.routes.delete(id);throw e;});
      this.routes.set(id,request);
    }
    return this.routes.get(id);
  }
  async select(id){
    const token=++this.request;this.current=null;this.route=null;
    this.onSelection?.(id);
    ["service-line","service-stops","service-vehicles"].forEach(k=>this.map.getSource(k).setData(fc([])));
    el("transit-fit").hidden=true;el("transit-active").textContent="";el("transit-route").value=id;
    const route=this.manifest.routes.find(r=>r.id===id);
    const url=new URL(location.href);
    if(route)url.searchParams.set("service",route.name);else url.searchParams.delete("service");
    history.replaceState(null,"",url);
    if(!route){this.status("");el("transit-active").textContent="";return;}
    this.status("Loading "+route.name+"…");
    const data=await this.routeData(id);if(token!==this.request)return;
    this.current=data;this.route=route;
    this.map.getSource("service-line").setData(fc(data.patterns.map(p=>geom({type:"LineString",coordinates:p.line.map(lngLat)}))));
    this.map.getSource("service-stops").setData(fc(data.stations.map(([x,y,name])=>geom({type:"Point",coordinates:lngLat([x,y])},{name}))));
    el("transit-fit").hidden=false;this.status(route.name+" · "+route.trips+" scheduled trips in this weekday.");this.render(this.getTime());
  }
  render(minute){
    if(!this.current)return;
    const dots=[];
    for(const ride of this.current.rides){
      const state=vehicleAt(ride,this.current.patterns[ride[0]],minute*60);
      if(state)dots.push(geom({type:"Point",coordinates:lngLat(state.p)},
        {title:this.route.name+" · "+ride[3]+" · "+fmt(ride[1])+" departure · "+(state.atStop?"at ":"towards ")+this.current.stations[state.stop][2]}));
    }
    this.map.getSource("service-vehicles").setData(fc(dots));el("transit-active").textContent=dots.length+" in service";
  }
}
