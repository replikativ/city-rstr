// Local east/south metres. The graph stores separate bits for each vehicle direction.
export const xy = ([lon,lat]) => [(lon+123.1)*72600,(49.26-lat)*111195];
export const lngLat = ([x,y]) => [x/72600-123.1,49.26-y/111195];
export const distance = (a,b) => Math.hypot(b[0]-a[0],b[1]-a[1]);
export const departureHour = minute => ((Math.floor(minute/60)%24)+24)%24;
export const WALK=1, CAR=2;
export const BIKE=4;
const metroGraphs=new Map();

export function metroRoadNetwork(root,version,json){
  const folder=root+"commuter-drive/"+version+"/";
  if(!metroGraphs.has(folder))metroGraphs.set(folder,Promise.all([json(folder+"network.json"),json(folder+"profile.json")])
    .then(([network,profile])=>new Network(network,null,profile)).catch(error=>{metroGraphs.delete(folder);throw error;}));
  return metroGraphs.get(folder);
}

function segmentPoint(point,a,b){
  const dx=b[0]-a[0],dy=b[1]-a[1];
  const f=Math.min(1,Math.max(0,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy)));
  return [a[0]+f*dx,a[1]+f*dy];
}

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
  constructor({nodes,ways,names},bikeways=null,driving=null){
    this.nodes=nodes;this.names=names;
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
      for(const [way,[bits,name,ids]] of ways.entries()){
        for(let i=1;i<ids.length;i++){
          const a=ids[i-1],b=ids[i];
          if(a===b || distance(nodes[a],nodes[b])===0)continue;
          const forward=(bits&3)|((bits&8)>>1),reverse=(bits&1)|((bits&4)>>1)|((bits&16)>>2);
          if(forward)callback(a,b,forward,name,way,0);
          if(reverse)callback(b,a,reverse,name,way,1);
        }
      }
    };
    each(a=>degree[a]++);
    const offset=new Uint32Array(nodes.length+1);
    for(let i=0;i<nodes.length;i++)offset[i+1]=offset[i]+degree[i];
    this.offset=offset;const size=offset[nodes.length];
    this.to=new Uint32Array(size);this.mask=new Uint8Array(size);this.street=new Uint32Array(size);
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
    each((a,b,bits,name,way,direction)=>{
      const i=cursor[a]++;this.to[i]=b;this.mask[i]=bits;this.street[i]=name;allowed[a]|=bits;
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
  *exits(node,mode){
    for(let e=this.offset[node];e<this.offset[node+1];e++){
      const next=this.to[e];if(!(this.mask[e]&mode))continue;
      const p=this.nodes[node],q=this.nodes[next],bearing=Math.atan2(q[0]-p[0],p[1]-q[1])*180/Math.PI;
      yield {next,bearing,name:this.names[this.street[e]]};
    }
  }
  streetStart(point,mode,heading,{accepts,maxDistance=Infinity}={}){
    const nearest=this.snap(point,mode);
    if(nearest<0)return null;
    const [x,y]=point.map(p=>Math.floor(p/120));
    const nodes=new Set([nearest]);
    for(let a=x-2;a<=x+2;a++)for(let b=y-2;b<=y+2;b++)
      for(const node of this.cells.get(a+","+b)??[])nodes.add(node);
    let best=null,bestDistance=maxDistance,bestTurn=Infinity;
    for(const node of nodes){
      const origin=this.nodes[node];
      for(const edge of this.exits(node,mode)){
        if(accepts&&!accepts(edge.name))continue;
        const end=this.nodes[edge.next],p=segmentPoint(point,origin,end);
        const metres=distance(point,p);
        const turn=Math.abs(((edge.bearing-heading+180)%360+360)%360-180);
        if(metres>bestDistance+1e-6||(Math.abs(metres-bestDistance)<=1e-6&&turn>=bestTurn))continue;
        best={mode,graph:this,node,prev:-1,edge,p,heading:edge.bearing,turn:0};
        bestDistance=metres;bestTurn=turn;
      }
    }
    return best;
  }
  exit(node,previous,heading,mode){
    let best=null,difference=Infinity;
    for(const edge of this.exits(node,mode)){
      const delta=Math.abs(((edge.bearing-heading+540)%360+360)%360-180)+(edge.next===previous?360:0);
      if(delta<difference){difference=delta;best=edge;}
    }
    return best;
  }
  resumeEdge(p,mode,record){
    const [node,next,prev,turn]=record;
    if(record.length!==4||!record.every(Number.isInteger)||!this.nodes[node]||!this.nodes[next]||
       (prev!==-1&&!this.nodes[prev])||![-90,0,90].includes(turn))return null;
    const a=this.nodes[node],b=this.nodes[next];
    for(let e=this.offset[node];e<this.offset[node+1];e++){
      if(!(this.mask[e]&mode)||this.to[e]!==next)continue;
      const dx=b[0]-a[0],dy=b[1]-a[1],position=segmentPoint(p,a,b);
      if(distance(position,p)>1)return null;
      const heading=Math.atan2(dx,-dy)*180/Math.PI;
      return {mode,graph:this,node,prev,edge:{next,bearing:heading,name:this.names[this.street[e]]},p:position,heading,turn};
    }
    return null;
  }
}

// Reuse a directed shortest-time search when comparing several vehicles for
// the same curb. The frontier can continue if a later offer allows more time.
export function driveTimesTo(graph){
  const {nodes,offset,to,mask,driveSpeed}=graph;
  if(!driveSpeed)throw Error("A drive-time search requires a driving profile.");
  const incoming=new Uint32Array(nodes.length+1);
  for(let edge=0;edge<to.length;edge++)if(mask[edge]&CAR)incoming[to[edge]+1]++;
  for(let node=1;node<incoming.length;node++)incoming[node]+=incoming[node-1];
  const cursor=incoming.slice(),from=new Uint32Array(incoming.at(-1)),weights=new Float64Array(from.length);
  for(let node=0;node<nodes.length;node++)for(let edge=offset[node];edge<offset[node+1];edge++){
    if(!(mask[edge]&CAR))continue;
    const target=to[edge],i=cursor[target]++;
    from[i]=node;
    weights[i]=distance(nodes[node],nodes[target])/driveSpeed[edge];
  }

  const seen=new Uint32Array(nodes.length),settled=new Uint32Array(nodes.length),cost=new Float64Array(nodes.length);
  let generation=0,goal=-1,queue;
  return (start,target,limit)=>{
    if(start===target)return 0;
    if(target!==goal){
      goal=target;generation++;
      queue=new MinHeap();
      seen[target]=generation;cost[target]=0;
      queue.push([0,target]);
    }
    while(settled[start]!==generation&&queue.data.length&&queue.data[0][0]<=limit){
      const [minutes,node]=queue.pop();
      if(minutes!==cost[node])continue;
      settled[node]=generation;
      for(let edge=incoming[node];edge<incoming[node+1];edge++){
        const other=from[edge],next=minutes+weights[edge];
        if(seen[other]===generation&&next>=cost[other])continue;
        seen[other]=generation;cost[other]=next;
        queue.push([next,other]);
      }
    }
    return settled[start]===generation&&cost[start]<=limit?cost[start]:Infinity;
  };
}
export const roadMode=mode=>mode==='walk'?WALK:mode==='bike'?BIKE:['car-driver','car-passenger','motorcycle','taxi','ridehail'].includes(mode)?CAR:0;
export function positionOnSegment(points,fraction){
  const lengths=points.slice(1).map((p,i)=>distance(p,points[i]));
  let left=lengths.reduce((a,b)=>a+b,0)*Math.max(0,Math.min(1,fraction));
  for(let i=0;i<lengths.length;i++){
    if(left<=lengths[i] && lengths[i]>0){
      const f=left/lengths[i],a=points[i],b=points[i+1];
      return {point:[a[0]+f*(b[0]-a[0]),a[1]+f*(b[1]-a[1])],segment:[a,b]};
    }
    left-=lengths[i];
  }
  return {point:points.at(-1),segment:null};
}
export const positionOn=(points,fraction)=>positionOnSegment(points,fraction).point;
