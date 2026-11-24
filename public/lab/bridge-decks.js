import {lngLat} from "./vancouver-network.js";

const arcKey=(a,b)=>`${a[0]},${a[1]}/${b[0]},${b[1]}`;
const bearing=(a,b)=>Math.atan2(b[0]-a[0],a[1]-b[1])*180/Math.PI;
const position=(p,a,b)=>{
  const x=b[0]-a[0],y=b[1]-a[1];
  return Math.max(0,Math.min(1,((p[0]-a[0])*x+(p[1]-a[1])*y)/(x*x+y*y)));
};
const mix=(a,b,f)=>a+(b-a)*f;

export class BridgeDecks {
  constructor(manifest,version){
    this.bridges=manifest.bridges;
    this.version=version;
    this.ways=new Set();this.edges=new Map();
    for(const bridge of this.bridges)for(const {way,vertices,points} of bridge.ways){
      this.ways.add(way);
      for(let i=1;i<vertices.length;i++){
        const low=vertices[i-1],high=vertices[i],a=points[low],b=points[high];
        if(a[0]===b[0]&&a[1]===b[1])continue;
        const edge={bridge,points,low,high};
        this.edges.set(arcKey(a,b),edge);
        this.edges.set(arcKey(b,a),edge);
      }
    }
  }
  surface(point,pair){
    if(!pair?.[0]||!pair[1])return null;
    const edge=this.edges.get(arcKey(...pair));
    if(!edge)return null;
    const {bridge,points,low,high}=edge,a=points[low],b=points[high],fraction=position(point,a,b);
    let lo=low,hi=high;
    while(hi-lo>1){
      const mid=(hi+lo)>>1;
      if(position(points[mid],a,b)<=fraction)lo=mid;else hi=mid;
    }
    const left=position(points[lo],a,b),right=position(points[hi],a,b);
    const f=right>left?(fraction-left)/(right-left):0;
    return {height:mix(points[lo][2],points[hi][2],f),name:bridge.name,heading:bearing(...pair)};
  }
  player(player){
    const {edge,node,prev,graph,p}=player;
    return this.surface(p,edge?[graph.nodes[node],graph.nodes[edge.next]]:[graph.nodes[prev],graph.nodes[node]]);
  }
  route(point,path){
    if(!path||!point)return null;
    for(let i=1;i<path.length;i++){
      const pair=[path[i-1],path[i]],f=position(point,...pair);
      const [a,b]=pair;
      if(!Number.isFinite(f)||Math.hypot(point[0]-mix(a[0],b[0],f),point[1]-mix(a[1],b[1],f))>.01)continue;
      const surface=this.surface(point,pair);
      if(surface)return surface;
    }
    return null;
  }
  sections(path){
    const ground=[],deck=[];
    let flat=[];
    for(let i=1;i<path.length;i++){
      const a=path[i-1],b=path[i],edge=this.edges.get(arcKey(a,b));
      if(edge){
        if(flat.length>1)ground.push(flat);
        flat=[];
        deck.push(edge.points.slice(edge.low,edge.high+1));
      }else{
        if(!flat.length)flat.push(a);
        flat.push(b);
      }
    }
    if(flat.length>1)ground.push(flat);
    return {ground,deck};
  }
}

export async function loadBridgeDecks(root,json,requested){
  let version=requested;
  if(!version){
    const response=await fetch(root+"current.json");
    if(response.status===404)return null;
    if(!response.ok)throw Error("Bridge deck elevations are unavailable.");
    ({version}=await response.json());
  }
  if(!/^[a-f0-9]{20}$/.test(version))throw Error("Invalid bridge deck release.");
  const manifest=await json(root+version+"/decks.json");
  if(manifest.verticalDatum!=="CGVD2013")throw Error("Bridge deck heights use a different vertical datum.");
  return new BridgeDecks(manifest,version);
}

const palette={road:[.22,.28,.31],path:[.44,.49,.46],edge:[.32,.38,.40],rail:[.53,.63,.63],
  tower:[.31,.49,.44],concrete:[.60,.59,.53],stripe:[.84,.77,.55],route:[1,.78,.34]};
const normal=(a,b)=>{const x=b[0]-a[0],y=b[1]-a[1],n=Math.hypot(x,y);return [-y/n,x/n];};
const offset=([x,y,z],[nx,ny],width,lift=0)=>[x+nx*width,y+ny*width,z+lift];

