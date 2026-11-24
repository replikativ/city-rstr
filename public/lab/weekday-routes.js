import {reusableFreeFlow,routeKey} from "./weekday-pathfinder.js";
import {departureHour} from "./vancouver-network.js";

export class WeekdayRoutes {
  constructor(config,render) {
    Object.assign(this,{config,render});
    this.paths=new Map();
    this.inFlight=new Set();
    this.hours=new Map();
  }
  begin(minute) { this.hour=Math.floor(minute/60);this.requests=new Map();this.priority=null; }
  get(mode,a,b,duration,speed,prefer=false,departure,priority=false) {
    const hour=mode===2&&this.config.hourlyDriving&&departure!==undefined?departureHour(departure):undefined;
    const baseline=routeKey(mode,a,b,duration,speed,prefer);
    const key=hour===undefined?baseline:baseline+"/"+hour;
    if(hour!==undefined&&!this.paths.has(key)&&this.reuseBaseline&&this.paths.has(baseline)){
      const route=this.paths.get(baseline);
      if(reusableFreeFlow(route,this.config.affected))return route;
    }
    if(!this.paths.has(key)&&!this.inFlight.has(key))this.requests.set(key,[key,mode,a.slice(0,2),b.slice(0,2),duration,speed,prefer,departure]);
    if(priority&&this.requests.has(key))this.priority=key;
    return this.paths.get(key);
  }
  flush() {
    if(!this.requests.size||this.error)return;
    if(this.config.cache&&!this.cacheUnavailable&&!this.hours.get(this.hour)){
      this.loadHour(this.hour);
      return;
    }
    if(this.hours.get(this.hour)==="loading"||this.inFlight.size)return;
    if(!this.worker){this.start();return;}
    if(!this.ready)return;
    const requests=this.priority?[this.requests.get(this.priority)]:Array.from(this.requests.values()).slice(0,32);
    this.inFlight=new Set(requests.map(row=>row[0]));
    this.worker.postMessage({requests});
  }
  async loadHour(hour) {
    this.hours.set(hour,"loading");
    try{
      this.directory??=fetch(this.config.cache).then(async response=>{
        if(!response.ok)return null;
        const {version}=await response.json();
        const directory=new URL(version+"/",new URL(this.config.cache,document.baseURI)).href;
        if(this.config.affected&&this.config.baselineDigest){
          const response=await fetch(directory+"manifest.json");
          this.reuseBaseline=response.ok&&(await response.json()).driveProfileDigest===this.config.baselineDigest;
        }
        return directory;
      });
      const directory=await this.directory;
      if(!directory)this.cacheUnavailable=true;
      else{
        const response=await fetch(directory+hour+".json");
        if(response.ok)for(const [key,result] of await response.json())this.paths.set(key,result);
      }
    }catch{
      this.cacheUnavailable=true;
    }finally{
      this.hours.set(hour,"done");
      while(this.hours.size>4)this.hours.delete(this.hours.keys().next().value);
      while(this.paths.size>12_000)this.paths.delete(this.paths.keys().next().value);
      this.render();
    }
  }
  start() {
    this.worker=new Worker(new URL("./weekday-routes-worker.js",import.meta.url),{type:"module"});
    this.worker.onmessage=({data})=>{
      if(data.error){this.fail(data.error);return;}
      if(data.ready){this.ready=true;this.speeds=data.speeds;}
      if(data.results){
        for(const [key,result] of data.results)this.paths.set(key,result);
        this.inFlight.clear();
        while(this.paths.size>12_000)this.paths.delete(this.paths.keys().next().value);
      }
      this.render();
    };
    this.worker.onerror=event=>this.fail(event.message||"The street router is unavailable.");
    const {network,cycling,bikeways,driving,hourlyDriving}=this.config;
    const absolute=url=>url&&new URL(url,document.baseURI).href;
    this.worker.postMessage({network:absolute(network),cycling:absolute(cycling),driving:absolute(driving),bikeways,hourlyDriving});
  }
  fail(message) { this.error=message;this.render(); }
}
