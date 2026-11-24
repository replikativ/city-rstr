const release=/^[a-f0-9]{20}$/;
const el=id=>document.getElementById(id);
const fmt=n=>n.toLocaleString("en-CA");
const time=minute=>String(Math.floor(minute/60)).padStart(2,"0")+":00";

export async function jointWeekday(root,id,json){
  if(!release.test(id))throw Error("Invalid combined weekday release.");
  const path=root+"joint-weekday/"+id+"/";
  const report=await json(path+"report.json");
  const {atlas,day,streets}=report.versions;
  const works=report.workplaces;
  if(![atlas,day,streets,report.outings,report.riders,report.transit,report.commuters,
    works.outbound,works.worksites,works["tract-workplaces"]].every(v=>release.test(v))||
    (report.directJoint&&!release.test(report.directJoint))||report.commuteRule!=="tracts")
    throw Error("The combined weekday has inconsistent source versions.");
  return {...report,id,path,root};
}

export async function showJointLink(root,versions,params,preferRepaired=false){
  const {atlas,day,streets}=versions;
  const path=root+"joint-weekday/"+[atlas,day,streets].join("_");
  let response=preferRepaired?await fetch(path+"_repaired_capacity.json"):null;
  if(!response||response.status===404)response=await fetch(path+".json");
  if(response.status===404)return;
  if(!response.ok)throw Error("The combined weekday comparison is unavailable.");
  const {version}=await response.json();
  if(!release.test(version))throw Error("Invalid combined weekday release.");
  const link=el("joint-replay"),url=new URL("cityday.html",location.href);
  const minute=params.get("minute");
  if(minute)url.searchParams.set("minute",minute);
  if(params.has("dayRun"))url.searchParams.set("dayRun",params.get("dayRun"));
  for(const [key,value] of Object.entries({jointRun:version,downtown:"am",commuters:"combined"}))
    url.searchParams.set(key,value);
  url.hash="joint-weekday";
  link.href=url;
  el("joint-weekday").hidden=false;
}

