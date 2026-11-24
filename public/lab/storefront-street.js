import {atStorefront,StorefrontAccess,storefrontInteractionMetres} from "./storefront-access.js";

export class StorefrontStreet {
  constructor({player,market,reveal,draw}){
    Object.assign(this,{player,market,reveal,draw});
    const el=id=>document.getElementById(id);
    this.panel=el("street-shops");this.select=el("street-shop-site");this.status=el("street-shop-distance");
    this.inspect=el("street-shop-inspect");this.open=el("street-shop-open");
    this.select.onchange=()=>this.refresh();
    this.inspect.onclick=()=>this.inspectSite(this.select.value);
    this.open.onclick=()=>{
      const model=this.market(),player=this.player(),site=model?.site;
      if(site?.id===this.select.value&&model.canActivate&&atStorefront(player,this.lookup?.locate(site,player?.graph,player?.mode))){
        model.activate();
        this.refresh();
      }
    };
  }

  access(model){
    if(!model?.catalog)return null;
    if(this.catalog!==model.catalog){
      this.catalog=model.catalog;
      this.lookup=new StorefrontAccess(model.catalog.sites);
    }
    return this.lookup;
  }

  inspectSite(id){
    if(!this.rows?.some(row=>row.site.id===id))return;
    this.market().selectSite(id);
    this.select.value=id;
    this.reveal();
    this.refresh();
  }

  refresh(){
    const player=this.player(),model=this.market();
    const rows=player&&model?.active&&model.payload?this.access(model)?.nearby(player):null;
    this.rows=rows;
    this.panel.hidden=!rows?.length;
    if(!rows?.length){
      if(this.visual){this.visual="";this.draw([],player);}
      return;
    }
    const key=rows.map(({site})=>site.id).join("/");
    const focus=model.site?.id;
    const selected=focus!==this.focus?focus:this.select.value;
    if(key!==this.options){
      const counts=new Map();
      for(const {site} of rows)counts.set(site.name,(counts.get(site.name)??0)+1);
      this.select.replaceChildren(...rows.map(({site})=>new Option(
        site.name+(counts.get(site.name)>1?" · #"+site.id:""),site.id)));
      this.options=key;
    }
    this.focus=focus;
    this.select.value=rows.some(({site})=>site.id===selected)?selected:rows[0].site.id;
    const choice=rows.find(({site})=>site.id===this.select.value);
    const current=choice.site.id===focus;
    this.inspect.hidden=current;
    this.open.hidden=!current||!model.playOpening||model.playedAt!==null;
    const near=atStorefront(player,choice.access);
    this.open.disabled=!near||!model.canActivate;
    const metres=Math.round(choice.metres);
    this.status.textContent=near?"At the estimated street access":metres+" m to estimated street access"+
      (metres<=storefrontInteractionMetres?" · use the connected street":"");
    this.open.title=near?(model.canActivate?"Open at the current simulation time":"Check the storefront’s opening hours"):
      "Move within "+storefrontInteractionMetres+" m along connected streets";
    const statuses=rows.map(row=>({...row,state:model.openAt(row.site.id)?"open":row.site.id===focus?"selected":"candidate"}));
    const visual=JSON.stringify([player.mode,statuses.map(({site,access,state})=>[site.id,access.p,state])]);
    if(this.visual!==visual){this.visual=visual;this.draw(statuses,player);}
  }
}
