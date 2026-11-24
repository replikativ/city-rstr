import {visitAt} from "../js/replay/replay.js";
import {track} from "../js/vancouver/route-timeline.js";
import {WALK,distance} from "./vancouver-network.js";
import {radius} from "./street-pedestrians.js";
import {scenarioActor} from "./street-scenarios.js";
import {findRoute,routeKey} from "./weekday-pathfinder.js";

const personKey=(d,i)=>d+"/"+i;
const inVisit=(visit,minute)=>visit.depart<=minute&&minute<visit.finish;

export class GroceryWalks {
  constructor(places,graph,speed){
    Object.assign(this,{places,graph,speed});
    this.people=new Map();
    this.hours=new Map();
    this.proposals=[];
    this.routes=new Map();
  }
  add(row,stop,proposed,timing){
    const [d,i,slot,start,dwell,,,,,,,inward,onward,from,to,,mode="walk",kind]=row;
    if(mode!=="walk"||kind||slot<0||!this.places[from]||!this.places[to]||!(inward>0&&onward>0))return;
    const [arrive,leave]=timing??[start,start+dwell];
    const visit={d,i,from,stop,to,proposed,depart:arrive-inward,arrive,leave,finish:leave+onward};
    const key=personKey(d,i);
    if(!this.people.has(key))this.people.set(key,[]);
    this.people.get(key).push(visit);
    if(proposed)this.proposals.push(visit);
    for(let hour=Math.floor(visit.depart/60);hour<Math.ceil(visit.finish/60);hour++){
      if(!this.hours.has(hour))this.hours.set(hour,[]);
      this.hours.get(hour).push(visit);
    }
    return visit;
  }
  visit(d,i,minute){
    return this.people.get(personKey(d,i))?.find(visit=>inVisit(visit,minute));
  }
  state(d,i,minute,trail=false){
    const visit=this.visit(d,i,minute);
    return visit?this.resolve(visit,minute,trail):null;
  }
  resolve(visit,minute,trail=false,centre){
    const span=visitAt(visit,minute);
    if(!span)return null;
    const {phase,from,to,start,end,fraction}=span;
    const a=this.places[from],b=this.places[to],dur=end-start;
    const mode=phase==="stop"?"stop":"walk";
    if(centre&&(mode==="stop"||distance(a,centre)>radius+(minute-start)*this.speed||
       distance(b,centre)>radius+(end-minute)*this.speed))return null;
    const state={mode,a,b,start,dur,kind:phase==="outbound"?"next stop":"grocery shopping",
      method:"recorded grocery visit"};
    if(mode==="stop")return {...state,p:a};
    const graph=this.graph();
    if(!graph)return {...state,positionNote:"loading walking network"};
    const key=routeKey(WALK,a,b,dur,this.speed,false);
    if(!this.routes.has(key)){
      const route=findRoute(graph,WALK,a,b,dur,this.speed,false);
      this.routes.set(key,route?.minutes<=dur?{path:route.path,
        offsets:route.offsets.map(offset=>route.minutes?offset*dur/route.minutes:0)}:null);
    }
    const route=this.routes.get(key);
    if(!route)return {...state,positionNote:"no connected walk within the diary time"};
    const motion=track(route.path,route.offsets,fraction*dur,trail?1.5:0);
    return {...state,...route,p:motion.position,trail:motion.trail,routed:true};
  }
  nearby(minute,centre){
    const actors=[];
    for(const visit of this.hours.get(Math.floor(minute/60))??[]){
      const {d,i}=visit;
      if(!inVisit(visit,minute)||this.visit(d,i,minute)!==visit)continue;
      const state=this.resolve(visit,minute,false,centre);
      const actor=scenarioActor(d,i,minute,centre,state,visit.proposed?"grocery-opening":"grocery-walk");
      if(actor)actors.push(actor);
    }
    return actors;
  }
}