export function attachJointEvidence(joint,json,follow,showSite,followTransfer,referenceRun,incomingVersion=null){
  const panel=el("joint-weekday"),select=el("joint-site"),link=el("joint-replay");
  const home=new URL("cityday.html",location.href);
  home.searchParams.set("downtown","am");
  if(referenceRun)home.searchParams.set("dayRun",referenceRun);
  home.hash="downtown";
  link.href=home;link.textContent=referenceRun?"Replay the fitted diaries":"Replay the original city weekday";
  const cycling=joint.activeModeDelta?.Cycling;
  const cyclingChange=joint.preserveDiaryModes?" The workplace assignments keep the diary travel modes.":
    referenceRun&&cycling?" The workplace mode assignments give "+fmt(Math.round(Math.abs(cycling)))+
      (cycling<0?" fewer":" more")+" adult cycling trips than the fitted diaries.":"";
  el("joint-description").textContent=fmt(joint.shoppingOutings)+" fitted shopping outings and "+
    fmt(joint.shortWalks)+" reconstructed walks share the census workplace weekday. Transit is matched to the revised addresses."+
    cyclingChange;
  if(joint.transfers){
    const {added,direct,example}=joint.transfers;
    el("joint-transfer").hidden=false;
    el("joint-transfer-note").textContent=fmt(direct)+" trips use one vehicle. "+fmt(added)+
      " more fit a single change of vehicle within their existing travel time.";
    const button=el("joint-transfer-follow");
    button.hidden=!example;
    button.onclick=()=>followTransfer().catch(e=>{el("joint-transfer-note").textContent=e.message;});
    if(joint.directJoint){
      const direct=el("joint-direct-replay");
      const link=new URL(location.href);
      link.searchParams.set("jointRun",joint.directJoint);
      link.searchParams.delete("incomingTransit");
      link.hash="joint-weekday";
      direct.href=link;el("joint-transfer-reference").hidden=false;
    }
  }
  const detail=el("joint-counts");
  const reachNote=el("joint-walk-reach");
  const incomingNote=el("joint-commuter-walks");
  let pending,reachPending,reachSites,incomingSites;
  detail.ontoggle=()=>{
    if(!detail.open){showSite(null);return;}
    pending??=json(joint.path+"pedestrians.json").then(report=>{
      if(report.tracts!==joint.workplaces["tract-workplaces"]||report.transit.riders!==joint.riders||
         Object.entries(joint.versions).some(([k,v])=>report[k]!==v))
        throw Error("Pedestrian counts and combined replay differ.");
      for(const [i,site] of report.sites.entries())select.add(new Option(site.name,String(i)));
      const requested=new URLSearchParams(location.search).get("jointSite");
      if(requested!==null&&report.sites[requested])select.value=requested;
      const drawReach=()=>{
        const current=reachSites?.[select.value];
        const [ten,quarter]=current?.networkBounds??[];
        reachNote.hidden=!(ten&&quarter);
        if(!ten||!quarter)return;
        const largestGap=current.observed.reduce((largest,count,i)=>
          count-quarter.hourly[i]>(largest<0?0:current.observed[largest]-quarter.hourly[largest])?i:largest,-1);
        reachNote.textContent="Keeping the same addresses and travel windows, the upper limits are "+fmt(ten.unique)+
          " resident walks across the recorded hours with paths up to 10% longer than the shortest, and "+fmt(quarter.unique)+" at 25%."+
          (largestGap<0?"":" At "+time(current.hours[largestGap])+", the 25% limit is "+fmt(quarter.hourly[largestGap])+
          " compared with "+fmt(current.observed[largestGap])+" observed.");
      };
      const drawIncoming=()=>{
        const site=incomingSites?.[select.value];
        incomingNote.hidden=!site;
        if(!site)return;
        const total=rows=>rows.reduce((a,b)=>a+b,0),added=total(site.added);
        incomingNote.textContent="Scheduled incoming work trips add "+fmt(added)+" walking passages in these hours. "+
          fmt(total(site.resident)+added)+" passages come from residents and incoming workers together.";
      };
      const draw=(focus=false)=>{
        const site=report.sites[select.value],body=el("joint-hours");
        const sum=rows=>rows.reduce((a,b)=>a+b,0);
        el("joint-count-status").textContent=fmt(sum(site.baseline))+" baseline weekday · "+fmt(sum(site.joint))+
          " combined · "+fmt(sum(site.observed))+" observed during the recorded hours.";
        body.replaceChildren();
        for(const [j,h] of site.hours.entries()){
          const row=body.insertRow();
          for(const value of [time(h),fmt(site.baseline[j]),fmt(site.joint[j]),fmt(site.observed[j])])
            row.insertCell().textContent=value;
          const example=["transfer","shopping","access","egress","inferred","tracts"].map(k=>site.examples[k]?.[j]).find(Boolean);
          if(example){
            const control=document.createElement("button");
            control.textContent="Follow";
            control.setAttribute("aria-label","Follow a resident at "+time(h));
            control.onclick=()=>follow(...example.slice(0,3)).catch(e=>{el("joint-count-status").textContent=e.message;});
            row.insertCell().append(control);
          }else row.insertCell();
        }
        const source=el("joint-count-source");
        source.href=site.source;source.textContent="City count sheet · "+site.date;
        drawReach();
        drawIncoming();
        showSite(site.point,report.radius,focus);
      };
      reachPending??=fetch(joint.root+"walk-reach/"+joint.id+".json").then(async response=>{
        if(response.status===404)return;
        if(!response.ok)throw Error("Unable to load the walking route comparison.");
        const {version}=await response.json();
        if(!release.test(version))throw Error("Invalid walking route comparison release.");
        const evidence=await json(joint.root+"walk-reach/"+version+"/report.json");
        if(evidence.joint!==joint.id||evidence.tracts!==report.tracts||evidence.riders!==joint.riders||
           Object.entries(joint.versions).some(([key,value])=>evidence[key]!==value)||
           evidence.sites.length!==report.sites.length||evidence.sites.some(({name,hours},i)=>
             name!==report.sites[i].name||hours.join()!==report.sites[i].hours.join()))
          throw Error("The walking route comparison uses different inputs.");
        reachSites=evidence.sites;
        drawReach();
      }).catch(error=>{reachNote.textContent=error.message;reachNote.hidden=false;});
      if(joint.transfers){
        const fetchOptional=async url=>{
          const response=await fetch(url);
          if(response.status===404)return null;
          if(!response.ok)throw Error("Unable to load counts from incoming commute walks.");
          return response.json();
        };
        const pinned=incomingVersion?Promise.resolve(incomingVersion):
          fetchOptional(joint.root+"incoming-transit/"+joint.id+".json").then(point=>point?.version);
        pinned.then(async version=>{
          if(!version)return;
          if(!release.test(version))throw Error("Invalid incoming transit release.");
          const evidence=await fetchOptional(joint.root+"incoming-pedestrians/"+version+".json");
          if(!evidence)return;
          if(evidence.joint!==joint.id||evidence.incoming!==version||evidence.radius!==report.radius||
             evidence.sites.length!==report.sites.length||evidence.sites.some(({name,hours,resident},i)=>
               name!==report.sites[i].name||hours.join()!==report.sites[i].hours.join()||resident.join()!==report.sites[i].joint.join()))
            throw Error("Incoming commuter counts use a different pedestrian comparison.");
          incomingSites=evidence.sites;
          drawIncoming();
        }).catch(error=>{incomingNote.textContent=error.message;incomingNote.hidden=false;});
      }
      select.onchange=()=>{
        const url=new URL(location.href);
        url.searchParams.set("jointSite",select.value);
        history.replaceState(null,"",url);draw(true);
      };
      el("joint-intersections").hidden=false;
      return draw;
    }).catch(e=>{pending=null;el("joint-count-status").textContent=e.message;});
    pending.then(draw=>{if(detail.open)draw?.();});
  };
  detail.hidden=false;panel.hidden=false;panel.open=true;
  if(new URLSearchParams(location.search).has("jointSite"))detail.open=true;
}

