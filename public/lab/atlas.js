import {archivedRun} from "./market-release.js";
import {cad,housingRelease} from "./housing-data.js";
import {coverageControl,coverageParams,regional,regionalRelease,publishedWeekday,scopeName} from "./coverage.js";
const el=id=>document.getElementById(id);
const fmt=n=>n==null?"unavailable":n.toLocaleString();
const pct=(a,b)=>b ? (100*a/b).toFixed(1)+"%" : "—";
const human=s=>s.replaceAll("-"," ");
const clock=t=>String(Math.floor(t/60)%24).padStart(2,"0")+":"+String(Math.floor(t)%60).padStart(2,"0")+(t>=1440?" +1":"");
const svgNS="http://www.w3.org/2000/svg";
const params=new URLSearchParams(location.search);
let clockRun,atlas,base,area="",da="",rosterDA="",roster=null,personIndex=0,houseIndex=-1;
let minute=480,timer=null,request=0;
let overview,validation,validationRequest;
let housingRequest,housing,assessmentReport;
const housingRosters=new Map();
const housingMaps={dwelling:{title:"Mean owner dwelling value",field:"ownerValue",low:500000,high:5000000},
  shelter:{title:"Mean monthly tenant shelter cost",field:"tenantShelter",low:800,high:2500}};
