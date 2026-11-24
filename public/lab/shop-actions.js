function candidates(site,schedule){
  return schedule.withinReference?site.changes:[...site.changes,...site.afterHours];
}

// The catalogue retains only proposals that beat the incumbent. An occasion
// goes to the feasible proposal with the shortest combined trip, at departure.
export function chooseShops(occasions,sites,actions,openingHours,stopTiming){
  const winners=new Map();
  const ordered=[...actions].sort(([a,,first],[b,,second])=>first-second||(a<b?-1:a>b?1:0));
  for(const [id,hours,minute] of ordered){
    const site=sites.get(id), schedule=openingHours(hours);
    for(const [index,travel] of candidates(site,schedule)){
      const row=occasions[index];
      const arrive=stopTiming?.[index]?.[0]??row[3],depart=arrive-row[11];
      const fits=minute===null?schedule.admits(row[3],row[4]):
        schedule.admitsAfterActivation(minute,row[3],row[4],row[3]-depart);
      const previous=winners.get(index);
      if(fits&&(!previous||travel<previous[1]))winners.set(index,[id,travel]);
    }
  }
  return winners;
}

export function readOpenings(params){
  if(params.has("openings")){
    const rows=JSON.parse(params.get("openings"));
    if(!Array.isArray(rows))throw Error("Expected a list of storefront openings.");
    return rows;
  }
  if(params.has("opened")){
    return [[params.get("shop"),params.get("hours")??"full",Number(params.get("opened"))]];
  }
  return [];
}

export function referenceReplay(href,{market,da,person,minute,commute,cycleTours}){
  const source=new URL(href),url=new URL(source.pathname,source.origin);
  for(const key of ["walks","bikeRoutes","terrain","jointRun"]){
    if(source.searchParams.has(key))url.searchParams.set(key,source.searchParams.get(key));
  }
  if(url.searchParams.has("jointRun"))for(const key of ["dayRun","incomingTransit","outboundRoad","outboundTransit","outboundClock","shoppingClock"]){
    if(source.searchParams.has(key))url.searchParams.set(key,source.searchParams.get(key));
  }
  for(const [key,value] of Object.entries({marketRun:market,shop:"baseline",da,person,minute,follow:"1",commute,cycleTours})){
    if(value!=null)url.searchParams.set(key,value);
  }
  return url;
}