export async function attachDiaryFit(root,versions,day,json,time){
  const {atlas,day:dayId,streets}=versions;
  const basis=day.diaryFit,baseAtlas=basis?.baselineAtlas??atlas,baseDay=basis?.baselineDay??dayId;
  const zonal=basis?.kind==="income-and-home-zone";
  const directory=root+"diary-fit/";
  const response=await fetch(directory+baseAtlas+"_"+baseDay+".json");
  if(response.status===404&&!basis)return;
  if(!response.ok)throw Error("The income-fitted weekday is unavailable.");
  const {baselineRun,fittedRun,fittedAtlas,zoneRun,zonalAtlas}=await response.json();
  if(![baselineRun,fittedRun].every(id=>/^[a-f0-9]{64}$/.test(id))||!release.test(fittedAtlas))
    throw Error("Invalid income-fitted weekday release.");
  const selectedAtlas=zonal?zonalAtlas:fittedAtlas;
  if(!release.test(selectedAtlas))throw Error("Invalid home-zone diary release.");
  const data=await json(directory+selectedAtlas+".json");
  if(data.atlas!==baseAtlas||data.fittedAtlas!==selectedAtlas||data.locations.streets!==streets||
     basis&&(data.locations.day!==dayId||selectedAtlas!==atlas))
    throw Error("The income fit and weekday have different inputs.");
  const low=data.results[0],transit=data.units.indexOf("Transit");
  const share=row=>(100*row[transit]/row.slice(0,6).reduce((sum,n)=>sum+n,0)).toFixed(1)+"%";
  el("diary-fit-summary").textContent="Among adults in households earning under $25,000, the original diaries put "+
    share(low.assigned.original)+" of trips on transit. The fitted diaries put "+share(low.assigned.fitted)+" on transit.";
  el("diary-fit-method").textContent="The weekday keeps the same residents and homes and reassigns whole diaries within age and activity groups. "+
    (zonal?"The fit uses household income, home-zone mode shares and the citywide trip rate. ":"")+
    "These shares count the travel recorded in the diaries before routing and timetable checks.";
  if(data.scheduled){
    const {original,fitted}=data.scheduled;
    const schedule=el("diary-fit-schedule");
    schedule.textContent="Across the city, "+fmt(original.matched)+" of "+fmt(original.bouts)+" original transit bouts and "+
      fmt(fitted.matched)+" of "+fmt(fitted.bouts)+" fitted transit bouts match a direct scheduled ride.";
    schedule.hidden=false;
  }
  el("diary-fit-source").href=data.source;
  const link=el("diary-fit-replay");
  const href=()=>link.href="cityday.html?dayRun="+(basis?baselineRun:fittedRun)+"&minute="+Math.floor(time())+"#diary-fit";
  href();
  link.onpointerdown=href;
  link.onfocus=href;
  link.textContent=basis?"Replay the original weekday":"Replay the income-fitted weekday";
  const panel=el("diary-fit");
  panel.hidden=false;
  if(basis||location.hash==="#diary-fit")panel.open=true;
  if(zoneRun&&/^[a-f0-9]{64}$/.test(zoneRun)&&release.test(zonalAtlas)){
    const other=el("diary-fit-zonal-replay");
    const update=()=>other.href="cityday.html?dayRun="+(zonal?fittedRun:zoneRun)+"&minute="+Math.floor(time())+"#diary-zone-check";
    update();other.onpointerdown=update;other.onfocus=update;
    other.textContent=zonal?"Replay income-only diaries":"Replay diaries fitted by income and home zone";
    other.hidden=false;
  }
  await attachDiaryZoneCheck(directory,fittedAtlas,baseAtlas,zonalAtlas);
  const booked=zoneRun&&zonalAtlas?await attachDiaryCapacity(directory,zoneRun,zonalAtlas,zonal,time):null;
  const direct=zonal?booked:data.scheduled?.fitted.riders;
  if(!direct)return;
  const suffix=zonal?"_booked_transfers.json":"_transfers.json";
  const connectionResponse=await fetch(directory+selectedAtlas+suffix);
  if(connectionResponse.status===404)return;
  if(!connectionResponse.ok)throw Error("The fitted transfer comparison is unavailable.");
  const connections=await connectionResponse.json();
  if(connections.atlas!==selectedAtlas||connections.day!==data.locations.day||!release.test(connections.riders)||
     connections.comparison.sourceRelease!==direct)
    throw Error("The fitted transfer comparison uses different direct journeys.");
  const transferLink=el("diary-fit-transfer-replay");
  const active=basis&&new URLSearchParams(location.search).get("riderRun")===connections.riders;
  const dayRun=zonal?zoneRun:fittedRun;
  const transferHref=()=>{
    const query=new URLSearchParams({dayRun,minute:String(Math.floor(time()))});
    if(!active)query.set("riderRun",connections.riders);
    else if(zonal)query.set("riderRun",direct);
    transferLink.href="cityday.html?"+query+"#diary-fit";
  };
  transferHref();
  transferLink.onpointerdown=transferHref;
  transferLink.onfocus=transferHref;
  transferLink.textContent=active?(zonal?"Replay booked direct rides":"Replay direct rides"):"Replay scheduled transfers";
  const lowIncome=connections.income?.[0];
  const bookedShare=lowIncome?.linkedTrips>0?100*(lowIncome.direct+lowIncome.transfers)/lowIncome.linkedTrips:null;
  el("diary-fit-transfer-count").textContent=fmt(connections.comparison.added)+
    " additional transit bouts fit one transfer and the bus capacity check."+
    (zonal?" All booked journeys fit the modeled bus capacity limits.":"")+
    (bookedShare===null?"":" In the lowest income bracket, "+bookedShare.toFixed(1)+
      "% of all adult trips match a scheduled transit journey in this replay.");
  if(connections.comparison.example){
    const [da,i,minute]=connections.comparison.example;
    const example=el("diary-fit-transfer-example");
    const query=new URLSearchParams({dayRun,riderRun:connections.riders,da,person:String(i+1),
                                     minute:String(minute+.1),follow:"1"});
    example.href="cityday.html?"+query+"#diary-fit";
    example.hidden=false;
  }
  el("diary-fit-transfers").hidden=false;
}

