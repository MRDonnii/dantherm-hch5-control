"use strict";
(() => {
  const q=(s,r=document)=>r.querySelector(s);
  const qa=(s,r=document)=>[...r.querySelectorAll(s)];
  const label=s=>String(s??"—").replaceAll("_"," ");
  const number=(v,d=0)=>Number.isFinite(Number(v))?Number(v).toLocaleString("da-DK",{maximumFractionDigits:d}):"—";

  function installOverviewHero(){
    const page=q("#overview");
    if(!page||q("#studio-overview-hero",page))return;
    const hero=document.createElement("section");
    hero.id="studio-overview-hero";
    hero.className="studio-overview-hero";
    hero.innerHTML=`
      <div class="studio-overview-copy">
        <small>HCH5 CONTROL</small>
        <h1>Ventilationsoverblik</h1>
        <p>Live drift, luftkvalitet og intelligent lokal styring samlet ét sted.</p>
      </div>
      <div class="studio-overview-state">
        <div><span class="studio-state-dot" id="studio-online-dot"></span><small>ANLÆG</small><b id="studio-online">Forbinder…</b></div>
        <div><small>MASTER</small><b id="studio-master">—</b></div>
        <div><small>STYRING</small><b id="studio-source">—</b></div>
        <div><small>NIVEAU</small><b id="studio-level">—</b></div>
      </div>`;
    page.prepend(hero);
  }

  function installTechniqueHeading(){
    if(location.pathname!=="/controller"&&location.pathname!=="/controller.html")return;
    const hero=q(".controller-hero");
    if(!hero||q(".studio-tech-kicker",hero))return;
    const kicker=document.createElement("div");
    kicker.className="studio-tech-kicker";
    kicker.innerHTML='<span></span><b>LIVE CONTROLLER</b><small>Konfiguration, automatik og diagnostik</small>';
    hero.prepend(kicker);
  }

  function setStateClass(el,state){
    if(!el)return;
    el.classList.remove("ok","warn","bad","idle");
    el.classList.add(state);
  }

  function updateOverview(live,ctl){
    if(!q("#studio-overview-hero"))return;
    const online=live?.available===true&&live?.bus_traffic===true;
    const dot=q("#studio-online-dot");
    setStateClass(dot,online?"ok":"bad");
    const onlineEl=q("#studio-online");if(onlineEl)onlineEl.textContent=online?"Online":"Afbrudt";
    const master=q("#studio-master");if(master)master.textContent=ctl?.active_master==="pi"?"Raspberry Pi":ctl?.active_master==="hcp4"?"HCP4":"Afventer";
    const source=q("#studio-source");if(source)source.textContent=label(ctl?.effective_source||ctl?.mode);
    const level=q("#studio-level");if(level)level.textContent=ctl?.effective_level?`Trin ${ctl.effective_level}`:"—";
  }

  function enhanceMetricLabels(){
    const metrics=q("#overview .metrics-grid");
    if(!metrics)return;
    qa(".metric",metrics).forEach(card=>{
      if(card.dataset.studioReady)return;
      card.dataset.studioReady="1";
      const title=q("small",card)?.textContent?.trim();
      if(title)card.dataset.metric=title.toLowerCase();
    });
  }

  async function refreshStudioState(){
    if(!q("#studio-overview-hero"))return;
    try{
      const [lr,cr]=await Promise.all([
        fetch("/state.json",{cache:"no-store"}),
        fetch("/api/controller/state",{cache:"no-store"})
      ]);
      const live=lr.ok?await lr.json():{};
      const ctl=cr.ok?await cr.json():{};
      updateOverview(live,ctl);
    }catch(e){}
  }

  function install(){
    installOverviewHero();
    installTechniqueHeading();
    enhanceMetricLabels();
    refreshStudioState();
    if(q("#studio-overview-hero"))setInterval(refreshStudioState,3500);
  }

  if(document.readyState==="loading")addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
