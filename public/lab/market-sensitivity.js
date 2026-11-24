const el=id=>document.getElementById(id);

export function attachSiteSensitivity(load){
  const panel=el("market-site-sensitivity"),rows=el("market-site-sensitivity-rows");
  let selected,pending;
  return async (site,market)=>{
    const key=site+"/"+market;
    if(key===selected)return;
    selected=key;panel.hidden=true;
    if(site!=="3738")return;
    try{
      pending??=load(site);
      const result=await pending;
      if(!result||selected!==key||!result.report.markets.includes(market))return;
      const {report,url}=result;
      rows.replaceChildren();
      for(const {minute,recorded,augmented} of report.cases){
        const row=rows.insertRow(),title=document.createElement("th");title.scope="row";
        title.textContent=minute===null?"Scheduled 08:00":String(minute/60)+":00";
        row.append(title);
        for(const n of [recorded.visits,augmented.visits,augmented.diverted])
          row.insertCell().textContent=n.toLocaleString();
      }
      const noon=report.cases.find(row=>row.minute===720).augmented;
      const access=report.access;
      el("market-site-sensitivity-context").textContent=
        "All cases close at 20:00. The noon case has "+noon.visits+" modeled visits, including "+
        noon.largestDiary+" from the most reused diary.";
      el("market-site-sensitivity-access").textContent=
        "Can-FED finds an existing grocer within 1 km at "+access.observedAccess+" of "+access.comparable+
        " Hastings-Sunrise census points. The model finds "+access.modeledAccess+". All "+
        access.gainedAreas+" points gaining their first grocer in the model already have access in Can-FED. This measures proximity to stores.";
      el("market-site-sensitivity-source").href=access.source;
      el("market-site-sensitivity-data").href=url;
      panel.hidden=false;
    }catch(error){pending=null;console.warn(error.message);}
  };
}
