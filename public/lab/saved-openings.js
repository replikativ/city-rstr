import {openingHours} from "../js/vancouver/workplaces.js";

import {openingLink as replay} from "../js/experiments/saved.js";

const el=id=>document.getElementById(id);
const hours=value=>openingHours(value)?.label??value;
const time=minute=>String(Math.floor(minute/60)%24).padStart(2,"0")+":"+String(minute%60).padStart(2,"0");
const opened=minute=>"opened at "+time(minute)+(minute>=1440?" +1":"");
const money=new Intl.NumberFormat("en-CA",{style:"currency",currency:"CAD"});
const key=visit=>visit[0]+"/"+visit[1];

export function init(snapshot){
  const status=el("saved-status"),select=el("saved-opening"),compare=el("saved-compare"),shopper=el("saved-person");
  let current,otherRecord,shown=[],visitRun,revision=0,comparison=0;
  const load=()=>import("../js/experiments/saved.js");
  const fail=e=>{status.textContent=e.message||String(e);};
  const follow=()=>{
    const visit=shown[Number(shopper.value)];
    el("saved-follow").hidden=!visit;
    if(visit)el("saved-follow").href=replay(visitRun,visit);
  };
  const shoppers=()=>{
    const group=el("saved-group").value;
    visitRun=group==="second"?otherRecord:current;
    const others=new Set((group==="second"?current:otherRecord)?.visits.map(key));
    shown=visitRun?.visits||[];
    if(group!=="all")shown=shown.filter(v=>group==="shared"?others.has(key(v)):!others.has(key(v)));
    shopper.replaceChildren(...shown.map((v,i)=>new Option(time(v[3])+" · "+v[0]+"-P"+(v[1]+1)+(v[5]==="bike"?" · bicycle":v[2]===-1?" · added shopping walk":"")+" · "+
      (v[4]?"from "+v[4]:"newly feasible"),String(i))));
    el("saved-person-label").hidden=!shown.length;follow();
  };
  const difference=async()=>{
    const ticket=++comparison,other=compare.value,first=current,out=el("saved-difference");
    out.textContent="";otherRecord=null;el("saved-group-label").hidden=true;el("saved-group").value="all";shoppers();
    if(!other||!first)return;
    const second=await (await load()).details(other);
    if(ticket!==comparison)return;
    if(first.atlas!==second.atlas){
      out.textContent="These openings use different population draws. They received "+first.visits.length+" and "+second.visits.length+" visits.";
      return;
    }
    otherRecord=second;el("saved-group-label").hidden=false;
    const a=new Set(first.visits.map(key)),b=new Set(second.visits.map(key));
    const shared=[...a].filter(id=>b.has(id)).length;
    out.textContent=shared+" residents visit both openings · "+(a.size-shared)+" visit only the selected opening · "+(b.size-shared)+" visit only the comparison.";
  };
  const inspect=async()=>{
    const ticket=++revision;comparison++;
    el("saved-list").hidden=true;
    const record=await (await load()).details(select.value);
    if(ticket!==revision)return;
    current=record;
    const visitors=new Set(record.visits.map(key)).size,diverted=record.visits.filter(v=>v[4]).length;
    el("saved-result").textContent=record.visits.length+" visits by "+visitors+" residents · "+diverted+" diverted · "+
      (record.visits.length-diverted)+" newly feasible"+(record.activated!=null?" · "+opened(record.activated):"")+
      (record.openings?.length?" · "+record.openings.length+" storefronts":"")+
      (record.basket!=null?" · "+money.format(record.visits.length*record.basket)+" illustrative gross sales at "+money.format(record.basket)+" per visit":"")+".";
    el("saved-replay").href=replay(record);
    const previous=compare.value;
    compare.replaceChildren(new Option("Choose another opening",""),
      ...Array.from(select.options).filter(o=>o.value!==select.value).map(o=>new Option(o.text,o.value)));
    compare.value=Array.from(compare.options).some(o=>o.value===previous)?previous:"";
    el("saved-compare-label").hidden=compare.options.length<=1;el("saved-list").hidden=false;
    await difference();
  };
  const refresh=async selected=>{
    const rows=await (await load()).listSaved("vancouver");
    rows.sort((a,b)=>b[3]-a[3]||a[0].localeCompare(b[0]));
    if(!rows.length){el("saved-list").hidden=true;status.textContent="No openings saved in this browser.";return;}
    select.replaceChildren(...rows.map(([id,address,period,,rule,clock,basket,workplaces,purchase,localWalk,activated,shoppingOutings,joint])=>
      new Option(address+" · "+hours(period)+" · "+(activated>=0?opened(activated)+" · ":"")+(joint?"combined weekday":clock?"adjusted clock":workplaces?"census workplaces ("+rule+")":
        rule==="access"?"survey bicycle access":rule==="ride"?"universal bicycle access":
        shoppingOutings?"added shopping walks":"original weekday")+(joint&&shoppingOutings?" · added shopping walks":"")+
        (localWalk?" · local grocery walks":"")+(purchase==="bc2010"?" · 2010 grocery shares":"")+(basket>=0?" · "+money.format(basket):""),id)));
    if(selected&&rows.some(r=>r[0]===selected))select.value=selected;
    status.textContent=rows.length+(rows.length===1?" opening saved":" openings saved")+" in this browser.";
    await inspect();
  };
  el("saved-group").onchange=shoppers;
  select.onchange=()=>inspect().catch(fail);shopper.onchange=follow;compare.onchange=()=>difference().catch(fail);
  el("save-opening").onclick=async()=>{
    const button=el("save-opening");if(button.getAttribute("aria-busy")==="true")return;
    button.setAttribute("aria-busy","true");
    try{
      const item=await snapshot();status.textContent="Saving "+item.address+"…";
      await refresh(await (await load()).save(item));
    }catch(e){fail(e);}finally{button.removeAttribute("aria-busy");}
  };
  status.textContent="Reading saved openings…";
  return ()=>refresh(select.value).catch(fail);
}