async function attachDiaryCapacity(directory,zoneRun,atlas,zonal,time){
  const response=await fetch(directory+atlas+"_capacity.json");
  if(response.status===404)return;
  if(!response.ok)throw Error("The fitted bus capacity comparison is unavailable.");
  const {atlas:reportAtlas,riders,comparison}=await response.json();
  if(reportAtlas!==atlas||!release.test(riders))throw Error("The bus capacity comparison uses a different weekday.");
  const active=zonal&&new URLSearchParams(location.search).get("riderRun")===riders;
  const link=el("diary-fit-capacity-replay"),setLink=()=>{
    const query=new URLSearchParams({dayRun:zoneRun,minute:String(Math.floor(time()))});
    if(!active)query.set("riderRun",riders);
    link.href="cityday.html?"+query+"#diary-fit";
  };
  setLink();link.onpointerdown=setLink;link.onfocus=setLink;
  link.textContent=active?"Replay the timetable-only matches":"Replay with bus capacity limits";
  el("diary-fit-capacity-count").textContent=fmt(comparison.admitted)+" direct journeys fit the timetable and capacity limits. "+
    fmt(comparison.rerouted)+" use another scheduled ride and "+fmt(comparison.rejected)+" lack space within their window.";
  el("diary-fit-capacity").hidden=false;
  return riders;
}