function mesh(bridges,convert,origin,trail=[]){
  const vertices=[];
  const write=(p,paint)=>{
    const {x,y,z}=convert(lngLat(p),p[2]);
    vertices.push(x-origin.x,y-origin.y,z,...paint);
  };
  const quad=(a,b,c,d,paint)=>{for(const p of [a,b,c,a,c,d])write(p,paint);};
  function strip(points,halfWidth,sideShift,color,thickness,lift=0){
    const pairs=points.map((p,i)=>{
      const n=normal(points[i-1]??p,points[i+1]??p);
      return [offset(p,n,sideShift-halfWidth,lift),offset(p,n,sideShift+halfWidth,lift)];
    });
    for(let i=1;i<pairs.length;i++){
      const [a,b]=pairs[i-1],[d,c]=pairs[i];
      quad(a,b,c,d,color);
      if(thickness){
        const below=([x,y,z])=>[x,y,z-thickness];
        quad(a,d,below(d),below(a),palette.edge);
        quad(b,c,below(c),below(b),palette.edge);
      }
    }
  }
  function box(x,y,bottom,top,heading,width,depth,color){
    const sine=Math.sin(heading),cosine=Math.cos(heading);
    const corners=[[-width,-depth],[width,-depth],[width,depth],[-width,depth]].map(([u,v])=>
      [x+u*cosine+v*sine,y+u*sine-v*cosine,top]);
    quad(...corners,color);
    for(let i=0;i<4;i++){
      const a=corners[i],b=corners[(i+1)%4];
      quad(a,b,[b[0],b[1],bottom],[a[0],a[1],bottom],i%2?color:palette.edge);
    }
  }
  for(const bridge of bridges)for(const route of bridge.ways){
    const {points,width,walk}=route;
    strip(points,width/2,0,walk?palette.path:palette.road,walk ? .32 : .8);
    if(walk){
      strip(points,.065,width/2-.08,palette.rail,.38,.94);
      strip(points,.065,.08-width/2,palette.rail,.38,.94);
    }
    if(bridge.id==="lions"&&route.way===4755915){
      strip(points,.065,1.8,palette.stripe,0,.055);
      strip(points,.065,-1.8,palette.stripe,0,.055);
      // Approximate the two suspension towers on the measured deck alignment.
      const [first,last]=[points[0],points.at(-1)],n=normal(first,last);
      const angle=bearing(first,last)*Math.PI/180;
      const towers=[.16,.464].map(f=>points[Math.round((points.length-1)*f)]);
      for(const p of towers){
        const top=111;
        for(const side of [-1,1]){
          const [x,y]=offset(p,n,side*6);
          box(x,y,-2,top,angle,1.1,1.35,palette.tower);
        }
        box(p[0],p[1],top-9,top-6,angle,7,1,palette.tower);
        box(p[0],p[1],p[2]+17,p[2]+19,angle,7,.9,palette.tower);
      }
      const anchor=.59;
      const cable=points.map((p,i)=>{
        const index=i/(points.length-1),lo=.16,hi=.464;
        const z=index<lo?mix(first[2]+3,111,index/lo):index>hi?mix(111,p[2]+3,(index-hi)/(anchor-hi)):
          73+38*((index-(lo+hi)/2)/((hi-lo)/2))**2;
        return [...p.slice(0,2),Math.max(p[2]+3,z)];
      }).slice(0,Math.round(points.length*anchor));
      for(const side of [-1,1]){
        strip(cable,.15,side*6,palette.tower,.23);
        for(let i=12;i<cable.length;i+=8){
          const [x,y,z]=offset(cable[i],n,side*6);
          box(x,y,points[i][2],z,angle,.085,.085,palette.tower);
        }
      }
      for(let i=Math.round(points.length*.62);i<points.length-15;i+=23){
        const [x,y,z]=points[i];box(x,y,-1,z-.55,angle,3.3,1.2,palette.concrete);
      }
    }
    if(bridge.id==="burrard"&&route.way===849900149){
      const [first,last]=[points[0],points.at(-1)],n=normal(first,last),angle=bearing(first,last)*Math.PI/180;
      const a=Math.round(points.length*.25),b=Math.round(points.length*.51);
      for(const i of [a,b]){
        const p=points[i];
        box(p[0],p[1],-1,p[2]-.6,angle,9,1.8,palette.concrete);
        for(const side of [-1,1]){
          const [x,y]=offset(p,n,side*8.7);
          box(x,y,p[2]-.5,p[2]+10.5,angle,1.4,1.8,palette.concrete);
        }
      }
      const beam=points.slice(a,b+1).map(([x,y,z],i)=>[x,y,z+Math.sin(Math.PI*i/(b-a))*8+2.8]);
      for(const side of [-1,1]){
        strip(beam,.22,side*8.3,palette.tower,.3);
        for(let i=3;i<beam.length;i+=5){
          const [x,y,z]=offset(beam[i],n,side*8.3);
          box(x,y,points[a+i][2],z,angle,.15,.17,palette.tower);
        }
      }
    }
    if(!walk&&[1419040127,1419040129,32333986,56864227,1275279652,1059700345].includes(route.way)){
      for(let i=11;i<points.length-6;i+=17){
        const [x,y,z]=points[i],angle=bearing(points[i-1],points[i+1])*Math.PI/180;
        box(x,y,-1,z-.6,angle,Math.min(width*.25,4),1.05,palette.concrete);
      }
    }
  }
  for(const points of trail)strip(points,.30,0,palette.route,0,.095);
  return new Float32Array(vertices);
}

