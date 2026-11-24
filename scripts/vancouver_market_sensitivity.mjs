// Score paired grocery demand releases through the same opening rule as the replay.
import {createHash} from "node:crypto";
import {readFileSync,writeFileSync,renameSync,mkdirSync,mkdtempSync,rmSync} from "node:fs";
import {join} from "node:path";
import {chooseShops} from "../public/lab/shop-actions.js";
import {openingHours} from "../public/js/vancouver/workplaces.js";

const sha256=bytes=>createHash("sha256").update(bytes).digest("hex");
const same=(left,right)=>JSON.stringify(left)===JSON.stringify(right);
const count=(counts,key)=>counts.set(key,(counts.get(key)??0)+1);
const ranked=counts=>Array.from(counts,([name,n])=>({name,n})).sort((a,b)=>b.n-a.n||a.name.localeCompare(b.name));
const canfed="https://www150.statcan.gc.ca/n1/pub/13-20-0001/132000012025001-eng.htm";
const accessStudy="https://vancouver.ca/files/cov/equitable-access-to-healthy-food-retail-report.pdf";
const retailStudy="https://vancouver.ca/files/cov/city-of-vancouver-small-business-study-2020.pdf";

function readMarket(root,id){
  if(!/^[a-f0-9]{64}$/.test(id))throw Error("Expected a versioned market catalogue.");
  const directory=join(root,"market","archive",id);
  const bytes=readFileSync(join(directory,"market.json"));
  if(sha256(bytes)!==id)throw Error("The archive and market ID differ.");
  return JSON.parse(bytes);
}

function accessAudit(access,site,area){
  const counts=access.counts[0],observed=access.observed["1000"];
  const reference=access.sites[site.id]?.newDA[0];
  if(!reference||![counts,observed,access.homeArea].every(rows=>rows.length===access.das.length))
    throw Error("Can-FED coverage and census areas differ.");
  if(!access.boundary.municipal.every(Boolean))throw Error("The access report must cover the legal City footprint.");
  const hasStore=levels=>levels?.some(level=>level>0);
  const geography=new Map(access.das.map((da,i)=>[da,{
    observed:observed[i]?.every(level=>Number.isInteger(level)&&level>=0)?hasStore(observed[i]):null,modeled:counts[i]>0
  }]));
  const local=access.das.filter((_,i)=>access.areas[access.homeArea[i]]===area).map(da=>geography.get(da));
  const comparable=local.filter(row=>row.observed!==null);
  const gained=reference.map(i=>geography.get(access.das[i]));
  return {
    geography,
    summary:{
      radiusMetres:1000,source:canfed,canfedDigest:access.canfed,geographyDigest:access.geography,
      neighbourhood:area,censusAreas:local.length,comparable:comparable.length,
      observedAccess:comparable.filter(row=>row.observed).length,modeledAccess:comparable.filter(row=>row.modeled).length,
      gainedAreas:gained.length,gainedWithObservedAccess:gained.filter(row=>row.observed).length
    }
  };
}

function scores(catalogue,siteId,das,homeAreas,geography,minute){
  const run=catalogue.runs[catalogue.variants.tracts];
  const siteIndex=catalogue.sites.findIndex(site=>site.id===siteId);
  const site={...catalogue.sites[siteIndex],changes:run.changes[siteIndex],afterHours:run.afterHours[siteIndex]};
  const winners=chooseShops(run.occasions,new Map([[siteId,site]]),[[siteId,"full",minute]],openingHours);
  const neighbourhoods=new Map(),stores=new Map(),templates=new Map();
  const hours=Array(24).fill(0),homeAccess={observed:0,modeled:0,neither:0,missing:0};
  let fitted=0,diverted=0;
  for(const index of winners.keys()){
    const row=run.occasions[index],home=das[row[0]];
    if(!homeAreas.has(home))throw Error("Modeled visitor has no home neighbourhood in the pinned atlas.");
    count(neighbourhoods,homeAreas.get(home));
    if(row[15]!=null)count(templates,String(row[15]));
    hours[Math.floor(row[3]/60)%24]++;
    if(row[17]==="added-shopping")fitted++;
    if(row[5]>=0){
      diverted++;
      count(stores,catalogue.stores[row[5]].id);
    }else{
      const access=geography.get(home);
      if(access?.observed)homeAccess.observed++;
      if(access?.modeled)homeAccess.modeled++;
      if(access?.observed===false&&!access.modeled)homeAccess.neither++;
      if(access?.observed==null)homeAccess.missing++;
    }
  }
  const divertedFrom=ranked(stores).map(row=>({...row,label:catalogue.stores.find(store=>store.id===row.name).name}));
  return {visits:winners.size,recorded:winners.size-fitted,fitted,diverted,
    newlyFeasible:winners.size-diverted,homeAccess,homeNeighbourhoods:ranked(neighbourhoods),
    divertedFrom,arrivalHours:hours,sourceDiaries:templates.size,largestDiary:Math.max(0,...templates.values())};
}