async function attachDiaryZoneCheck(directory,fittedAtlas,baseAtlas,zonalAtlas){
  const response=await fetch(directory+fittedAtlas+"_zone-check.json");
  if(response.status===404)return;
  if(!response.ok)throw Error("The weekday home-zone comparison is unavailable.");
  const report=await response.json();
  if(report.runs[0]?.atlas!==baseAtlas||report.runs[1]?.atlas!==fittedAtlas)
    throw Error("The home-zone comparison uses different diaries.");
  const runs=report.runs.filter(run=>[baseAtlas,fittedAtlas,zonalAtlas].includes(run.atlas));
  const picker=el("diary-zone-selector"),header=el("diary-zone-header"),rows=el("diary-zone-rows");
  for(const {code,name} of report.zones)picker.add(new Option(name,code));
  const points=run=>run.meanError.toFixed(1);
  el("diary-zone-error").textContent="Across nine home zones and five modes, the original weekday averages "+
    points(runs[0])+" percentage points of error and the income fit averages "+points(runs[1])+
    (runs.length===3?". The income and home-zone fit averages "+points(runs[2])+".":".");
  const rate=run=>((run.cityTrips+run.unclassified)/run.adults).toFixed(2);
  const surveyRate=(report.surveyCity.trips/report.surveyCity.adults).toFixed(2);
  el("diary-zone-rate").textContent="Trips per adult per day · "+rate(runs[0])+" original · "+rate(runs[1])+" income fit"+
    (runs.length===3?" · "+rate(runs[2])+" income and home-zone fit":"")+" · "+surveyRate+" in the 2025 survey.";
  const labels=["Original","Income fit",...(runs.length===3?["Income and zone fit"]:[]),"2025 survey"];
  for(const label of labels){
    const cell=document.createElement("th");cell.scope="col";cell.textContent=label;header.append(cell);
  }
  const draw=()=>{
    const code=picker.value;rows.replaceChildren();
    const selected=report.zones.find(z=>z.code===code);
    const predicted=runs.map(run=>run.zones.find(z=>z.code===code).shares);
    for(const [i,mode] of report.modes.entries()){
      const row=rows.insertRow();
      for(const value of [mode,...predicted.map(shares=>shares[i].toFixed(1)+"%"),selected.observed[i]+"%"])
        row.insertCell().textContent=value;
    }
  };
  picker.onchange=draw;draw();
  el("diary-zone-source").href=report.source+"#page=54";
  const panel=el("diary-zone-check");
  panel.hidden=false;
  if(location.hash==="#diary-zone-check"){
    panel.open=true;el("diary-fit").open=true;
  }
}

