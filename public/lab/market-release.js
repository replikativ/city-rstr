const release=/^[a-f0-9]{20}$/;
const digest=/^[a-f0-9]{64}$/;

export async function archivedRun(root, hash, json){
  if(!digest.test(hash))throw Error("Invalid saved market release.");
  const path=root+"market/archive/"+hash+"/";
  const run=await json(path+"run.json");
  if(run.market!==hash||run.city!=="vancouver"||![run.atlas,run.day,run.streets].every(v=>release.test(v))||
     (run.clock&&!release.test(run.clock))||
     (run.clockKind&&(run.clockKind!=="spread-departures"||!run.clock||run.workplaceRuns))||
     (run.tours&&(!release.test(run.tours)||!release.test(run.cycling)||run.clock||run.workplaceRuns))||
     (run.jointRun&&(!release.test(run.jointRun)||!run.shoppingOutings||!run.workplaceRuns))||
     (run.shoppingOutings&&(!release.test(run.shoppingOutings)||run.tours||run.clock||(run.workplaceRuns&&!run.jointRun)))||
     (run.workplaceRuns&&(!run.workplaceRuns.outbound||!Object.values(run.workplaceRuns).every(v=>release.test(v)))))
    throw Error("The saved market has inconsistent source versions.");
  return {...run,path};
}

export async function shoppingDemandPair(root, versions, joint){
  const {atlas,day,streets}=versions;
  const key=joint?.id??[atlas,day,streets].join("_");
  const response=await fetch(root+"market/demand_"+key+".json");
  if(response.status===404)return null;
  if(!response.ok)throw Error("The shopping demand comparison is unavailable.");
  const pair=await response.json();
  if(![pair.market,pair.baseMarket].every(v=>digest.test(v))||!release.test(pair.outings)||
     pair.jointRun!==joint?.id||(joint&&pair.outings!==joint.outings)||
     Object.entries(versions).some(([k,v])=>pair[k]!==v))
    throw Error("The shopping demand comparison and weekday differ.");
  return pair;
}

export async function marketCatalogue(url, expected, fallback){
  let response=await fetch(url);
  if(response.status===404&&fallback&&!expected)response=await fetch(fallback);
  if(!response.ok)throw Error("Unable to load the grocery catalogue.");
  const bytes=await response.arrayBuffer();
  const catalog=JSON.parse(new TextDecoder().decode(bytes));
  if(catalog.clockKind==="spread-departures"&&catalog.stopTiming?.length!==catalog.occasions.length)
    throw Error("The grocery catalogue is missing its shifted trip times.");
  // Ordinary replay can also run from HTTP origins without Web Crypto.
  const hash=crypto.subtle?Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)),
    n=>n.toString(16).padStart(2,"0")).join(""):null;
  if(expected&&hash!==expected)throw Error("The catalogue differs from the saved experiment.");
  return {catalog,hash};
}