const paths=new Map();
function options(select,values,blank) {
  select.replaceChildren();
  if (blank) select.add(new Option(blank,""));
  values.forEach(x=>select.add(new Option(x,x)));
}
async function json(url) {
  const res=await fetch(url);
  if (!res.ok) throw Error("Unable to load "+url);
  return res.json();
}
function project([lon,lat]) {
  return [Math.round((lon+123.1)*72600), Math.round((49.26-lat)*111195)];
}
function linePath(points) {return "M"+points.map(project).join("L");}
function polygonPath(geom) {
  const polygons=geom.type==="Polygon" ? [geom.coordinates] : geom.coordinates;
  return polygons.flatMap(poly=>poly.map(ring=>linePath(ring)+"Z")).join("");
}
function element(tag,attributes) {
  const node=document.createElementNS(svgNS,tag);
  for (const [key,value] of Object.entries(attributes)) node.setAttribute(key,value);
  return node;
}
function regionMap(map,parks) {
  const svg=el("atlas-map");
  const [w,s,e,n]=map.frame, [x,y]=project([w,n]), [right,bottom]=project([e,s]);
  overview=[x,y,right-x,bottom-y];
  const land=polygonPath(map.land);
  const defs=element("defs",{}),clip=element("clipPath",{id:"atlas-land-mask"});
  clip.append(element("path",{d:land,"clip-rule":"evenodd"}));defs.append(clip);
  svg.append(defs,element("path",{id:"atlas-land",d:land,"fill-rule":"evenodd"}));
  const areas=element("g",{id:"atlas-areas","clip-path":"url(#atlas-land-mask)"});
  for (const [name,a] of Object.entries(atlas.areas)) {
    const node=element("path",{d:polygonPath(a.geometry),role:"button",tabindex:0,"aria-label":name,"fill-rule":"evenodd"});
    node.append(element("title",{}));
    node.onclick=()=>selectArea(name);
    node.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();selectArea(name);}};
    paths.set(name,node);areas.append(node);
  }
  svg.append(areas);
  const green=element("g",{"clip-path":"url(#atlas-land-mask)","aria-hidden":"true"});
  for(const feature of parks.features){
    green.append(element("path",{class:"atlas-park",d:polygonPath(feature.geometry),"fill-rule":"evenodd"}));
  }
  svg.append(green);
  for(const [kind,lines] of Object.entries(map.roads)) {
    svg.append(element("path",{class:"atlas-road "+kind,d:lines.map(linePath).join("")}));
  }
  // Anchor labels on the landmark or occupied land rather than the bounding box of a water-spanning polygon.
  const places=[
    ["Stanley Park",-123.145,49.302,"context"],["UBC",-123.246,49.261,"context"],
    ["North Vancouver",-123.085,49.323,"context"],["Richmond",-123.095,49.188,"context"],["Burnaby",-123.015,49.255,"context"],
    ["Burrard Inlet",-123.082,49.307,"water"],["English Bay",-123.197,49.285,"water"],
    ["False Creek",-123.118,49.2725,"water"],["Fraser River",-123.145,49.2035,"water"],
    ["Downtown",-123.114,49.282,"local"],["Kitsilano",-123.165,49.263,"local"],
    ["Mount Pleasant",-123.092,49.260,"local"],["Hastings-Sunrise",-123.043,49.280,"local"],
    ["Kerrisdale",-123.158,49.225,"local"],["Sunset",-123.091,49.218,"local"],
    ["Queen Elizabeth Park",-123.112,49.241,"context"],["Granville Island",-123.134,49.270,"detail"],
    ["Main St",-123.101,49.249,"road-name"],["W Broadway",-123.146,49.264,"road-name"],
    ["Kingsway",-123.069,49.246,"road-name"],["Cambie St",-123.116,49.232,"road-name"]
  ];
  if(regional)places.push(["West Vancouver",-123.198,49.354,"local"],["Lynn Valley",-123.034,49.344,"local"],
    ["Horseshoe Bay",-123.274,49.375,"local"],["Deep Cove",-122.948,49.327,"local"]);
  for(const [name,lon,lat,kind] of places) {
    const [lx,ly]=project([lon,lat]),label=element("text",{x:lx,y:ly,class:kind,"aria-hidden":"true"});
    label.textContent=name;svg.append(label);
  }
  svg.append(element("g",{class:"scale","aria-hidden":"true"}));
  setMapView(overview);
}
function setMapView(box) {
  const svg=el("atlas-map"),[x,y,w,h]=box,f=w/overview[2];
  svg.setAttribute("viewBox",box.join(" "));
  svg.querySelectorAll("text").forEach(node=>{
    node.style.fontSize=(335*f)+"px";node.style.strokeWidth=(48*f)+"px";
    node.style.display=f>.7 && ["road-name","detail"].includes(node.getAttribute("class"))?"none":"";
  });
  const distance=w>12000?2000:w>4000?1000:w>1600?500:100;
  const left=x+w*.035, top=y+h*.96,scale=svg.querySelector(".scale");
  const ruler=element("line",{x1:left,y1:top,x2:left+distance,y2:top,"stroke-width":32*f});
  const label=element("text",{x:left+distance/2,y:top-120*f});
  label.style.fontSize=(290*f)+"px";label.style.strokeWidth=(38*f)+"px";
  label.textContent=distance>=1000?(distance/1000)+" km":distance+" m";
  scale.replaceChildren(ruler,label);
  el("zoom-city").disabled=box===overview;
}
function zoomSelection(){
  const shape=da?el("selected-da"):paths.get(area);
  if(!shape)return;
  const b=shape.getBBox(),ratio=overview[2]/overview[3];
  const w=Math.max(b.width,b.height*ratio,800)*1.3,h=w/ratio;
  setMapView([b.x+b.width/2-w/2,b.y+b.height/2-h/2,w,h]);
}
const scope=()=>da?atlas.das[da]:area?atlas.areas[area]:atlas.city;
function heldOutDifferences() {
  const ids = da ? [da] : area ? atlas.areas[area].das : Object.keys(atlas.das);
  const errors = [];
  for (const id of ids) for (const i of atlas.heldout) {
    const [m,d,c,t]=atlas.das[id].fit[i];
    if (d && t) errors.push({id,i,delta:100*(m/d-c/t)});
  }
  const host=el("errors");host.replaceChildren();
  for (const {id,i,delta} of errors.sort((a,b)=>Math.abs(b.delta)-Math.abs(a.delta)).slice(0,5)){
    const button=document.createElement("button");
    button.textContent=id+" · "+atlas.labels[i]+" · "+delta.toFixed(1)+" pp";
    button.onclick=()=>selectArea(Object.keys(atlas.areas).find(n=>atlas.areas[n].das.includes(id)),id);
    host.append(button);
  }
  if (!errors.length) host.textContent="The census has no comparable published denominator here.";
}
function validatePopulation(){
  if(!validation)return;
  const key=el("validation-measure").value;
  const group=da?validation.das[da]:area?validation.areas[area]:validation.all;
  if(el("housing").open){
    const {ownerValue,mortgaged,tenantCost,rentBurden}=group.housing;
    const dollars=n=>"$"+fmt(Math.round(n));
    el("housing-context").textContent=ownerValue?"Average owner-estimated home value "+dollars(ownerValue[1])+
      " across "+fmt(ownerValue[0])+" owner households with published data."+(mortgaged?" "+mortgaged[1].toFixed(1)+"% of owners have a mortgage.":""):
      "No published owner value in this selection.";
    el("housing-tenants").textContent=tenantCost?"Average monthly shelter cost "+dollars(tenantCost[1])+
      " across "+fmt(tenantCost[0])+" tenant households with published data."+(rentBurden?" "+rentBurden[1].toFixed(1)+"% spend at least 30% of income on shelter.":""):
      "No published tenant costs in this selection.";
  }
  if(!el("validation").open)return;
  const result=group[key],body=el("validation-rows");
  body.replaceChildren();
  el("validation-universe").textContent="";el("validation-coverage").textContent="";
  if(!result){
    el("validation-result").textContent="The census has no comparable published distribution for this selection.";
    return;
  }
  const {model,census,denominator,missing,covered,total,direct}=result;
  const n=model.reduce((a,b)=>a+b,0),pooled=validation.pooled[key];
  const meanGap=shares=>shares.reduce((err,v,i)=>err+Math.abs(v-census[i]/denominator),0)*100/shares.length;
  el("validation-result").textContent=n?"Average absolute gap across categories · model "+
    meanGap(model.map(v=>v/n)).toFixed(1)+" percentage points · metro donors "+meanGap(pooled).toFixed(1)+".":
    "No synthetic records with a known value in this census universe.";
  for(const [i,label] of validation.labels[key].entries()){
    const row=body.insertRow();
    for(const value of [label,pct(model[i],n),pct(census[i],denominator),pct(pooled[i],1)])row.insertCell().textContent=value;
  }
  el("validation-universe").textContent=key==="income"?
    fmt(n)+" private households have complete 2020 before-tax income. Income is unresolved for "+fmt(missing)+". The census covers "+fmt(denominator)+" households.":
    fmt(n)+" private-household residents with a reported usual commute mode. The census covers "+fmt(denominator)+
    " employed residents aged 15+ with a usual workplace or no fixed workplace, from the 25% sample.";
  el("validation-coverage").textContent=direct?"The census publishes these counts directly for the municipality.":
    fmt(covered)+" of "+fmt(total)+" dissemination areas contribute comparable published counts. Rounding can make census shares sum to a value other than 100%.";
}

