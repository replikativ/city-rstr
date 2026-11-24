import {BIKE,CAR,WALK,distance,lngLat} from "./vancouver-network.js";

const MOVEMENT = {
  [WALK]: {top:1.7,acceleration:3,coast:4,brake:7,zoom:18.7,lead:7,eyeHeight:1.65,gaze:18},
  [BIKE]: {top:6,acceleration:2.3,coast:2.2,brake:5,zoom:18.6,lead:13,eyeHeight:1.55,gaze:23},
  [CAR]: {top:13.9,acceleration:3.2,coast:2.3,brake:7,zoom:18.25,lead:20,eyeHeight:1.25,gaze:27}
};
const angularDistance=(from,to)=>((to-from+540)%360+360)%360-180;
const clamp=(n,lo,hi)=>Math.min(hi,Math.max(lo,n));
const radians=degrees=>degrees*Math.PI/180;
const ahead=(point,bearing,metres)=>[point[0]+Math.sin(radians(bearing))*metres,point[1]-Math.cos(radians(bearing))*metres];

export function startPlayer(graph,mode,node,heading,resume,overhead=false,eye=false,look=[]) {
  const state=resume??{mode,graph,node,prev:-1,edge:null,p:graph.nodes[node],heading,turn:0};
  const player={...state,velocity:0,overhead,eye,cameraHeading:state.heading,street:state.edge?.name??"",lookYaw:0,lookPitch:0};
  aimPlayer(player,...look);
  return player;
}

export const eyeLevel=player=>!!player?.eye&&!player.overhead;

export function aimPlayer(player,yaw=0,pitch=0) {
  if(Number.isFinite(yaw))player.lookYaw=clamp(player.lookYaw+yaw,-140,140);
  if(Number.isFinite(pitch))player.lookPitch=clamp(player.lookPitch+pitch,-18,6);
}

export function playerLink(player,url,minute) {
  url.searchParams.set("street",{[WALK]:"walk",[CAR]:"drive",[BIKE]:"bike"}[player.mode]);
  url.searchParams.set("at",[...lngLat(player.p).map(v=>v.toFixed(6)),Math.round(player.heading)].join(","));
  if(player.edge)url.searchParams.set("edge",[player.node,player.edge.next,player.prev,player.turn].join(","));
  else url.searchParams.delete("edge");
  if(player.overhead)url.searchParams.set("camera","overhead");
  else if(player.eye)url.searchParams.set("camera","eye");
  else url.searchParams.delete("camera");
  if(eyeLevel(player)&&(player.lookYaw||player.lookPitch))
    url.searchParams.set("look",[player.lookYaw,player.lookPitch].map(n=>n.toFixed(1)).join(","));
  else url.searchParams.delete("look");
  url.searchParams.set("minute",String(minute));
  return url;
}

function nextEdge(player) {
  const exits=new Map();
  for(const edge of player.graph.exits(player.node,player.mode))
    if(edge.next!==player.prev&&!exits.has(edge.next))exits.set(edge.next,edge);
  if(player.turn&&exits.size>1){
    let chosen=null,score=Infinity;
    for(const edge of exits.values()){
      const angle=angularDistance(player.heading,edge.bearing);
      if(Math.sign(angle)!==Math.sign(player.turn)||Math.abs(angle)<15||Math.abs(angle)>165)continue;
      const error=Math.abs(angle-player.turn);
      if(error<score){score=error;chosen=edge;}
    }
    if(chosen){player.turn=0;return chosen;}
  }
  return player.graph.exit(player.node,player.prev,player.heading,player.mode);
}

function takeEdge(player,edge) {
  player.edge=edge;
  player.heading=edge.bearing;
  player.street=edge.name;
}

export function turnAround(player) {
  const origin=player.edge?.next??player.node;
  const destination=player.edge?player.node:player.prev;
  const reverse=destination<0?player.graph.exit(origin,-1,player.heading+180,player.mode):
    [...player.graph.exits(origin,player.mode)].find(edge=>edge.next===destination);
  if(!reverse||destination<0&&Math.abs(angularDistance(player.heading,reverse.bearing))<120)return false;
  player.node=origin;
  player.turn=0;
  player.velocity=0;
  takeEdge(player,reverse);
  return true;
}

