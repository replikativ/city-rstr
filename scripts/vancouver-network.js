// Local east/south metres. The graph stores separate bits for each vehicle direction.
export const xy = ([lon,lat]) => [(lon+123.1)*72600,(49.26-lat)*111195];
export const lngLat = ([x,y]) => [x/72600-123.1,49.26-y/111195];
export const distance = (a,b) => Math.hypot(b[0]-a[0],b[1]-a[1]);
export const departureHour = minute => ((Math.floor(minute/60)%24)+24)%24;
export const WALK=1, CAR=2;
export const BIKE=4;

class MinHeap {
  constructor(){this.data=[];}
  push(entry){
    const a=this.data;let i=a.length;a.push(entry);
    while(i){const p=(i-1)>>1;if(a[p][0]<=entry[0])break;a[i]=a[p];i=p;}
    a[i]=entry;
  }
  pop(){
    const a=this.data, first=a[0],last=a.pop();
    if(!a.length)return first;
    let i=0;
    while(2*i+1<a.length){
      let j=2*i+1;if(j+1<a.length && a[j+1][0]<a[j][0])j++;
      if(last[0]<=a[j][0])break;
      a[i]=a[j];i=j;
    }
    a[i]=last;return first;
  }
}

export class Network {
  constructor({nodes,ways},bikeways=null,driving=null){
    this.nodes=nodes;
    if(bikeways){
      this.offBikewayCost=bikeways.offBikewayCost;
      if(!(this.offBikewayCost>=1))throw Error("Invalid bikeway travel cost");
      this.bikeways=new Set(bikeways.arcs.map(([a,b])=>a*nodes.length+b));
      this.maxBikeCost=this.offBikewayCost;
      if(bikeways.uphillArcs){
        const costs=bikeways.uphillCosts;
        if(!costs?.length||!costs.every(cost=>Number.isFinite(cost)&&cost>=0))
          throw Error("Invalid bicycle grade cost");
        this.uphill=new Map(bikeways.uphillArcs.map(([a,b,band])=>{
          if(costs[band]===undefined)throw Error("Unknown bicycle grade band");
          return [a*nodes.length+b,costs[band]];
        }));
        this.maxBikeCost+=Math.max(...costs);
      }
    }
    const degree=new Uint32Array(nodes.length);
    const each=(callback)=>{
      for(const [way,[bits,,ids]] of ways.entries()){
        for(let i=1;i<ids.length;i++){
          const a=ids[i-1],b=ids[i];
          if(a===b || distance(nodes[a],nodes[b])===0)continue;
          const forward=(bits&3)|((bits&8)>>1),reverse=(bits&1)|((bits&4)>>1)|((bits&16)>>2);
          if(forward)callback(a,b,forward,way,0);
          if(reverse)callback(b,a,reverse,way,1);
        }
      }
    };
    each(a=>degree[a]++);
    const offset=new Uint32Array(nodes.length+1);
    for(let i=0;i<nodes.length;i++)offset[i+1]=offset[i]+degree[i];
    this.offset=offset;const size=offset[nodes.length];
    this.to=new Uint32Array(size);this.mask=new Uint8Array(size);
    if(driving){
      if(driving.kmh.length!==ways.length||!(driving.connectorKmh>0)||!(driving.connectorMetres>0))
        throw Error("The driving speeds do not match the street graph");
      this.driveSpeed=new Float64Array(size);
      this.connectorSpeed=driving.connectorKmh*1000/60;
      this.connectorMetres=driving.connectorMetres;
      this.maxDriveSpeed=this.connectorSpeed;
      if(driving.hourly){
        const {hours,corridors}=driving.hourly;
        this.trafficHours=new Map(hours.map((hour,column)=>[hour,column]));
        this.traffic=new Map();
        for(const {arcs,factors} of corridors){
          if(factors.length!==hours.length||!factors.every(f=>Number.isFinite(f)&&f>=1))
            throw Error("Invalid observed road travel times");
          for(const [a,b] of arcs)this.traffic.set(a*nodes.length+b,factors);
        }
      }
    }
    const cursor=offset.slice(),allowed=new Uint8Array(nodes.length);
    each((a,b,bits,way,direction)=>{
      const i=cursor[a]++;this.to[i]=b;this.mask[i]=bits;allowed[a]|=bits;
      allowed[b]|=bits&(driving?BIKE|CAR:BIKE);
      if(driving&&(bits&CAR)){
        const speed=driving.kmh[way][direction]*1000/60;
        if(!(speed>0))throw Error("Missing speed on a directed driving edge");
        this.driveSpeed[i]=speed;
        this.maxDriveSpeed=Math.max(this.maxDriveSpeed,speed);
      }
    });
    this.allowed=allowed;this.cells=new Map();
    nodes.forEach(([x,y],i)=>{
      if(!allowed[i])return;
      const key=Math.floor(x/120)+','+Math.floor(y/120);
      if(!this.cells.has(key))this.cells.set(key,[]);
      this.cells.get(key).push(i);
    });
  }
  snap(p,mode){
    const x=Math.floor(p[0]/120),y=Math.floor(p[1]/120);
    let nearest=-1,bestSquared=Infinity;
    for(let r=0;r<=8;r++){
      for(let a=-r;a<=r;a++)for(let b=-r;b<=r;b++){
        if(r && Math.max(Math.abs(a),Math.abs(b))!==r)continue;
        for(const i of this.cells.get((x+a)+','+(y+b))||[]){
          if(!(this.allowed[i]&mode))continue;
          const node=this.nodes[i],dx=node[0]-p[0],dy=node[1]-p[1],squared=dx*dx+dy*dy;
          if(squared<bestSquared||(squared===bestSquared&&i<nearest)){bestSquared=squared;nearest=i;}
        }
      }
      if(bestSquared<(r*120)**2)break;
    }
    return nearest;
  }
  route(a,b,mode,maxMetres=Infinity,prefer=!!this.bikeways&&mode===BIKE){
    return this.search(a,b,mode,maxMetres,prefer,false);
  }
  driveRoute(a,b,maxMinutes=Infinity,departure){
    if(!this.driveSpeed)return null;
    return this.search(a,b,CAR,maxMinutes,false,true,this.trafficHours?.get(departureHour(departure)));
  }
  search(a,b,mode,budget,prefer,timed,trafficHour){
    const start=this.snap(a,mode),end=this.snap(b,mode);
    if(start<0||end<0)return null;
    const queue=new MinHeap(),goal=this.nodes[end];
    const from=distance(a,this.nodes[start]),to=distance(b,goal);
    if(timed&&(from>this.connectorMetres||to>this.connectorMetres))return null;
    const access=timed?from/this.connectorSpeed:from, egress=timed?to/this.connectorSpeed:to;
    const unit=timed?this.maxDriveSpeed:1;
    const streetBudget=budget-access-egress;
    const limit=prefer?streetBudget*this.maxBikeCost:streetBudget;
    const estimateFrom=p=>distance(p,goal)/unit;
    if(estimateFrom(this.nodes[start])>limit)return null;
    this.scratch??={seen:new Uint32Array(this.nodes.length),cost:new Float64Array(this.nodes.length),
      prev:new Uint32Array(this.nodes.length),generation:0};
    const {seen,cost,prev}=this.scratch;
    this.scratch.generation=(this.scratch.generation+1)>>>0;
    if(!this.scratch.generation){seen.fill(0);this.scratch.generation=1;}
    const generation=this.scratch.generation;
    seen[start]=generation;cost[start]=0;
    queue.push([estimateFrom(this.nodes[start]),start,0]);
    while(queue.data.length){
      const [estimate,u,g]=queue.pop();
      if(estimate>limit)return null;
      if(g!==cost[u])continue;
      if(u===end){
        const points=[b,goal];let v=u;
        const offsets=timed?[access+g+egress,access+g]:null;
        while(v!==start){
          v=prev[v];points.push(this.nodes[v]);
          if(timed)offsets.push(access+cost[v]);
        }
        points.push(a);points.reverse();
        if(timed){offsets.push(0);return {path:points,offsets:offsets.reverse(),minutes:access+g+egress};}
        if(prefer&&points.reduce((m,p,k)=>m+(k?distance(points[k-1],p):0),0)>budget)
          return this.route(a,b,mode,budget,false);
        return points;
      }
      for(let e=this.offset[u];e<this.offset[u+1];e++){
        if(!(this.mask[e]&mode))continue;
        const v=this.to[e],p=this.nodes[v];
        let factor=1;
        if(prefer){
          const arc=u*this.nodes.length+v;
          if(!this.bikeways.has(arc))factor=this.offBikewayCost;
          factor+=this.uphill?.get(arc)??0;
        }
        if(trafficHour!==undefined)
          factor=this.traffic.get(u*this.nodes.length+v)?.[trafficHour]??1;
        const rate=timed?this.driveSpeed[e]:1;
        const next=g+factor*distance(this.nodes[u],p)/rate;
        if(seen[v]===generation&&next>=cost[v])continue;
        seen[v]=generation;cost[v]=next;prev[v]=u;queue.push([next+estimateFrom(p),v,next]);
      }
    }
    return null;
  }
}

export const roadMode=mode=>mode==='walk'?WALK:mode==='bike'?BIKE:['car-driver','car-passenger','motorcycle','taxi','ridehail'].includes(mode)?CAR:0;