function renderHousing(){
  renderAssessments();
  if(!housing||!el("housing").open)return;
  const report=housing.report,group=da?report.das[da]:area?report.areas[area]:report.all;
  const rows=el("housing-model-rows");rows.replaceChildren();
  for(const [key,label] of [["ownerShelter","Owner shelter / month"],["tenantShelter","Tenant shelter / month"],
    ["ownerValue","Owner dwelling value"]]){
    const value=group?.[key];
    if(value){
      const row=rows.insertRow();
      for(const cell of [label,fmt(value.count),cad.format(value.mean),cad.format(value.median)])row.insertCell().textContent=cell;
    }
  }
  el("housing-model").hidden=!rows.rows.length;
  const check=el("housing-median-check");
  check.textContent=area||da?"":"Citywide, the Census reports a median owner dwelling value of "+
    cad.format(report.census.ownerValue.median)+" and median monthly tenant shelter costs of "+
    cad.format(report.census.tenantShelter.median)+".";
}

function renderAssessments(){
  if(!assessmentReport||!el("property-assessments").open)return;
  const {year,city,areas,definitions,coverage,levyMatch}=assessmentReport;
  const group=area?areas[area]:city;
  el("assessment-scope").textContent=(area||"City of Vancouver")+" · "+year+" assessment roll";
  const rows=el("assessment-rows");rows.replaceChildren();
  for(const [category,label] of Object.entries(definitions)){
    const value=group?.[category];
    if(!value)continue;
    const row=rows.insertRow();
    for(const cell of [label,fmt(value.count),cad.format(value.median),value.quartiles.map(n=>cad.format(n)).join("–")])
      row.insertCell().textContent=cell;
  }
  const included=Object.values(city).reduce((n,x)=>n+x.count,0);
  el("assessment-coverage").textContent=(rows.rows.length?"":"No records matched this neighbourhood. ")+
    "Current parcel points locate "+fmt(coverage.mapped)+" of "+fmt(included)+" eligible citywide roll records in a neighbourhood.";
  el("assessment-levy").hidden=!levyMatch;
}