const vertexSource=`#version 300 es
uniform mat4 viewpoint;
in vec3 location;
in vec3 colour;
out vec3 tint;
void main() { tint=colour; gl_Position=viewpoint*vec4(location,1.0); }`;
const fragmentSource=`#version 300 es
precision mediump float;
in vec3 tint;
out vec4 fragment;
void main() { fragment=vec4(tint,1.0); }`;

function compile(gl,type,source){
  const shader=gl.createShader(type);
  gl.shaderSource(shader,source);gl.compileShader(shader);
  if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS)){
    const error=gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);throw Error(error);
  }
  return shader;
}

export function bridgeDeckLayer(decks,maplibre,regional){
  const origin=maplibre.MercatorCoordinate.fromLngLat([-123.12,49.29]);
  const bridges=decks.bridges.filter(({id})=>regional||id!=="ironworkers");
  const convert=(p,z)=>maplibre.MercatorCoordinate.fromLngLat(p,z);
  const triangleData=mesh(bridges,convert,origin);
  let map,program,viewpoint,staticGeometry,routeGeometry,route=[],routeData=null;
  const matrix=new Float32Array(16);
  function geometry(gl){
    const array=gl.createVertexArray(),buffer=gl.createBuffer();
    gl.bindVertexArray(array);gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
    for(const [name,offset] of [["location",0],["colour",12]]){
      const attr=gl.getAttribLocation(program,name);
      gl.enableVertexAttribArray(attr);gl.vertexAttribPointer(attr,3,gl.FLOAT,false,24,offset);
    }
    gl.bindVertexArray(null);
    return {array,buffer,count:0};
  }
  function upload(gl,units,data,usage){
    gl.bindBuffer(gl.ARRAY_BUFFER,units.buffer);gl.bufferData(gl.ARRAY_BUFFER,data,usage);
    units.count=data.length/6;
  }
  function setup(gl){
    const vertex=compile(gl,gl.VERTEX_SHADER,vertexSource),fragment=compile(gl,gl.FRAGMENT_SHADER,fragmentSource);
    program=gl.createProgram();gl.attachShader(program,vertex);gl.attachShader(program,fragment);gl.linkProgram(program);
    gl.deleteShader(vertex);gl.deleteShader(fragment);
    if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));
    staticGeometry=geometry(gl);routeGeometry=geometry(gl);
    upload(gl,staticGeometry,triangleData,gl.STATIC_DRAW);
    routeData=mesh([],convert,origin,route);
    viewpoint=gl.getUniformLocation(program,"viewpoint");
  }
  const reset=()=>{program=null;};
  return {
    id:"bridge-decks",type:"custom",renderingMode:"3d",
    setTrail(segments){
      if(route===segments||!route.length&&!segments.length)return;
      route=segments;
      routeData=mesh([],convert,origin,route);
      map.triggerRepaint();
    },
    onAdd(owner,gl){map=owner;setup(gl);map.on("webglcontextlost",reset);},
    onRemove(owner,gl){
      map.off("webglcontextlost",reset);
      if(program){
        for(const {array,buffer} of [staticGeometry,routeGeometry]){gl.deleteBuffer(buffer);gl.deleteVertexArray(array);}
        gl.deleteProgram(program);
      }
    },
    render(gl,{defaultProjectionData}){
      if(map.getPitch()<15)return;
      if(!program)setup(gl);
      const transform=defaultProjectionData.mainMatrix;
      matrix.set(transform);
      for(let row=0;row<4;row++)matrix[12+row]=transform[12+row]+transform[row]*origin.x+transform[4+row]*origin.y;
      gl.useProgram(program);gl.uniformMatrix4fv(viewpoint,false,matrix);
      gl.depthMask(true);gl.disable(gl.CULL_FACE);
      if(routeData){upload(gl,routeGeometry,routeData,gl.DYNAMIC_DRAW);routeData=null;}
      for(const {array,count} of [staticGeometry,routeGeometry])if(count){
        gl.bindVertexArray(array);gl.drawArrays(gl.TRIANGLES,0,count);
      }
      gl.bindVertexArray(null);
    }
  };
}
