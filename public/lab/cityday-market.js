import {chooseShops,readOpenings,referenceReplay} from "./shop-actions.js";
import {housingRelease} from "./housing-data.js";
import {GroceryWalks} from "./grocery-walks.js";
import {attachSiteSensitivity} from "./market-sensitivity.js";
import {renderResult} from "../js/replay/replay.js";

const el=id=>document.getElementById(id);
const count=n=>n.toLocaleString();
const money=new Intl.NumberFormat("en-CA",{style:"currency",currency:"CAD"});
const annual=new Intl.NumberFormat("en-CA",{style:"currency",currency:"CAD",maximumFractionDigits:0});
const sum=values=>values.reduce((a,b)=>a+b,0);
const clock=t=>String(Math.floor(t/60)%24).padStart(2,"0")+":"+String(t%60).padStart(2,"0");
const personKey=(da,index)=>da+"/"+index;

// Overlay only the selected stationary slots. Both surrounding legs then resolve
// their endpoints through the same plans used by map playback and following.
export class GroceryMarket {
  constructor({load,archive,loadHouseholds,housingFolder,json,inferredWalks,loadShoppingEvidence,loadPurchaseChoices,loadDemandPair,loadSiteSensitivity,shoppingOutings,fixedCommute,places,day,neighbourhoods,versions,workplaces,clock,rule,tours,cycling,showSites,locate,visit,follow,refresh,time,reveal,walkingGraph}){
    Object.assign(this,{load,archive,inferredWalks,loadShoppingEvidence,loadPurchaseChoices,loadDemandPair,shoppingOutings,fixedCommute,places,day,versions,workplaces,clock,rule,tours,cycling,showSites,follow,refresh,time,walkingGraph});
    this.actions=new Map();
    if(loadSiteSensitivity)this.showSiteSensitivity=attachSiteSensitivity(loadSiteSensitivity);
    this.homeArea=new Map(Object.entries(neighbourhoods).flatMap(([area,group])=>group.das.map(d=>[d,area])));
    this.overrides=new Map();this.outingPlaces=new Map();this.site=null;this.changes=[];this.revision=0;
    this.homeIndex=day.das.map(da=>day.areas.indexOf(this.homeArea.get(da)));
    this.linkedVisit=new URLSearchParams(location.search);
    this.playOpening=["shopPlay","opened","openings"].some(key=>this.linkedVisit.has(key));
    this.details=el("market");
    this.details.ontoggle=()=>this.toggle().catch(e=>{el("market-status").textContent=e.message;});
    el("shop-play-map").hidden=false;
    el("shop-play-map").onclick=()=>{
      reveal();
      this.playOpening=true;this.details.open=true;
      if(this.payload)this.apply();
    };
    for(const id of ["shop-activate","shop-activate-map"])el(id).onclick=()=>this.activate();
    el("shop-reset").onclick=()=>{this.actions.delete(this.site?.id);this.apply();};
    el("shop-compare").onclick=()=>{this.playOpening=false;this.actions.clear();this.apply();};
    el("market-area").onchange=()=>{this.site=null;this.fillSites();this.apply();};
    el("market-site").onchange=()=>this.focusSite(this.sites.get(el("market-site").value));
    el("market-travel").onchange=()=>{
      const url=new URL(location.href);url.searchParams.set("cycleTours",el("market-travel").value);location.assign(url);
    };
    el("market-hours").onchange=()=>{
      const value=el("market-hours").value, schedule=this.openingHours(value);
      el("market-custom").hidden=value!=="custom";
      if(schedule?.opens){
        el("market-opens").value=schedule.opens;el("market-closes").value=schedule.closes;
      }
      this.apply();
    };
    for(const id of ["market-opens","market-closes"])el(id).oninput=()=>this.apply();
    el("market-basket").oninput=()=>{this.sales();this.syncURL();this.refresh();};
    const saved=el("market-saved");
    const readSaved=async()=>{
      if(!saved.open||!this.details.open)return;
      try{
        this.savedUI??=import("./saved-openings.js").then(ui=>ui.init(()=>this.snapshot()));
        const refreshSaved=await this.savedUI;
        this.savedReady=true;el("save-opening").disabled=!this.canSave();
        await refreshSaved();
      }catch(e){this.savedUI=null;el("saved-status").textContent=e.message;}
    };
    saved.ontoggle=readSaved;
    window.addEventListener("focus",readSaved);
    el("market-person").onchange=()=>this.reason();
    el("market-next").onclick=()=>{
      if(this.next===null)return;
      el("market-person").value=String(this.next);this.reason();
      this.inspect().catch(e=>{el("market-reason").textContent=e.message;});
    };
    el("market-inspect").onclick=()=>this.inspect().catch(e=>{el("market-reason").textContent=e.message;});
    el("market-locate").onclick=()=>{if(this.site)locate(this.site.point);};
    el("market-street").onclick=()=>{
      if(!this.site)return;
      const site=this.site,status=el("market-street-status");
      status.textContent="";
      visit(site).catch(error=>{if(this.site===site)status.textContent=error.message;});
    };
    this.householdPanel=el("household-market");
    this.housingPanel=el("household-housing");
    const hasHousingLink=this.linkedVisit.has("housingRun")||this.linkedVisit.has("shelterShock");
    this.householdPanel.ontoggle=async()=>{
      if(!this.householdPanel.open)return;
      try{
        el("household-reach").textContent="Loading household budgets…";
        this.householdRequest??=loadHouseholds();
        const result=await this.householdRequest;
        if(Object.entries(this.versions).some(([key,value])=>result[key]!==value))
          throw Error("The household budget build uses a different city release.");
        this.households=result;
        this.householdResults();
        this.loadHousing(housingFolder,json,hasHousingLink).catch(error=>{
          this.housingRequest=null;
          this.housingPanel.hidden=false;el("household-housing-status").textContent=error.message;
        });
      }catch(error){
        this.householdRequest=null;
        el("household-reach").textContent=error.message;
      }
    };
    el("household-radius").onchange=()=>this.householdResults();
    el("household-share").oninput=()=>this.householdResults();
    el("shelter-shock").onchange=()=>{
      const url=new URL(location.href);
      url.searchParams.set("housingRun",this.housing.version);
      url.searchParams.set("shelterShock",el("shelter-shock").value);
      history.replaceState(null,"",url);
      this.householdResults();
    };
    this.housingPanel.ontoggle=()=>this.householdResults();
    if(this.linkedVisit.has("shop")||this.playOpening||hasHousingLink)this.details.open=true;
    if(hasHousingLink)this.householdPanel.open=true;
  }
  get active(){return this.details.open||this.playOpening;}
  get playedAt(){return this.actions.get(this.site?.id)?.[2]??null;}
  async toggle(){
    if(this.playOpening&&!this.details.open)return;
    if(!this.details.open){
      renderResult(null);
      this.overrides.clear();this.outingPlaces=new Map();this.bikeLegs?.clear();this.walkLegs?.clear();this.walkHours=[];this.walkTrips=0;this.effects=null;this.revision++;this.showSites([],null);this.syncURL();this.refresh();return;
    }
    if(!this.catalog){
      if(!this.loading)this.loading=Promise.all([this.load(),import("../js/vancouver/workplaces.js")]).catch(e=>{this.loading=null;throw e;});
      const [{catalog:result,hash},model]=await this.loading;
      if(!this.active)return;
      if(!this.catalog){
        if(result.clock!==this.clock||result.workplaces!==this.workplaces||result.day!==this.versions.day||result.atlas!==this.versions.atlas||result.streets!==this.versions.streets)
          throw Error("The grocery build and day map have different source versions.");
        if(result.bicycle&&(result.bicycle.tours!==this.tours||result.bicycle.cycling!==this.cycling))
          throw Error("The bicycle market and outing assignments have different releases.");
        if(result.shoppingDemand?.outings!==this.shoppingOutings)
          throw Error("The grocery market and added shopping trips have different releases.");
        this.catalog=result;this.hash=hash;this.project=model.projectMarket;this.openingHours=model.openingHours;
        if(/^[a-f0-9]{64}$/.test(result.parentMarket??"")){
          el("market-clock-pair").hidden=false;
          const comparison=el("market-original-clock");
          const link=()=>{
            const url=new URL(location.href),params=url.searchParams;
            this.openingParams(params);
            params.set("marketRun",result.parentMarket);
            params.set("shop",this.site?.id||"baseline");
            params.set("hours",this.hours);
            params.set("minute",Math.floor(this.time()));
            for(const key of ["departureClock","clock","hiredRides","dispatchRun","visit","cycleTours","grocery","localWalk"])params.delete(key);
            url.hash="market";
            comparison.href=url;
          };
          this.clockPairLink=link;
          for(const event of ["pointerdown","focus"])comparison.addEventListener(event,link);
        }
        this.combine=model.combineMarket;this.bikeRuns=new Map();
        el("market-travel").parentElement.hidden=!result.bicycle;
        const add=x=>this.places.push([...x.point,x.area,x.name])-1;
        this.storePlaces=result.stores.map(add);this.sitePlaces=new Map(result.sites.map(s=>[s.id,add(s)]));
        for(const [index,name] of this.day.areas.entries())el("market-area").add(new Option(name,String(index)));
        const params=new URL(location.href).searchParams;
        const basket=params.get("basket");
        if(basket!==null&&basket.trim()&&Number.isFinite(Number(basket))&&Number(basket)>=0)el("market-basket").value=basket;
        this.site=result.sites.find(s=>s.id===params.get("shop"))||null;
        el("market-area").value=String(this.site?.area??this.day.areas.indexOf("Mount Pleasant"));
        const requested=params.get("hours")??"full",schedule=this.openingHours(requested);
        const custom=!["full","short","24h"].includes(schedule?.key);
        el("market-hours").value=custom?"custom":schedule.key;
        el("market-custom").hidden=!custom;
        if(custom||schedule.opens){
          const [opens,closes]=requested.split("-");
          el("market-opens").value=schedule?.opens??opens;
          el("market-closes").value=schedule?.closes??closes??"";
        }
        el("market-status").textContent=count(result.sites.length)+" alternative storefronts · "+count(result.stores.length)+" existing grocers";
        el("market-panel").hidden=false;
        const purchase=el("market-purchase");
        purchase.value=result.purchase?.key||"fixed";
        if(result.bicycle){
          const local=el("market-local-walk");
          local.checked=!!result.localWalk;
          const linkWalking=target=>{
            local.parentElement.hidden=false;
            local.onchange=()=>{
              const url=new URL(location.href);url.searchParams.set("marketRun",target);
              if(local.checked)url.searchParams.set("localWalk","1");else url.searchParams.delete("localWalk");
              location.assign(url);
            };
          };
          if(result.localWalk)linkWalking(result.localWalk.base);
          else this.loadPurchaseChoices(true).then(choices=>{
            const rule=result.purchase?.key||"fixed";
            if(choices.tours!==this.tours||choices.streets!==this.versions.streets||
               choices.bases?.[rule]!==this.hash||!/^[a-f0-9]{64}$/.test(choices[rule]))return;
            linkWalking(choices[rule]);
          }).catch(()=>{});
        }
        if(result.bicycle)this.loadPurchaseChoices(!!result.localWalk).then(choices=>{
          if(choices.tours!==this.tours||choices.streets!==this.versions.streets||
             ![choices.fixed,choices.bc2010].every(h=>/^[a-f0-9]{64}$/.test(h))||
             (this.hash&&choices[purchase.value]!==this.hash))return;
          purchase.parentElement.hidden=false;
          purchase.onchange=()=>{
            const url=new URL(location.href);
            if(url.searchParams.has("marketRun"))url.searchParams.set("marketRun",choices[purchase.value]);
            if(purchase.value==="fixed")url.searchParams.delete("grocery");else url.searchParams.set("grocery",purchase.value);
            if(el("market-evidence").open)url.searchParams.set("shopCheck","1");
            if(el("local-access").open)url.searchParams.set("accessCheck","1");
            location.assign(url);
          };
        }).catch(()=>{});
        if(result.bicycle)this.setupEvidence().catch(error=>{
          el("market-evidence").hidden=false;el("shopping-evidence-status").textContent=error.message;
        });
        if(result.shoppingDemand)this.demandLink({baseMarket:result.shoppingDemand.baseMarket});
        else if((!result.workplaces||this.fixedCommute)&&!result.clock)this.loadDemandPair().then(pair=>{
          if(pair&&(!this.fixedCommute||pair.baseMarket===this.hash))this.demandLink(pair);
        }).catch(()=>{});
      }
    }
    this.selectRun(true);
  }
  demandLink(pair){
    const link=el("market-demand-link"),added=!!this.catalog.shoppingDemand;
    el("market-demand-pair").hidden=false;
    link.textContent=added?"Score recorded shopping only":
      this.hash===pair.baseMarket?"Score fitted shopping walks as well":"Compare shopping demand in the walking model";
    this.updateDemandLink=()=>{
      const url=new URL(location.href),params=url.searchParams;
      for(const key of ["outingsRun","outings","cycleTours","grocery","localWalk","visit"])params.delete(key);
      this.openingParams(params);
      params.set("marketRun",added?pair.baseMarket:pair.market);
      params.set("shop",this.site?.id||"baseline");
      params.set("hours",this.hours??"full");
      params.set("minute",Math.floor(this.time()));
      url.hash="market";
      link.href=url;
    };
    this.updateDemandLink();
    for(const event of ["focus","pointerdown"])link.addEventListener(event,this.updateDemandLink);
  }
  async setupEvidence(){
    const view=await import("../js/vancouver/shopping-evidence.js");
    if(this.catalog.localWalk){
      this.accessRender=view.initAccess(this.catalog.localWalk,()=>this.site?.id,()=>this.liveWalks||[],(d,i,s)=>this.follow(this.day.das[d],i,s).catch(e=>{el("local-drivers").textContent=e.message;}));
      if(new URLSearchParams(location.search).has("accessCheck"))el("local-access").open=true;
      this.accessRender();
    }
    const state=()=>{
      const site=this.site,occasions=this.payload?.occasions;
      const rows=site?.afterHours&&occasions?site.changes.concat(site.afterHours).map(([j])=>[occasions[j][3],occasions[j][4]]):null;
      return {site:site?.id,rows,hours:this.hours,mode:this.run,walked:(this.walkTrips||0)/2,inferred:this.inferredWalks(),survey:this.catalog.purchase?.survey};
    };
    this.evidenceRender=view.init(async()=>{
      const report=await this.loadShoppingEvidence();
      const pinned={...this.versions,tours:this.tours,cycling:this.cycling};
      if(Object.keys(pinned).some(k=>pinned[k]!==report.versions[k]))throw Error("Different shopping evidence release.");
      return report;
    },state,(opens,closes)=>{
      if(this.playedAt!==null)return;
      el("market-hours").value="custom";el("market-custom").hidden=false;
      el("market-opens").value=opens;el("market-closes").value=closes;this.apply();
    });
    const panel=el("market-evidence");panel.hidden=false;
    if(this.linkedVisit?.has("shopCheck")||new URLSearchParams(location.search).has("shopCheck"))panel.open=true;
  }
  selectRun(force=false){
    if(!this.catalog||!this.active)return;
    const data=this.catalog, id=data.variants?data.variants[this.rule()]:data.bicycle?(this.rule()||"diary"):0;
    if(!force&&this.run===id)return;
    if(data.variants&&!data.runs[id])throw Error("Missing grocery choices for this workplace assignment.");
    this.run=id;
    const run=data.runs?.[id];
    if(data.bicycle){
      if(!this.bikeRuns.has(id))this.bikeRuns.set(id,this.combine(data,id));
      this.payload=this.bikeRuns.get(id);el("market-travel").value=id;
    }else this.payload=run?{...data,...run,sites:data.sites.map((s,i)=>({...s,changes:run.changes[i],afterHours:run.afterHours?.[i]}))}:data;
    this.site=this.payload.sites.find(s=>s.id===this.site?.id)||null;
    this.sites=new Map(this.payload.sites.map(site=>[site.id,site]));
    if(!this.openingsRestored){this.restoreOpenings();this.openingsRestored=true;}
    const {eligible,coverage,occasions,share,speed,budget}=this.payload;
    const reference=this.openingHours("full");
    const outside=occasions.filter(row=>!reference.admits(row[3],row[4]));
    const starts=new Set(outside.map(row=>row[3]%1440));
    const templates=new Set(outside.map(row=>row[15]));
    el("market-evening-evidence").textContent=count(outside.length)+" located grocery occasions fall outside the assumed hours of existing grocers."+
      (starts.size===1?" All start at "+clock(starts.values().next().value)+" in the sampled diaries.":
       starts.size?" They have "+count(starts.size)+" distinct diary start times.":"")+
      (templates.size===1&&!templates.has(undefined)?" All use the same source diary.":"")+" The model keeps these times when a shop opens.";
    el("market-method").textContent=count(eligible)+" in-person goods outings have a walk on both sides and two located endpoints. A repeatable "+
      (+(100*share).toFixed(1))+"% grocery draw yields "+count(data.bicycle?data.occasions.length:occasions.length)+" located walking grocery occasions. Each walk must fit its diary time at "+
      speed+" m/min, with "+budget+" minutes available for the two walks together."+
      (data.bicycle?" The selected purchase rule gives "+count(this.payload.bikeOccasions)+" bicycle occasions from "+count(this.payload.bikeQualifying)+
        " goods stops. Each ride must fit at "+data.bicycle.speed+" m/min. The two shortest directed rides together must fit the same "+budget+"-minute budget.":"");
    const purchase=data.purchase;
    el("market-purchase-source").hidden=!purchase;
    if(purchase){
      const pool=purchase.survey.pools.bc;
      const band=g=>g.interval.map(p=>(p*100).toFixed(1)+"%").join("–");
      const intervals=pool.active.interval&&pool["car-driver"].interval?
        " Approximate 95% sampling intervals are "+band(pool.active)+" for active travel and "+band(pool["car-driver"])+" for driving.":"";
      el("purchase-calibration").textContent="The historical rule assigns "+(100*pool.active.share).toFixed(1)+
        "% of original walking and cycling purchases and "+(100*pool["car-driver"].share).toFixed(1)+
        "% of switched drivers’ purchases to groceries. Urban BC reported "+pool.active.groceryStops+" of "+pool.active.stops+
        " qualifying active-travel stops and "+pool["car-driver"].groceryStops+" of "+pool["car-driver"].stops+
        " driver stops at a grocer for food."+intervals+" Transferring these 2010 rates to Vancouver adds uncertainty. Only "+pool.bike.stops+" active stops were by bicycle.";
    }
    const info=el("market-coverage");
    info.hidden=!coverage;
    if(coverage){
      info.textContent=count(coverage.drawn)+" walking grocery occasions citywide · "+count(data.bicycle?data.occasions.length:occasions.length)+" can be checked against the street network. "+
        (coverage.externalDrawn?count(coverage.externalDrawn)+" involve an external workplace without a street address. ":"")+
        (coverage.missingDrawn?count(coverage.missingDrawn)+" have another unlocated endpoint.":"");
    }
    this.fillSites();this.apply();
  }
  fillSites(){
    const select=el("market-site");select.replaceChildren(new Option("Existing grocers only",""));
    for(const s of this.payload.sites.filter(s=>s.area===Number(el("market-area").value)))
      select.add(new Option(s.name+" · #"+s.id,s.id));
    select.value=this.site?.id||"";
  }
  selectSite(id){
    const site=this.sites?.get(id);
    if(this.active&&site)this.focusSite(site);
  }
  focusSite(site){
    this.site=site??null;
    el("market-street-status").textContent="";
    if(site)el("market-area").value=String(site.area);
    const action=this.actions.get(site?.id);
    if(action){
      const schedule=this.openingHours(action[1]),custom=!["full","short","24h"].includes(schedule.key);
      el("market-hours").value=custom?"custom":schedule.key;
      el("market-custom").hidden=!custom;
      if(schedule.opens){
        el("market-opens").value=schedule.opens;el("market-closes").value=schedule.closes;
      }
    }
    this.fillSites();this.apply();
  }
  restoreOpenings(){
    try{
      const actions=new Map();
      for(const row of readOpenings(this.linkedVisit)){
        if(!Array.isArray(row)||row.length!==3)throw Error();
        const [id,hours,minute]=row,site=this.sites.get(id),schedule=this.openingHours(hours);
        if(!site||!schedule||!Number.isInteger(minute)||minute<240||minute>=1680||
           !schedule.admits(minute,1)||(!schedule.withinReference&&!site.afterHours)||actions.has(id))throw Error();
        actions.set(id,[id,schedule.key,minute]);
      }
      const selected=actions.get(this.site?.id);
      if(selected&&selected[1]!==this.openingHours(this.linkedVisit.get("hours")??"full")?.key)throw Error();
      this.actions=actions;
    }catch{
      this.openingError="The link contains an invalid storefront opening for this weekday.";
    }
  }
  openingParams(params){
    if(this.playOpening)params.set("shopPlay","1");else params.delete("shopPlay");
    if(this.playedAt!==null)params.set("opened",String(this.playedAt));else params.delete("opened");
    if(this.actions.size>1||(this.actions.size&&this.playedAt===null))
      params.set("openings",JSON.stringify([...this.actions.values()]));
    else params.delete("openings");
    if(this.actions.size&&this.hash)params.set("marketRun",this.hash);
  }
  syncURL(){
    const url=new URL(location.href);
    if(this.active && this.payload){
      if(el("market-basket").value&&el("market-basket").validity.valid)url.searchParams.set("basket",el("market-basket").value);
      else url.searchParams.delete("basket");
      url.searchParams.set("shop",this.site?.id||"baseline");url.searchParams.set("hours",this.hours);
    }else{url.searchParams.delete("shop");url.searchParams.delete("hours");url.searchParams.delete("basket");}
    this.openingParams(url.searchParams);
    history.replaceState(null,"",url);
  }
  get canActivate(){
    return this.playOpening&&this.playedAt===null&&this.site&&!this.hoursError&&this.coversMinute(Math.ceil(this.time()));
  }
  coversMinute(minute){
    return Number.isInteger(minute)&&minute>=240&&minute<1680&&this.schedule?.admits(minute,1);
  }
  openAt(id,minute=Math.floor(this.time())){
    const action=this.actions.get(id);
    return !!action&&minute>=action[2]&&this.openingHours(action[1]).admits(minute,1);
  }
  activate(){
    if(!this.canActivate)return;
    this.openingError=null;
    this.actions.set(this.site.id,[this.site.id,this.hours,Math.ceil(this.time())]);
    const url=new URL(location.href);
    url.searchParams.set("minute",String(this.time()));
    history.replaceState(null,"",url);
    this.apply();
  }
  canSave(){
    return this.savedReady&&this.site&&!this.hoursError&&(!this.playOpening||this.playedAt!==null);
  }
  playStatus(minute){
    const committed=this.playedAt!==null;
    el("shop-play").hidden=!this.playOpening;
    el("shop-activate-map").hidden=!this.playOpening||!this.site||committed;
    for(const id of ["shop-activate","shop-activate-map"])el(id).disabled=!this.canActivate;
    el("shop-activate").hidden=committed;
    el("shop-reset").hidden=!committed;
    if(!this.playOpening)return;
    el("shop-play-status").textContent=committed?
      "Opened at "+clock(this.playedAt)+(this.playedAt>=1440?" +1":"")+". "+
        (minute<this.playedAt?"The replay is before the opening.":this.coversMinute(minute)?"The shop is open.":"The shop is outside its scheduled hours."):
      this.site?(this.openingError||(!this.coversMinute(Math.ceil(this.time()))?"Set the clock inside the shop’s hours to open it.":"Open the shop when you’re ready. Shoppers can change plans before they set off.")):
      "Choose a storefront to open.";
  }
  apply(){
    const {occasions,sites,stopTiming}=this.payload,preset=el("market-hours").value;
    this.hours=preset==="custom"?el("market-opens").value+"-"+el("market-closes").value:preset;
    const schedule=this.openingHours(this.hours);
    this.schedule=schedule;
    this.hoursError="";
    if(schedule)this.hours=schedule.key;
    if(this.site){
      if(!schedule)this.hoursError="Enter different opening and closing times, or choose 24 hours.";
      else if(!schedule.withinReference&&!this.site.afterHours)
        this.hoursError="This archived market covers 08:00–20:00. Choose hours within that window to score this opening.";
    }
    const actions=this.playOpening?this.actions.values():this.site&&!this.hoursError?[[this.site.id,this.hours,null]]:[];
    const winners=chooseShops(occasions,this.sites,actions,this.openingHours,stopTiming);
    this.changes=[];this.overrides.clear();this.outingPlaces=new Map();this.bikeLegs=new Map();
    this.walks=new GroceryWalks(this.places,this.walkingGraph,this.payload.speed);
    this.walkers=[];
    for(const [j,[id,travel]] of winners){
      if(id===this.site?.id)this.changes.push([j,travel]);
    }
    this.walkLegs=new Map();this.walkHours=Array.from({length:28},()=>[]);this.walkTrips=0;this.liveWalks=[];
    let served=0,gained=0,focusedGains=0;const relocations=[];
    const shopCounts=new Map();
    occasions.forEach(([d,p,slot,,,old],j)=>{
      if(old>=0)served++;
      const choice=winners.get(j),place=choice?this.sitePlaces.get(choice[0]):this.storePlaces[old];
      if(choice){
        shopCounts.set(choice[0],(shopCounts.get(choice[0])??0)+1);
        if(old<0){gained++;if(choice[0]===this.site?.id)focusedGains++;}
      }
      if(place===undefined)return;
      const key=personKey(d,p);
      const row=occasions[j],area=this.places[place][2];
      const [arrive,leave]=stopTiming?.[j]??[row[3],row[3]+row[4]];
      const sharedWalk=this.walks.add(row,place,!!choice,[arrive,leave]);
      if(choice&&!sharedWalk&&row[13]!==undefined&&row[14]!==undefined){
        const mode=row[16]||"walk";
        this.walkers.push({d,i:p,start:arrive-row[11],end:arrive,from:row[13],to:place,mode},
                          {d,i:p,start:leave,end:leave+row[12],from:place,to:row[14],mode});
      }
      if(row[17]==="added-shopping")this.outingPlaces.set(key,place);
      else{
        if(!this.overrides.has(key))this.overrides.set(key,new Map());
        this.overrides.get(key).set(slot,place);
      }
      if(row[16]==="bike"){
        this.bikeLegs.set(key+"/"+(row[3]-row[11]),[row[13],place]);
        this.bikeLegs.set(key+"/"+(row[3]+row[4]),[place,row[14]]);
      }
      if(row[17]==="local"){
        this.walkTrips+=2;
        this.liveWalks.push([this.homeIndex[d],!!choice&&choice[0]===this.site?.id,old>=0,d,p,row[3]-row[11]/2]);
        for(const [s,n,a,b] of [[row[3]-row[11],row[11],row[13],place],[row[3]+row[4],row[12],place,row[14]]]){
          this.walkLegs.set(key+"/"+s,true);
          for(let h=Math.floor(s/60);h<=Math.floor((s+n-1)/60);h++)
            this.walkHours[h].push([d,p,s,n,a,b,this.catalog.localWalk.speed]);
        }
      }
      if(row.length>=13&&(area!==row[9]||row[17]==="local")){
        relocations.push([this.homeIndex[d],arrive,leave-arrive,row[9],area,row[8],row[10],row[11],row[12],row[16]||"walk",row[17]==="local"?"car-driver":row[16]||"walk"]);
      }
    });
    this.effects=this.payload.occasions[0]?.length>=13?this.project(this.day.areas.length,this.day.areas.indexOf("Downtown"),relocations):null;
    this.revision++;
    this.arrivals=this.changes.map(([j])=>j).sort((a,b)=>this.arrivalAt(a)-this.arrivalAt(b)||a-b);
    el("market-walk-legend").hidden=!(this.walks.proposals.length||this.walkers.length);
    this.lastMinute=null;
    const opened=[...this.actions.values()].sort((a,b)=>a[2]-b[2]).map(([id,,minute])=>({site:this.sites.get(id),minute}));
    this.showSites(sites.filter(s=>s.area===Number(el("market-area").value)),this.site,opened.map(r=>r.site));
    const openings=el("shop-openings");
    openings.hidden=this.actions.size===0;
    openings.replaceChildren(...opened.map(({site,minute})=>{
      const row=document.createElement("li"),button=document.createElement("button");
      button.type="button";button.textContent=site.name+" · "+clock(minute)+(minute>=1440?" +1":"");
      button.onclick=()=>this.focusSite(site);
      row.append(button," · "+count(shopCounts.get(site.id)??0)+" visits");
      return row;
    }));
    const visits=this.changes.length;
    el("save-opening").disabled=!this.canSave();
    el("shopping-shift-apply").disabled=this.playedAt!==null;
    for(const id of ["market-travel","market-local-walk","market-purchase","workplaces","commute-rule","zone-model","tour-mode"])
      el(id).disabled=this.actions.size>0||this.fixedCommute&&["workplaces","commute-rule","zone-model"].includes(id);
    for(const id of ["market-hours","market-opens","market-closes"])el(id).disabled=!this.site||this.playedAt!==null;
    el("market-locate").hidden=el("market-street").hidden=!this.site;
    el("market-result").textContent=this.site?count(visits)+" visits to this shop · "+count(visits-focusedGains)+" diverted from existing grocers · "+count(focusedGains)+" newly feasible.":
      count(served+gained)+" purchases fit a grocer. "+count(occasions.length-served-gained)+" grocery purchases are deferred.";
    el("market-compare").textContent=this.site?"Across the city, "+count(served+gained)+" purchases fit the day, compared with "+count(served)+" before opening.":"Choose a storefront on the map or in the scenario list.";
    const mix=el("market-travel-mix");mix.hidden=!this.site||!!this.hoursError||!this.catalog.bicycle;
    if(!mix.hidden){
      const bikes=this.changes.filter(([j])=>occasions[j][16]==="bike");
      const original=bikes.filter(([j])=>occasions[j][17]==="diary").length;
      mix.textContent=count(visits-bikes.length)+" visits on foot · "+count(original)+" by recorded cyclists · "+
        count(bikes.length-original)+" by drivers switching their outing to a bicycle.";
      if(this.catalog.localWalk)mix.textContent+=" Of those on foot, "+count(this.liveWalks.filter(r=>r[1]).length)+" originally drove.";
    }
    if(this.catalog.localWalk){
      if(!this.site)el("market-result").textContent=count(served+gained)+" walk or cycle purchases fit a grocer.";
      else el("market-compare").textContent=count(gained)+" additional visits fit on foot or by bicycle. Drivers may already have bought groceries by car.";
    }
    if(this.hoursError){el("market-result").textContent=this.hoursError;el("market-compare").textContent="";}
    else if(this.playOpening&&this.site&&this.playedAt===null){
      el("market-result").textContent=this.site.name+" is ready to open.";
      el("market-compare").textContent="";
    }
    renderResult(this.site&&!this.hoursError&&(!this.playOpening||this.playedAt!==null)?{
      label:this.site.name,value:count(visits)+" visits",intervention:true,
      note:"Modeled · "+(this.playedAt===null?"proposed schedule":"opens at "+clock(this.playedAt)),href:"#market"
    }:null);
    const demand=el("market-demand-results"),shopping=this.catalog.shoppingDemand;
    this.showSiteSensitivity?.(this.site?.id,this.hash);
    demand.hidden=!shopping;
    if(shopping){
      const added=this.changes.filter(([j])=>occasions[j][17]==="added-shopping").length;
      demand.textContent=this.site&&!this.hoursError&&(!this.playOpening||this.playedAt!==null)?
        count(visits-added)+" visits from recorded diaries and "+count(added)+" from fitted shopping walks.":
        count(shopping.grocery)+" grocery occasions drawn from the fitted shopping walks. "+
        count(shopping.feasible)+" fit an existing grocer.";
    }
    el("market-evening-evidence").hidden=!this.site||!!this.hoursError||schedule.withinReference;
    const people=el("market-person");people.replaceChildren();
    for(const [idx] of this.changes){
      const [d,i]=occasions[idx],origin=occasions[idx][17];
      const label=origin==="added-shopping"?" · added shopping walk":origin==="local"?" · former driver on foot":occasions[idx][16]==="bike"?" · bicycle":"";
      people.add(new Option(clock(this.arrivalAt(idx))+" · "+this.day.das[d]+"-P"+(i+1)+label,String(idx)));
    }
    if(this.linkedVisit?.has("visit")){
      const params=this.linkedVisit,selected=this.changes.find(([idx])=>{
        const [d,i,slot,start]=occasions[idx];
        return this.day.das[d]===params.get("da")&&i+1===Number(params.get("person"))&&slot===Number(params.get("visit"))&&start===Number(params.get("minute"));
      });
      if(selected){people.value=String(selected[0]);this.linkedVisit=null;}
    }
    el("market-examples").hidden=visits===0;
    el("market-customers").hidden=visits===0;
    if(visits)this.customers();
    this.reason();this.sales();this.householdResults();this.accessRender?.();this.evidenceRender?.();this.syncURL();
    this.clockPairLink?.();this.updateDemandLink?.();this.refresh();
  }
  async snapshot(){
    if(!this.site)throw Error("Choose a storefront to save its opening.");
    if(this.hoursError)throw Error(this.hoursError);
    if(this.playOpening&&this.playedAt===null)throw Error("Open the storefront before saving this playthrough.");
    if(!this.hash)throw Error("Saving an opening requires HTTPS or localhost.");
    const basket=el("market-basket");
    if(!basket.validity.valid)throw Error("Enter a valid nonnegative basket amount, or leave it blank.");
    const data={...this.versions,city:"vancouver",clock:this.clock,workplaces:this.workplaces,
      jointRun:new URL(location.href).searchParams.get("jointRun"),
      localWalk:this.catalog.localWalk?"full":null,shoppingOutings:this.shoppingOutings,
      rule:this.workplaces||this.catalog.bicycle?this.rule()||"diary":"diary",
      tours:this.catalog.bicycle?.tours,cycling:this.catalog.bicycle?.cycling,purchase:this.catalog.purchase?.key,
      market:this.hash,site:this.site.id,address:this.site.name,hours:this.hours,
      activated:this.playedAt,
      ...(this.actions.size>1?{openings:[...this.actions.values()]}:{}),
      basket:basket.value?basket.valueAsNumber:null,
      visits:this.changes.map(([j])=>{
        const [d,i,slot,start,,prior]=this.payload.occasions[j];
        return [this.day.das[d],i,slot,start,this.payload.stores[prior]?.name||"",this.payload.stores[prior]?.id??null,
          this.payload.occasions[j][16]||"walk"];
      })};
    await this.archive(data.market);
    return data;
  }
  householdResults(){
    if(!this.households||!this.householdPanel.open)return;
    const {sites,radii,counts,budgets,households}=this.households;
    const reach=el("household-reach"),access=el("household-access"),spend=el("household-spend");
    const index=sites.indexOf(this.site?.id);
    access.textContent="";spend.textContent="";
    if(index<0){
      reach.textContent=count(sum(households))+" private households citywide. Choose a storefront to see its walking catchment.";
      this.housingResults(index);
      return;
    }
    const radius=radii.indexOf(Number(el("household-radius").value));
    const [near,switched,newlyServed]=counts[radius][index];
    const budget=groups=>sum(groups.map((n,i)=>n*budgets[i]));
    reach.textContent=count(sum(near))+" households can walk here from home. Their combined annual food budget for purchases from stores is "+annual.format(budget(near))+". "+
      count(near[5])+" households use the province-wide average because their income is unresolved.";
    access.textContent="For "+count(sum(switched))+" households this shop is closer than an existing grocer within the walk limit. Another "+
      count(sum(newlyServed))+" gain their first grocer within that walk.";
    const share=el("household-share").valueAsNumber;
    spend.textContent=Number.isFinite(share)&&share>=0&&share<=100?
      annual.format((budget(switched)+budget(newlyServed))*share/100)+" per year at this shop if those households spend "+share+"% here.":
      "Enter a spending share from 0 to 100%.";
    this.housingResults(index,radius,share);
  }
  async loadHousing(folder,json,open){
    if(this.housing||this.housingRequest)return;
    const key=[this.versions.atlas,this.versions.day,this.versions.streets].join("_");
    this.housingRequest=housingRelease(folder,key,json,this.linkedVisit.get("housingRun"));
    const data=await this.housingRequest;
    if(!data)return;
    const {report}=data;
    if(Object.entries(this.versions).some(([field,value])=>report.versions[field]!==value)||
       report.spendingDigest!==this.households.sourceHash||
       ["sites","radii"].some(field=>report[field].join("/")!==this.households[field].join("/")))
      throw Error("The housing estimates and walking catchments use different releases.");
    this.housing=data;
    const choice=el("shelter-shock");
    choice.replaceChildren(...report.shocks.map(pct=>new Option(pct===0?"Recorded costs":pct+"% higher",String(pct))));
    const pct=this.linkedVisit.get("shelterShock");
    if(report.shocks.some(value=>String(value)===pct))choice.value=pct;
    el("household-housing-source").href=report.census;
    el("household-housing-status").textContent="";
    this.housingPanel.hidden=false;
    if(open)this.housingPanel.open=true;
    this.housingResults(report.sites.indexOf(this.site?.id),report.radii.indexOf(Number(el("household-radius").value)),
      el("household-share").valueAsNumber);
  }
  housingResults(index,radius,share){
    if(!this.housing||!this.housingPanel.open)return;
    const status=el("household-housing-status"),controls=el("household-housing-results");
    controls.hidden=index<0;
    status.textContent=index<0?"Choose a storefront to see its housing catchment.":"";
    if(index<0)return;
    const {report}=this.housing, pct=el("shelter-shock").value;
    const [near,switched,newly]=report.counts[radius][index];
    const get=(row,key)=>row[report.fields.indexOf(key)];
    const context=el("household-housing-context");
    const tenants=get(near,"tenants"),costKnown=get(near,"tenantCostsKnown"),valueKnown=get(near,"ownerValuesKnown");
    context.textContent=count(tenants)+" tenant households within walking distance."+
      (costKnown?" Estimated monthly tenant shelter cost averages "+annual.format(get(near,"tenantMonthlyShelter")/costKnown)+".":"")+
      (valueKnown?" Mean estimated owner dwelling value is "+annual.format(get(near,"ownerDwellingValue")/valueKnown)+".":"");
    const loss="foodLoss"+pct, reduction=get(near,loss),out=el("household-housing-spend");
    const customerBudget=get(switched,"food")+get(newly,"food");
    const adjusted=customerBudget-get(switched,loss)-get(newly,loss);
    out.textContent="Annual food budgets in this catchment change by "+annual.format(reduction===0?0:-reduction)+" across "+
      count(get(near,"tenantCashflowKnown"))+" tenant households with cost and positive income estimates."+
      (Number.isFinite(share)&&share>=0&&share<=100?" At a "+share+"% share, annual spending at the proposed shop moves from "+
      annual.format(customerBudget*share/100)+" to "+annual.format(adjusted*share/100)+".":"");
  }
  customers(){
    const bands=["Below $30,000","$30,000–59,999","$60,000–99,999","$100,000 or more","Unavailable"];
    const all=bands.map(()=>0),here=bands.map(()=>0),origins=new Map(),diaries=new Map();
    for(const row of this.payload.occasions)all[row[7]??4]++;
    for(const [i] of this.changes){
      const row=this.payload.occasions[i],area=this.homeArea.get(this.day.das[row[0]]);
      here[row[7]??4]++;origins.set(area,(origins.get(area)||0)+1);
      if(row[15]!==undefined)diaries.set(row[15],(diaries.get(row[15])||0)+1);
    }
    const support=el("market-diaries");
    support.hidden=!diaries.size;
    if(diaries.size){
      const visits=this.changes.length,largest=Math.max(...diaries.values());
      support.textContent="The "+count(visits)+(visits===1?" simulated visit uses ":" simulated visits use ")+count(diaries.size)+
        (diaries.size===1?" source diary.":" source diaries.")+
        (diaries.size>1&&largest>1?" The most frequently reused diary accounts for "+count(largest)+" visits.":"");
    }
    el("market-origins").textContent="Most frequent home neighbourhoods · "+[...origins].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]))
      .slice(0,3).map(([name,n])=>name+" ("+n+")").join(", ");
    el("market-income").replaceChildren(...bands.map((name,i)=>{
      const row=document.createElement("tr");
      for(const value of [name,count(here[i]),count(all[i])])row.insertCell().textContent=value;
      return row;
    }));
  }
  sales(){
    const basket=el("market-basket"),value=basket.valueAsNumber;
    el("market-sales").textContent=this.site&&!this.hoursError&&basket.value&&Number.isFinite(value)&&value>=0?
      money.format(value*this.changes.length)+" illustrative gross sales from these visits":"";
  }
  reason(){
    if(!this.changes.length)return;
    const idx=Number(el("market-person").value),row=this.payload.occasions[idx],old=this.payload.stores[row[5]];
    const [,mins]=this.changes.find(([j])=>j===idx);
    const [d,i,,minute]=row,bike=row[16]==="bike";
    el("market-reason").textContent=old?(bike?"Ride":"Walk")+" via "+old.name+" takes "+row[6].toFixed(1)+" min. Via this shop it takes "+mins.toFixed(1)+" min.":
      "No visit to an existing grocer fits "+(bike?"by bicycle":"on foot")+". This shop fits with "+mins.toFixed(1)+" min of "+(bike?"cycling.":"walking.");
    const reference=el("market-reference");
    reference.hidden=!this.hash;
    if(this.hash)reference.href=referenceReplay(location.href,{market:this.hash,da:this.day.das[d],person:i+1,minute,
      commute:this.workplaces?this.rule():null,cycleTours:this.catalog.bicycle?this.rule():null});
  }
  async inspect(){
    if(!this.changes.length)return;
    const index=Number(el("market-person").value),[d,i]=this.payload.occasions[index];
    await this.follow(this.day.das[d],i,this.arrivalAt(index));
  }
  arrivalAt(index){return this.payload.stopTiming?.[index]?.[0]??this.payload.occasions[index][3];}
  atMinute(time){
    if(!this.active||!this.payload)return;
    const minute=Math.floor(time);
    if(this.lastMinute===minute)return;
    this.lastMinute=minute;
    this.playStatus(minute);
    const now=el("market-now"),button=el("market-next");
    const streetStatus=el("shop-play-map-status");
    streetStatus.hidden=this.playedAt===null;
    now.hidden=!this.site||!!this.hoursError;button.hidden=!this.arrivals.length;
    if(now.hidden)return;
    const occasions=this.payload.occasions;
    let present=0,arrived=0;
    this.next=null;
    for(const j of this.arrivals){
      const arrival=this.arrivalAt(j),row=occasions[j];
      if(minute<arrival){if(this.next===null)this.next=j;continue;}
      arrived++;
      if(minute<(this.payload.stopTiming?.[j]?.[1]??row[3]+row[4]))present++;
    }
    if(!streetStatus.hidden){
      const status=minute<this.playedAt?"Opens at "+clock(this.playedAt):this.coversMinute(minute)?"Shop open":"Shop closed";
      streetStatus.textContent=status+" · "+count(arrived)+" arrivals";
    }
    if(this.next===null)this.next=this.arrivals[0]??null;
    now.textContent=clock(minute)+" · "+count(present)+" in the shop · "+count(arrived)+" of "+count(this.arrivals.length)+" visits have arrived.";
    if(this.next!==null)button.textContent=(arrived===this.arrivals.length?"Replay first arrival at ":"Follow next arrival at ")+clock(this.arrivalAt(this.next));
  }
  slots(d,index){return this.overrides.get(personKey(d,index));}
  outingPlace(d,index){return this.outingPlaces.get(personKey(d,index));}
  cycleLeg(d,index,start){return this.bikeLegs?.get(personKey(d,index)+"/"+start);}
}