export async function attachIncomeComparison(joint,json,vehicle=null){
  const directory=joint.root+"income-travel/";
  const response=await fetch(directory+joint.id+".json");
  if(response.status===404)return;
  if(!response.ok)throw Error("The household income comparison is unavailable.");
  const {version}=await response.json();
  if(!release.test(version))throw Error("Invalid household income comparison release.");
  const panel=el("income-trip-modes"),status=el("income-trip-status"),picker=el("income-trip-band");
  let pending;
  const load=()=>{
    if(!panel.open)return;
    pending??=Promise.all([json(directory+version+"/report.json"),vehicle]).then(([report,access])=>{
      if(report.joint!==joint.id||Object.entries(joint.versions).some(([k,v])=>report.versions[k]!==v))
        throw Error("The household income comparison belongs to a different weekday.");
      for(const [i,band] of report.bands.entries())picker.add(new Option(band,String(i)));
      const selected=new URLSearchParams(location.search).get("incomeBand");
      if(selected!==null&&report.bands[selected])picker.value=selected;
      const sum=a=>a.reduce((n,x)=>n+x,0);
      const percent=(n,total)=>total?(100*n/total).toFixed(1)+"%":"—";
      const surveyPercent=value=>value==null?"—":value+"%";
      const survey2023=report.survey2023;
      el("income-vehicle-header").hidden=!access;
      el("income-survey-2023-header").hidden=!survey2023;
      if(survey2023){
        el("income-survey-2023-source").href=survey2023.source;
        el("income-survey-2023-source").hidden=false;
      }
      function draw(){
        const i=Number(picker.value),rows=el("income-trip-rows"),original=report.original[i],combined=report.combined[i];
        const originalTotal=sum(original),combinedTotal=sum(combined);
        rows.replaceChildren();
        for(const [j,mode] of report.modes.entries()){
          const row=rows.insertRow();
          const changed=access?[percent(combined[j]+access.report.modeDelta[i][j],combinedTotal)]:[];
          const observed=[surveyPercent(report.observed[i]?.[j])];
          if(survey2023)observed.push(surveyPercent(survey2023.shares[i]?.[j]));
          for(const cell of [mode,percent(original[j],originalTotal),percent(combined[j],combinedTotal),...changed,...observed])
            row.insertCell().textContent=cell;
        }
        status.textContent="Estimated trips by adult residents · "+report.bands[i];
        el("income-trip-coverage").textContent=fmt(Math.round(report.adults[i]))+" adults · "+
          fmt(Math.round(originalTotal))+" original trips · "+fmt(Math.round(combinedTotal))+" combined trips.";
        el("income-survey-2023-band-note").hidden=survey2023?.shares[i]!==null;
      }
      picker.onchange=()=>{
        const url=new URL(location.href);url.searchParams.set("incomeBand",picker.value);
        history.replaceState(null,"",url);draw();
      };
      el("income-trip-source").href=report.survey.source;
      const diaryPool=report.diaryPool,low=diaryPool?.byIncome[0];
      if(low?.donors){
        const trips=sum(low.weightedTrips),transit=low.weightedTrips[report.modes.indexOf("Transit")];
        el("income-diary-description").textContent=fmt(low.donors)+" urban B.C. weekday respondents aged "+
          diaryPool.minimumAge+" or older lived alone and earned under $25,000. Their weighted trips were "+
          percent(transit,trips)+" transit. The Vancouver survey covers residents across household sizes.";
        el("income-diary-source").href=diaryPool.source;
        el("income-diary-support").hidden=false;
      }
      el("income-trip-evidence").hidden=false;draw();
    }).catch(e=>{pending=null;status.textContent=e.message;});
  };
  panel.ontoggle=load;
  panel.hidden=false;
  if(location.hash==="#income-trip-modes"||new URLSearchParams(location.search).has("incomeBand")){
    const jointPanel=el("joint-weekday");
    jointPanel.hidden=false;jointPanel.open=true;panel.open=true;
  }
  load();
}
