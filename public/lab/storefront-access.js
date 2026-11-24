import {distance,lngLat,WALK} from "./vancouver-network.js";

export const storefrontInteractionMetres=25;
const frontageLimit=80;
const grid=160;

const streetTypes={avenue:"av",ave:"av",street:"st",boulevard:"blvd",drive:"dr",road:"rd",court:"ct",
  crescent:"cres",place:"pl",lane:"ln",terrace:"terr",mall:"mall",highway:"hwy",parkway:"pkwy"};
const directions={north:"n",south:"s",east:"e",west:"w"};

export function streetName(name){
  return String(name??"").normalize("NFKD").replace(/\p{Diacritic}/gu,"").toLowerCase().replace(/[.’']/g,"")
    .trim().split(/\s+/).map(word=>directions[word]??streetTypes[word]??word).join(" ");
}

export function addressStreets(address){
  return new Set(address.split(" / ").flatMap(value=>{
    const match=/^\s*\d+[a-z]?(?:\s*-\s*\d+[a-z]?)?\s+(.+)$/i.exec(value);
    return match?[streetName(match[1])]:[];
  }));
}

export class StorefrontAccess {
  constructor(sites){
    this.sites=new Map(sites.map(site=>[site.id,site]));
    this.streets=new Map(sites.map(site=>[site.id,addressStreets(site.name)]));
    this.byGraph=new WeakMap();
    this.grid=new Map();
    for(const site of sites){
      const key=site.point.map(value=>Math.floor(value/grid)).join("/");
      if(!this.grid.has(key))this.grid.set(key,[]);
      this.grid.get(key).push(site);
    }
  }

  locate(site,graph,mode=WALK){
    if(!site||!graph||!this.sites.has(site.id))return null;
    if(!this.byGraph.has(graph))this.byGraph.set(graph,new Map());
    const cache=this.byGraph.get(graph),key=mode+"/"+site.id;
    if(!cache.has(key)){
      const names=this.streets.get(site.id);
      const segment=names.size?graph.streetStart(site.point,mode,0,{maxDistance:frontageLimit,
        accepts:name=>names.has(streetName(name))}):null;
      cache.set(key,segment);
    }
    return cache.get(key);
  }

  nearby({p,graph,mode},radius=150){
    const margin=radius+frontageLimit,found=[];
    const [x0,y0]=p.map(value=>Math.floor((value-margin)/grid));
    const [x1,y1]=p.map(value=>Math.floor((value+margin)/grid));
    for(let x=x0;x<=x1;x++)for(let y=y0;y<=y1;y++)for(const site of this.grid.get(x+"/"+y)??[]){
      if(distance(site.point,p)>margin)continue;
      const access=this.locate(site,graph,mode);
      if(!access)continue;
      const metres=distance(access.p,p);
      if(metres<=radius)found.push({site,access,metres});
    }
    return found.sort((a,b)=>a.metres-b.metres||a.site.id.localeCompare(b.site.id));
  }
}

export function atStorefront(player,access,limit=storefrontInteractionMetres){
  if(!player||!access||player.graph!==access.graph||distance(player.p,access.p)>limit)return false;
  const ends=state=>[state.node,state.edge?.next].filter(Number.isInteger);
  const from=ends(player),to=ends(access);
  if(from.length===2&&from.every(node=>to.includes(node)))return true;
  // Follow a few metres of actual graph connectivity when the player and
  // frontage occupy different segments. This excludes nearby overpasses.
  const {graph,mode}=player,cost=new Map(),targets=new Map(to.map(node=>[node,distance(graph.nodes[node],access.p)]));
  const queue=from.map(node=>[node,distance(graph.nodes[node],player.p)]);
  for(const [node,metres] of queue){
    if(metres>limit||metres>=(cost.get(node)??Infinity))continue;
    cost.set(node,metres);
    if(metres+(targets.get(node)??Infinity)<=limit)return true;
    for(const {next} of graph.exits(node,mode)){
      const total=metres+distance(graph.nodes[node],graph.nodes[next]);
      if(total<=limit&&total<(cost.get(next)??Infinity))queue.push([next,total]);
    }
  }
  return false;
}

export function storefrontSign({site,access},state){
  const [x,y]=access.p;
  const offset=distance(access.p,site.point),[dx,dy]=[site.point[0]-x,site.point[1]-y];
  const side=offset?[dx/offset,dy/offset]:[1,0];
  const centre=[x+side[0]*Math.min(2,offset),y+side[1]*Math.min(2,offset)];
  const color=state==="open"?"#80d9ae":state==="selected"?"#ffe49b":"#d8bbec";
  function shape(width,length,base,height,color){
    const ring=[[-width,-length],[width,-length],[width,length],[-width,length],[-width,-length]]
      .map(([a,b])=>lngLat([centre[0]-side[1]*a+side[0]*b,centre[1]+side[0]*a+side[1]*b]));
    return {type:"Feature",geometry:{type:"Polygon",coordinates:[ring]},properties:{id:site.id,base,height,color}};
  }
  return [shape(.09,.09,0,1.75,"#33474c"),shape(.62,.10,1.3,2.1,color)];
}
