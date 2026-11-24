import {lngLat} from "./vancouver-network.js";

const release=/^[a-f0-9]{20}$/;

export async function loadBuildingHeights(root,streets,requested,json){
  let version=requested==="tags"?null:requested;
  if(!version){
    const response=await fetch(root+streets+".json");
    if(response.status===404)return null;
    if(!response.ok)throw Error("Building height data is unavailable.");
    ({version}=await response.json());
  }
  if(!release.test(version))throw Error("Unknown building height release.");
  const path=root+version+"/",report=await json(path+"report.json");
  if(report.schema!==1||report.streets!==streets)throw Error("Building heights use a different street map.");
  const roofSections=report.roofSections?.coordinateSpace==="city-grid"?report.roofSections:null;
  const keys=new Set(report.tiles),sections=new Set(roofSections?.tiles),tiles=new Map();
  const load=name=>{
    if(!tiles.has(name))tiles.set(name,json(path+name+".json").catch(error=>{tiles.delete(name);throw error;}));
    return tiles.get(name);
  };
  return {version,report,roofSections,enabled:requested!=="tags",
    tile:key=>keys.has(key)?load(key):null,
    sectionTile:key=>sections.has(key)?load("sections-"+key):null};
}

export function buildingProperties(height,basis,detail,estimate,year){
  if(!estimate)return {height,basis,name:detail?.name??""};
  const [,metres,pixels,spread]=estimate;
  return {height:metres,basis:"lidar",name:detail?.name??"",year,pixels,spread};
}

export function sectionFeatures(id,detail,parts,year){
  return parts.map(([height,coordinates],index)=>({
    type:"Feature",id:id+"/"+index,
    geometry:{type:"MultiPolygon",coordinates:coordinates.map(polygon=>polygon.map(ring=>ring.map(lngLat)))},
    properties:{height,basis:"lidar",year,building:id,roofSection:true,name:detail?.name??""}
  }));
}