export function stepPlayer(player,seconds,accelerating,braking) {
  const {top,acceleration,coast,brake}=MOVEMENT[player.mode];
  const change=braking?-brake:accelerating?acceleration:-coast;
  const old=player.velocity;
  player.velocity=Math.min(top,Math.max(0,old+change*seconds));
  const accelerationTime=Math.min(seconds,(player.velocity-old)/change);
  let remaining=(old+player.velocity)*accelerationTime/2+player.velocity*(seconds-accelerationTime);
  if(remaining<=0)return false;
  while(remaining>0){
    if(!player.edge){
      const edge=nextEdge(player);
      if(!edge){player.velocity=0;break;}
      takeEdge(player,edge);
    }
    const end=player.graph.nodes[player.edge.next];
    const left=distance(player.p,end);
    if(left<=remaining){
      player.prev=player.node;
      player.node=player.edge.next;
      player.p=end;
      player.edge=null;
      remaining-=left;
    }else{
      const f=remaining/left;
      player.p=[player.p[0]+(end[0]-player.p[0])*f,player.p[1]+(end[1]-player.p[1])*f];
      remaining=0;
    }
  }
  return true;
}

export function playerCamera(player,seconds=1,map,ground=0) {
  player.cameraHeading+=angularDistance(player.cameraHeading,player.heading)*Math.min(1,seconds*7);
  const {zoom,lead,gaze,eyeHeight}=MOVEMENT[player.mode];
  if(eyeLevel(player)&&map){
    const from=lngLat(player.p),bearing=player.cameraHeading+player.lookYaw;
    const eye=ground+eyeHeight;
    const target=eye-gaze*Math.tan(radians(4-player.lookPitch));
    return map.calculateCameraOptionsFromTo(from,eye,lngLat(ahead(player.p,bearing,gaze)),target);
  }
  const center=player.overhead?player.p:ahead(player.p,player.cameraHeading,lead);
  return {center:lngLat(center),zoom:player.overhead?zoom-.6:zoom,pitch:player.overhead?0:72,
    bearing:player.overhead?0:player.cameraHeading};
}

export function streetBodies(actors){
  const features=[];
  for(const [x,y,properties] of actors){
    const {mode,heading=0,scenario,service,surfaceOffset=0}=properties;
    const s=Math.sin(radians(heading)),c=Math.cos(radians(heading));
    function box(width,length,base,height,color){
      const shape=[[-width,-length],[width,-length],[width,length],[-width,length],[-width,-length]];
      const ring=shape.map(([u,v])=>lngLat([x+c*u+s*v,y+s*u-c*v]));
      features.push({type:"Feature",geometry:{type:"Polygon",coordinates:[ring]},
        properties:{...properties,base:base+surfaceOffset,height:height+surfaceOffset,color}});
    }
    if(mode===CAR){
      const body=service==="taxi"?"#e9be68":service==="ridehail"?"#b49ce8":scenario?"#67b5d3":"#b1c4cc";
      box(.88,2.05,.15,1.05,body);
      box(.73,1.08,1.05,1.47,"#405563");
      if(service==="taxi")box(.4,.15,1.47,1.59,"#f7e8af");
    }else{
      const bicycle=mode===BIKE;
      box(.22,bicycle ? .42 : .17,0,bicycle ? 1.46 : 1.39,properties.visitor ? "#83e5d7" : bicycle ? "#d99fdc" : scenario ? "#86cfee" : "#86cbaa");
      box(.13,.13,bicycle ? 1.46 : 1.39,bicycle ? 1.71 : 1.65,"#c8ae96");
    }
  }
  return features;
}

const car=[
  "....ffff....","...fbbbbf...","..fbbbbbbf..","..fllllllf..","..fllllllf..","..fggggggf..",
  ".wfggggggfw.",".wfbbbbbbfw.","..fbbbbbbf..","..fbbbbbbf..","..fbbbbbbf..","..fbbbbbbf..",
  ".wfggggggfw.",".wfggggggfw.","..frbbbbrf..","..ffbbbbff..","...ffffff..."
];
const cycle=[
  "....ff....","...fbbf...","...fbbf...","....ff....","..fffffff.","....bb....",
  "...bbbb...","...fbbf...","...fbbf...","....ff...."
];
const walker=[
  "..fff..",".flllf.",".flllf.","..fff..",".fbbbf.","ffbbbff","..bbb..","..f.f..","..f.f.."
];

export function playerSprite(mode,player) {
  const rows=mode===CAR?car:mode===BIKE?cycle:walker;
  const width=rows[0].length,height=rows.length;
  const body={taxi:[233,190,104,255],ridehail:[180,156,232,255],scenario:[135,209,240,255]};
  const paint={f:[24,32,40,255],b:body[player]??(player?[255,176,77,255]:[183,204,216,255]),
    l:[255,235,176,255],g:[89,123,142,255],r:[228,90,63,255],w:[41,52,59,255]};
  const data=new Uint8Array(width*height*4);
  for(const [y,row] of rows.entries())for(const [x,pixel] of [...row].entries()){
    if(paint[pixel])data.set(paint[pixel],(y*width+x)*4);
  }
  return {width,height,data};
}