async function renderHouseholdCosts(){
  if(!el("household-costs").open||houseIndex<0)return;
  const output=el("household-cost-estimate"),id=rosterDA,index=houseIndex;
  output.textContent="Loading household estimate…";
  try{
    const release=await housingRequest();
    if(!release)return;
    if(!housingRosters.has(id))housingRosters.set(id,json(release.base+id+".json").catch(error=>{
      housingRosters.delete(id);throw error;
    }));
    const records=await housingRosters.get(id);
    if(id!==rosterDA||index!==houseIndex||!roster)return;
    if(records.length!==roster.homes.length||records[index][0]!==roster.homes[index][2])
      throw Error("Housing estimates use a different household roster.");
    const [,shelter,afterTax,value,mortgage]=records[index];
    const parts=[shelter==null?"Shelter cost unavailable":cad.format(shelter)+" monthly shelter cost",
      afterTax==null?"After-tax income unavailable":cad.format(afterTax)+" annual after-tax income"];
    if(value!=null)parts.push(cad.format(value)+" estimated dwelling value");
    if(mortgage!=null)parts.push(mortgage?"Mortgage present":"No mortgage");
    output.textContent=parts.join(" · ") + ". Synthetic household estimate.";
  }catch(error){if(id===rosterDA&&index===houseIndex)output.textContent=error.message;}
}
function fit() {
  const s=scope(),body=el("fit").tBodies[0];body.replaceChildren();
  el("scope").textContent=da?area+" · "+da:area||scopeName;
  el("pop").textContent=fmt(s.population);el("homes").textContent=fmt(s.homes);
  el("reconcile").textContent=fmt(s.population)+" census residents. "+(regional?"":fmt(s.legacy)+" in the early roster. ")+
    fmt(s.private)+" residents have synthetic private households. "+fmt(s.unresolved)+" have unresolved household membership. The rounded census private-household person count is "+fmt(s.rawPrivate)+". Age is masked for "+fmt(s.unknownAge)+" synthetic residents.";
  heldOutDifferences();validatePopulation();
  s.fit.forEach(([m,d,c,t,covered],i)=>{
    const row=body.insertRow();
    if(atlas.heldout.includes(i)) row.classList.add("held");
    const gap=d&&t?(100*m/d-100*c/t).toFixed(1):"—";
    const label=atlas.labels[i]+(atlas.heldout.includes(i)?" (held out)":"");
    [label,pct(m,d),pct(c,t),gap].forEach(v=>row.insertCell().textContent=v);
    row.title=covered+" DA(s) with a published denominator. Model "+m+"/"+d+" · Census "+c+"/"+t;
  });
}
function episode(day) {
  // All chains cover 04:00–04:00 contiguously.
  return day.episodes.find(([start,dur])=>minute>=start && minute<start+dur);
}
function mapColours(acts){
  const view=housingMaps[el("atlas-layer").value];
  for(const [key,node] of paths){
    const a=atlas.areas[key];
    let fraction,description;
    if(view){
      const value=housing.report.areas[key]?.[view.field]?.mean;
      fraction=value==null?0:Math.max(0,Math.min(1,(value-view.low)/(view.high-view.low)));
      description=value==null?"estimate unavailable":"mean "+cad.format(value);
    }else{
      const n=Object.entries(a.days).reduce((v,[t,count])=>v+(acts[t]==="paid-work"?count:0),0);
      fraction=Math.min(1,2*n/a.population);
      description=fmt(n)+" at paid work ("+pct(n,a.population)+")";
    }
    node.setAttribute("fill","rgb("+[38+104*fraction,68+145*fraction,82+79*fraction].map(Math.round).join(",")+")");
    node.setAttribute("aria-pressed",String(key===area));
    node.setAttribute("aria-description",description);
    node.firstChild.textContent=key+" · "+description;
  }
}
function changeMap(){
  const view=housingMaps[el("atlas-layer").value],title=view?.title??"Residents at paid work";
  el("map-heading").textContent=title;
  el("atlas-map").setAttribute("aria-label",title+" by home neighbourhood");
  el("map-time").hidden=!!view;
  el("atlas-scale-low").textContent=view?cad.format(view.low)+" or less":"0%";
  el("atlas-scale-high").textContent=view?cad.format(view.high)+"+":"50%+";
  const url=new URL(location.href);
  if(view)url.searchParams.set("map",el("atlas-layer").value);else url.searchParams.delete("map");
  history.replaceState(null,"",url);syncTime();
}
function syncTime() {
  el("minute").value=Math.floor(minute);el("time").textContent=el("map-time").textContent=clock(minute);
  const acts=atlas.templates.map(t=>episode(t)[2]);
  mapColours(acts);
  const s=scope(),counts=new Map();
  Object.entries(s.days).forEach(([t,n])=>counts.set(acts[t],(counts.get(acts[t])||0)+n));
  const best=[...counts].sort((a,b)=>b[1]-a[1]).slice(0,5);
  const rest=s.population-best.reduce((v,[,n])=>v+n,0);
  if(rest) best.push(["other activities",rest]);
  const host=el("activity");host.replaceChildren();
  for(const [label,n] of best){
    const row=document.createElement("div");row.className="activity";
    const a=document.createElement("span"),bar=document.createElement("i"),v=document.createElement("span");
    a.textContent=human(label);bar.style.width=pct(n,s.population);v.textContent=fmt(n);
    row.append(a,bar,v);host.append(row);
  }
  now();
}
function mapClock(dayParams){
  if(clockRun?.kind==="work-transit-flex"){
    dayParams.delete("clock");
    dayParams.set("workTransit",clockRun.version);
    dayParams.set("workplaceRun",clockRun.workplaceRun);
    if(params.has("outingsRun"))dayParams.set("outingsRun",params.get("outingsRun"));
  }else if(clockRun?.kind==="spread-departures"){
    dayParams.set("departureClock",clockRun.version);
    for(const key of ["workplaceRun","workplaceBasis"])if(params.has(key))dayParams.set(key,params.get(key));
  }else if(clockRun)dayParams.set("clock",clockRun.version);
  if(clockRun?.kind==="scheduled-transit")dayParams.set("scheduled","1");
  if(params.has("recreationRun")||params.has("recreation"))for(const key of ["recreationRun","recreation","workplaceRun"])
    if(params.has(key))dayParams.set(key,params.get(key));
  if(params.has("schoolRun"))for(const key of ["schoolRun","workplaceRun","walks"])
    if(params.has(key))dayParams.set(key,params.get(key));
  if(params.has("attendanceRun"))for(const key of ["attendanceRun","workplaceRun","walks","outingsRun"])
    if(params.has(key))dayParams.set(key,params.get(key));
  if(params.has("easternOutingRun"))for(const key of ["easternOutingRun","workplaceRun"])
    if(params.has(key))dayParams.set(key,params.get(key));
  if(params.has("personalTransit"))for(const key of ["personalTransit","workplaceRun","follow"])
    if(params.has(key))dayParams.set(key,params.get(key));
  if(params.has("votingRun"))for(const key of ["votingRun","votingLayout","votingSite"])
    if(params.has(key))dayParams.set(key,params.get(key));
}
function now(){
  if(!roster)return;
  const dayParams=new URLSearchParams({...coverageParams,da:rosterDA,person:personIndex+1,minute});
  if(params.has("marketRun"))dayParams.set("marketRun",params.get("marketRun"));
  for(const key of ["basket","grocery","shopCheck"])if(params.has(key))dayParams.set(key,params.get(key));
  mapClock(dayParams);
  if(!regional)for(const key of ["crossing","crossingRun","cycleCheck","bikeRoutes","localWalk","cycleTours","tourZone","tourPurpose","follow","walks","service","transitWalks","riderRun"])
    if(params.has(key))dayParams.set(key,params.get(key));
  if(!regional&&params.get("workplaces")==="census")dayParams.set("workplaces","census");
  if(dayParams.has("workplaces")&&["usual","local","sites","tracts"].includes(params.get("commute")))dayParams.set("commute",params.get("commute"));
  if(!regional&&params.has("shop")){
    dayParams.set("shop",params.get("shop"));dayParams.set("hours",params.get("hours")??"full");
    for(const key of ["shopPlay","opened","openings"])if(params.has(key))dayParams.set(key,params.get(key));
  }
  el("city-day-link").href="cityday.html?"+dayParams;
  const tpl=atlas.templates[roster.people[personIndex][7]];
  const [start,dur,act,loc]=episode(tpl);
  el("now").textContent=clock(minute)+" · "+human(act)+" · "+human(loc)+" ("+clock(start)+"–"+clock(start+dur)+")";
}
function syncURL(){
  const url=new URL(location.href);
  for(const [k,v] of [["area",area],["da",da],["roster",rosterDA],["resident",roster?String(personIndex+1):""]]){
    if(v)url.searchParams.set(k,v);else url.searchParams.delete(k);
  }
  history.replaceState(null,"",url);
}
function showResident(index) {
  if(!roster)return;
  personIndex=Math.max(0,Math.min(roster.people.length-1,index));
  const people=roster.people, homes=roster.homes, p=people[personIndex];
  houseIndex=homes.findIndex(([first,size])=>first<=personIndex&&personIndex<first+size);
  const home=homes[houseIndex];
  el("household-costs").hidden=!home||!housing;
  renderHouseholdCosts();
  el("resident-id").value=personIndex+1;el("home-id").value=home?houseIndex+1:"";
  el("identity").textContent=home?"Household "+rosterDA+"-H"+(houseIndex+1)+" · "+home[1]+" residents · "+
    ({1:"owner",2:"rented or provided",8:"unknown tenure"}[home[2]]??"unknown tenure"):"Unresolved household membership";
  const members=el("members");members.replaceChildren();
  if(home)for(let i=home[0];i<home[0]+home[1];i++){
    const button=document.createElement("button");button.textContent="Person "+(i+1);
    button.setAttribute("aria-pressed",String(i===personIndex));button.onclick=()=>showResident(i);members.append(button);
  }
  el("person-title").textContent=rosterDA+"-P"+(personIndex+1);
  const age=atlas.ages[p[0]-1]??"unavailable",labour=["unavailable / outside universe","employed","unemployed","outside the labour force"][p[2]];
  el("attributes").textContent="Age "+age+" · "+labour+" · 2020 personal income "+(p[3]===null?"unavailable / outside universe":"$"+fmt(p[3]));
  const modes={1:"bicycle",2:"car driver",3:"motorcycle or scooter",4:"other",5:"car passenger",6:"public transit",7:"walk"};
  if(modes[p[6]]) el("attributes").textContent+=" · commute by "+modes[p[6]];
  const day=atlas.templates[p[7]],body=el("episodes");body.replaceChildren();
  el("basis").textContent=day.source+(p[0]===88?" · age unavailable":"")+". Times denote the start of each episode.";
  day.episodes.forEach(([start,,act,loc])=>{const r=body.insertRow();[clock(start),human(act),human(loc)].forEach(v=>r.insertCell().textContent=v);});
  now();syncURL();
}
async function loadRoster(id,index=0) {
  const token=++request;roster=null;rosterDA=id;
  el("selected-da")?.remove();
  el("inspector").hidden=true;el("hint").hidden=false;
  if(!id){el("hint").textContent="Choose a neighbourhood to inspect its residents.";syncURL();return;}
  el("hint").textContent="Loading residents…";
  try{
    const result=await json(base+id+".json");
    if(token!==request)return;
    clockRun?.applyRoster(id,result);
    if(da && result.geometry){
      const boundary=document.createElementNS(svgNS,"path");
      boundary.id="selected-da";boundary.setAttribute("d",polygonPath(result.geometry));
      boundary.setAttribute("aria-label","Selected census area "+da);
      boundary.setAttribute("clip-path","url(#atlas-land-mask)");
      el("atlas-areas").after(boundary);
      el("zoom-area").disabled=false;
    }
    if(!result.people.length){el("hint").textContent="The census records no residents in this area.";syncURL();return;}
    roster=result;el("hint").hidden=true;el("inspector").hidden=false;
    el("roster-da").value=id;el("home-id").max=roster.homes.length;el("home-id").disabled=!roster.homes.length;
    el("resident-id").max=roster.people.length;showResident(index);
  }catch(err){if(token===request)el("hint").textContent=err.message;}
}
function selectArea(name,sub="",which="",person=0){
  area=name;da=sub;el("area").value=area;
  setMapView(overview);el("zoom-area").disabled=!area||!!da;
  const ids=atlas.areas[name]?.das??[];
  options(el("da"),ids,"All areas");el("da").disabled=!area;el("da").value=da;
  options(el("roster-da"),ids);el("roster-da").disabled=!!da;
  fit();syncTime();renderHousing();loadRoster(da||which||ids.find(id=>atlas.das[id].population>0)||"",person);
}
async function init(){
  coverageControl(()=>minute);
  const root="data/vancouver/";
  const replay=!regional&&params.has("marketRun")?await archivedRun(root,params.get("marketRun"),json):null;
  const published=await publishedWeekday(json,replay);
  const pointer=replay?{version:replay.atlas}:published?{...published,version:published.atlas}:regional?await regionalRelease(root+"region/",params.get("clock"),json):await json(root+"atlas/current.json");
  base=root+(regional?"region/atlas/"+pointer.atlas:"atlas/"+pointer.version)+"/";
  const [population,map,parks]=await Promise.all([json(base+"atlas.json"),json(base+"basemap.json"),json("data/vancouver/parks.geojson")]);
  atlas=population;
  // Early regional releases serialised integer and string diary IDs to the same JSON key.
  if(regional&&Object.values(atlas.city.days).reduce((a,b)=>a+b,0)!==atlas.city.population){
    const days={};
    for(const area of Object.values(atlas.areas))for(const [id,n] of Object.entries(area.days))days[id]=(days[id]||0)+n;
    if(Object.values(days).reduce((a,b)=>a+b,0)!==atlas.city.population)throw Error("Regional diaries and population differ.");
    atlas.city.days=days;
  }
  const spread=replay?.clockKind==="spread-departures"?replay.clock:params.get("departureClock");
  const clock=spread??(replay?replay.clock:params.get("clock"));
  if(clock){
    const baseRoot=root+(regional?"region/":"");
    const day=replay?{version:replay.day}:published?{...published,version:published.day}:regional?pointer:await json(baseRoot+"cityday/current.json");
    const {loadClock}=await import("../js/vancouver/departures.js");
    let dayVersion=regional?day.day:day.version;
    const workplaces=params.get("workplaceRun");
    if(spread&&regional&&/^[a-f0-9]{20}$/.test(workplaces??"")){
      const pair=await json(baseRoot+"regional-workplaces/"+workplaces+"/report.json");
      if(pair.versions.atlas!==pointer.atlas)throw Error("The workplace fit and population differ.");
      dayVersion=params.get("workplaceBasis")==="original"?pair.versions.day:pair.day;
    }
    clockRun=await (spread?loadClock(baseRoot,regional?pointer.atlas:pointer.version,dayVersion,clock,json,"departure-clock","spread"):
      loadClock(baseRoot,regional?pointer.atlas:pointer.version,dayVersion,clock,json));
    clockRun.applyAtlas(atlas);
    if(clockRun.kind==="work-transit-flex")for(const anchor of document.querySelectorAll(".masthead a")){
      const url=new URL(anchor.href);
      if(url.pathname.endsWith("/cityday.html")){
        mapClock(url.searchParams);
        anchor.href=url;
      }
    }
  }
  atlas.heldout ??= [12,13];
  const check=el("validation"),measure=el("validation-measure"),version=regional?pointer.atlas:pointer.version;
  if(!regional)fetch(root+"atlas/boundary-"+version+".json").then(async response=>{
    if(!response.ok)return;
    const audit=await response.json();
    if(audit.atlas!==version||audit.municipality!=="5915022")return;
    const list=group=>Object.entries(group).map(([d,n])=>d+" ("+fmt(n)+")").join(", ");
    const panel=el("boundary-check");panel.hidden=false;panel.open=params.has("boundary");
    el("boundary-totals").textContent=fmt(audit.municipalPopulation)+" residents in "+fmt(audit.municipalAreas)+
      " municipal census areas. The replay covers "+fmt(atlas.city.population)+" residents in "+fmt(audit.inReplay)+" areas.";
    el("boundary-areas").textContent=!Object.keys(audit.missing).length&&!Object.keys(audit.adjacent).length?
      "Every area in the replay belongs to the municipality, and all municipal areas are represented.":
      "City areas missing from the replay (census populations in parentheses) · "+(list(audit.missing)||"none")+
      ". Additional areas in "+([...new Set(Object.values(audit.adjacentAreas))].join(", ")||"the replay")+" · "+(list(audit.adjacent)||"none")+".";
  }).catch(()=>{});
  const updateCheck=()=>{
    const url=new URL(location.href);
    if(check.open)url.searchParams.set("check",measure.value);else url.searchParams.delete("check");
    history.replaceState(null,"",url);validatePopulation();
  };
  const loadValidation=async()=>{
    if(!check.open&&!el("housing").open)return;
    if(validation){validatePopulation();return;}
    try{
      validationRequest??=json(root+(regional?"region/":"")+"atlas/validation-"+version+".json");
      const report=await validationRequest;
      if(report.version!==version)throw Error("Population and census check versions differ.");
      validation=report;validatePopulation();
    }catch(e){validationRequest=null;el("validation-result").textContent=e.message;el("housing-context").textContent=e.message;}
  };
  check.ontoggle=()=>{updateCheck();loadValidation();};
  if(!regional){
    let pending;
    housingRequest=()=>pending??=housingRelease(root+"atlas/housing/",version,json).then(release=>{
      if(release&&release.report.atlas!==version)throw Error("Housing and population releases differ.");
      housing=release;
      if(release){
        el("household-costs").hidden=houseIndex<0;
        const picker=el("atlas-layer");picker.hidden=false;picker.onchange=changeMap;
        const view=params.get("map");
        if(Object.hasOwn(housingMaps,view)){picker.value=view;changeMap();}
        renderHousing();
      }
      return release;
    });
    housingRequest().catch(()=>{});
    const assess=el("property-assessments"),requested=params.get("assessments");
    const pinned=requested&&/^[a-f0-9]{20}$/.test(requested)?requested:undefined;
    assess.ontoggle=renderAssessments;
    housingRelease(root+"atlas/assessments/",version,json,pinned).then(release=>{
      if(!release||release.report.atlas!==version)return;
      assessmentReport=release.report;assess.hidden=false;
      if(requested){el("housing").open=true;assess.open=true;}
      renderAssessments();
    }).catch(e=>{
      if(requested){el("housing").open=true;assess.hidden=false;assess.open=true;el("assessment-scope").textContent=e.message;}
    });
    el("household-costs").ontoggle=renderHouseholdCosts;
  }
  el("housing").ontoggle=()=>{loadValidation();renderHousing();};
  if(params.has("housing"))el("housing").open=true;
  measure.onchange=updateCheck;
  if(["income","commute"].includes(params.get("check"))){measure.value=params.get("check");check.open=true;}
  const areas=Object.keys(atlas.areas).sort();options(el("area"),areas,scopeName);
  regionMap(map,parks);
  if(regional){
    document.querySelector(".intro .context").textContent="Vancouver, UBC & North Shore · 2021 Census";
    el("zoom-city").textContent="Regional view";
  }
  if(clockRun)document.querySelector(".intro .context").append(
    clockRun.kind==="scheduled-transit"?" · Commutes timed to transit":
    clockRun.kind==="work-transit-flex"?" · Flexible home time":
    clockRun.kind==="spread-departures"?" · Spread departures":" · Household commute times");
  el("zoom-area").onclick=zoomSelection;
  el("zoom-city").onclick=()=>setMapView(overview);
  el("area").onchange=e=>selectArea(e.target.value);el("da").onchange=e=>selectArea(area,e.target.value);
  el("roster-da").onchange=e=>loadRoster(e.target.value);
  el("home-id").onchange=e=>{const h=roster.homes[Number(e.target.value)-1];if(h)showResident(h[0]);};
  el("resident-id").onchange=e=>showResident(Math.floor(Number(e.target.value)||1)-1);
  el("outlier").onclick=()=>selectArea("Downtown","59154026");
  function stop(){clearInterval(timer);timer=null;el("play").textContent="Play";}
  el("minute").oninput=e=>{stop();minute=Number(e.target.value);syncTime();};
  el("play").onclick=()=>{if(timer){stop();return;}el("play").textContent="Pause";
    timer=setInterval(()=>{minute=240+(minute-240+5)%1440;syncTime();},300);};
  const requested=Number(params.get("minute"));
  if(Number.isFinite(requested)&&requested>=240&&requested<1680)minute=requested;
  const start=areas.includes(params.get("area"))?params.get("area"):"";
  const ids=atlas.areas[start]?.das??[];
  el("status").textContent=areas.length+(regional?" study areas · ":" neighbourhoods · ")+fmt(Object.keys(atlas.das).length)+" census areas";
  selectArea(start,ids.includes(params.get("da"))?params.get("da"):"",ids.includes(params.get("roster"))?params.get("roster"):"",Math.max(0,Number.parseInt(params.get("resident"),10)||1)-1);
}
init().catch(e=>{el("status").textContent=e.message+". Build the atlas as described in README.md.";});
