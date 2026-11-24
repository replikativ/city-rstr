import {BIKE,Network} from "./vancouver-network.js";
import {findRoute} from "./weekday-pathfinder.js";

let road,cycle;
async function load(url) {
  const response=await fetch(url);
  if(!response.ok)throw Error("The route data is unavailable.");
  return response.json();
}
self.onmessage=async({data})=>{
  try {
    if(data.network){
      const profile=data.driving?await fetch(data.driving).then(r=>r.ok?r.json():null):null;
      if(data.hourlyDriving&&!profile?.hourly)throw Error("The observed road speed profile is unavailable.");
      [road,cycle]=await Promise.all([
        load(data.network).then(net=>new Network(net,null,profile)),
        data.cycling?load(data.cycling).then(net=>new Network(net,data.bikeways)):null
      ]);
      self.postMessage({ready:true,speeds:!!profile});
      return;
    }
    const results=data.requests.map(([key,mode,...args])=>[key,findRoute(mode===BIKE?cycle:road,mode,...args)]);
    self.postMessage({results});
  }catch(error){self.postMessage({error:error.message});}
};