function build(data,release,siteId,accessId){
  const root=join(data,"vancouver"),read=(...path)=>JSON.parse(readFileSync(join(root,...path)));
  const weekday=JSON.parse(readFileSync(join(data,"runs",release+".json")));
  if(weekday.release!==release||weekday.city!=="vancouver"||weekday.coverage!=="city"||!weekday.jointRun)
    throw Error("Choose the combined published Vancouver weekday.");
  const pair=read("market","demand_"+weekday.jointRun+".json");
  const baseline=readMarket(root,pair.baseMarket),augmented=readMarket(root,pair.market),local=readMarket(root,accessId);
  if(![baseline,augmented,pair].every(c=>["atlas","day","streets"].every(key=>c[key]===weekday[key]))||
    pair.jointRun!==weekday.jointRun||augmented.jointRun!==weekday.jointRun||augmented.shoppingDemand?.baseMarket!==pair.baseMarket||
    augmented.shoppingDemand?.outings!==pair.outings||!same(baseline.sites,augmented.sites)||!same(baseline.stores,augmented.stores)||
    local.streets!==baseline.streets||!same(local.stores,baseline.stores))
    throw Error("The day, shopping comparison and Can-FED access use different inputs.");
  const baseRun=baseline.runs[baseline.variants.tracts],addedRun=augmented.runs[augmented.variants.tracts];
  if(!same(baseRun.occasions,addedRun.occasions.slice(0,baseRun.occasions.length)))
    throw Error("Adding shopping demand changed the recorded occasions.");
  const site=baseline.sites.find(s=>s.id===siteId);
  const accessSite=local.sites.find(s=>s.id===siteId);
  if(!site||!accessSite||site.name!==accessSite.name||site.area!==accessSite.area||!same(site.point,accessSite.point))
    throw Error("The access report used a different proposed storefront.");
  const had=baseline.sites.indexOf(site),available=addedRun.changes[had].filter(([i])=>i<baseRun.occasions.length);
  if(!same(baseRun.changes[had],available))throw Error("Adding demand changed recorded shoppers' choices.");
  const day=read("cityday",weekday.day,"day.json"),atlas=read("atlas",weekday.atlas,"atlas.json");
  const homeAreas=new Map(Object.entries(atlas.areas).flatMap(([name,area])=>area.das.map(da=>[da,name])));
  const {geography,summary}=accessAudit(local.localWalk,site,day.areas[site.area]);
  if(geography.size!==day.das.length||!day.das.every(da=>geography.has(da)))
    throw Error("The access report and pinned weekday use different census areas.");
  return {
    schema:1,release,jointRun:weekday.jointRun,site,siteArea:day.areas[site.area],markets:[pair.baseMarket,pair.market],
    accessMarket:accessId,access:summary,contextSources:[accessStudy,retailStudy],
    cases:[null,720,900].map(minute=>({minute,recorded:scores(baseline,siteId,day.das,homeAreas,geography,minute),
      augmented:scores(augmented,siteId,day.das,homeAreas,geography,minute)}))
  };
}

const [data,release,site,access]=process.argv.slice(2);
if(!data||!/^\w+$/.test(site??"")||!/^[a-f0-9]{64}$/.test(release??""))
  throw Error("Usage: vancouver_market_sensitivity.mjs DATA_ROOT DAY_RUN SITE ACCESS_MARKET");
const report=build(data,release,site,access);
const directory=join(data,"vancouver","market","sensitivity");
mkdirSync(directory,{recursive:true});
const staging=mkdtempSync(join(directory,".build-"));
try{
  const staged=join(staging,"report.json"),out=join(directory,site+"-"+release+".json");
  writeFileSync(staged,JSON.stringify(report));
  renameSync(staged,out);
  console.log(out);
}finally{rmSync(staging,{recursive:true,force:true});}
