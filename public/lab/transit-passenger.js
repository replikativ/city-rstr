import {positionOn} from "./vancouver-network.js";
import {pointAt,vehicleAt} from "./regional-transit.js";

export function publishedStreetWalks(rows,person){
  const key=p=>p.slice(0,2).join("/");
  const walks=new Map();
  for(const [i,,access,egress] of rows)if(i===person)
    for(const path of [access,egress])walks.set(key(path[0])+"/"+key(path.at(-1)),path);
  return {route:(a,b)=>walks.get(key(a)+"/"+key(b))};
}

export function rideTiming(row,data,waitAtDestination=false){
  const [,,start,duration,,,,trip,board,alight,access,egress]=row;
  const ride=data.rides[trip],pat=data.patterns[ride[0]];
  const boardAt=ride[1]+ride[2][2*board+1],alightAt=ride[1]+ride[2][2*alight];
  return {ride,pat,boardAt,alightAt,from:data.stations[pat.stops[board]],to:data.stations[pat.stops[alight]],
    accessStart:start*60,access,egressStart:waitAtDestination?alightAt:(start+duration)*60-egress,egress};
}

export function onwardRide(row){
  const onward=row[12];
  if(!onward)return null;
  const next=[...row.slice(0,6),...onward.slice(0,4),0,row[11]];
  if(onward[7])next.push(onward[7]);
  return next;
}

export function activeWalks(rows,sec,maxSeconds){
  let lo=0,hi=rows.length;
  while(lo<hi){
    const mid=Math.floor((lo+hi)/2);
    if(rows[mid][0]<=sec-maxSeconds)lo=mid+1;else hi=mid;
  }
  const active=[];
  for(let i=lo;i<rows.length&&rows[i][0]<=sec;i++)
    if(sec<rows[i][0]+rows[i][1])active.push(rows[i]);
  return active;
}

export class ScheduledPassengers{
  constructor(services,places,refresh,onError){
    Object.assign(this,{services,places,refresh,onError});
    this.routes=new Map();this.loading=new Map();this.paths=new Map();
  }
  routeData(id){
    if(!this.loading.has(id)){
      this.loading.set(id,this.services.routeData(id).then(data=>{
        this.routes.set(id,data);this.refresh();return data;
      }).catch(e=>{this.loading.delete(id);throw e;}));
    }
    return this.loading.get(id);
  }

  walking(place,route,stop,station,toStop,network,fraction){
    const venue=this.places[place],origin=toStop?venue:station,destination=toStop?station:venue;
    const key="walk/"+place+"/"+route+"/"+stop+"/"+toStop;
    if(network&&!this.paths.has(key))this.paths.set(key,network.route(origin,destination,1));
    const street=this.paths.get(key),path=street||[origin,destination];
    return {p:positionOn(path,fraction),path,routed:!!street,
      description:(toStop?"Walking to ":"Walking from ")+station[2]};
  }

  position(row,t,network,waitAtDestination=false){
    const [,,,,a,b,id,run,board,alight]=row;
    const data=this.routes.get(id);
    if(!data){
      this.routeData(id).catch(e=>this.onError(e));
      return null;
    }
    const {ride,pat,boardAt,alightAt,from,to,accessStart,access,egressStart,egress}=rideTiming(row,data,waitAtDestination);
    const sec=t*60;
    if(sec>=boardAt&&sec<alightAt){
      const pathKey=id+"/"+ride[0]+"/"+board+"/"+alight;
      if(!this.paths.has(pathKey)){
        const lo=pat.dist[board],hi=pat.dist[alight];
        this.paths.set(pathKey,[pointAt(pat,lo),...pat.line.filter((p,i)=>pat.axis[i]>lo&&pat.axis[i]<hi),pointAt(pat,hi)]);
      }
      return {p:vehicleAt(ride,pat,sec).p,path:this.paths.get(pathKey),routed:pat.mapped,vehicle:[id,run],
        description:"Scheduled "+(this.services.manifest?.routes.find(r=>r.id===id)?.name||"transit")+" toward "+ride[3]+" · "+from[2]+" → "+to[2]};
    }
    const firstLeg=sec<boardAt;
    const walkStarts=firstLeg?accessStart:egressStart;
    const walkSeconds=firstLeg?access:egress;
    if(!firstLeg&&waitAtDestination&&sec>=walkStarts+walkSeconds)
      return {p:this.places[b],description:"Arrived · waiting for the next diary activity"};
    if(sec<walkStarts||sec>=walkStarts+walkSeconds)
      return {p:firstLeg?from:to,description:"Waiting at "+(firstLeg?from:to)[2]};
    return this.walking(firstLeg?a:b,id,pat.stops[firstLeg?board:alight],firstLeg?from:to,firstLeg,network,
                        (sec-walkStarts)/walkSeconds);
  }

  transferPosition(row,minute,network){
    const id=row[6],next=onwardRide(row);
    const [nextId,,,,seconds,,path]=row[12];
    const first=rideTiming(row,this.routes.get(id),true);
    const sec=minute*60;
    if(sec<first.alightAt)return this.position(row,minute,network,true);
    const second=rideTiming(next,this.routes.get(nextId),true);
    if(sec>=second.boardAt)return next[12]?this.transferPosition(next,minute,network):this.position(next,minute,network,true);
    const elapsed=sec-first.alightAt;
    return elapsed<seconds ?
      {p:positionOn(path,elapsed/seconds),path,routed:true,description:"Walking to transfer at "+second.from[2]} :
      {p:second.from,description:"Waiting to transfer at "+second.from[2]};
  }
}
