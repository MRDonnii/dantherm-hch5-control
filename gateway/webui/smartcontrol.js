"use strict";
(() => {
  const q=(s,r=document)=>r.querySelector(s), qa=(s,r=document)=>[...r.querySelectorAll(s)];

  function installBranding(){
    document.title="HCH5 Control";
    const oldBrand=q(".topbar .brand"); if(oldBrand) oldBrand.hidden=true;
    const tabs=q(".tabs");
    if(tabs && !q(".modern-brand",tabs)){
      const brand=document.createElement("div"); brand.className="modern-brand";
      brand.innerHTML='<span class="modern-logo" aria-hidden="true"><svg viewBox="0 0 64 64"><path d="M12 31 32 13l20 18v20H39V38H25v13H12Z"/><path class="wave" d="M10 44c9-7 16-7 25 0 8 6 13 6 20 0"/></svg></span><div><strong>HCH5 <span>Control</span></strong><small>Smart ventilation</small></div>';
      tabs.prepend(brand);
      const status=document.createElement("div");status.className="sidebar-status";
      status.innerHTML='<i></i><span>Anlæg online</span><small>HCH5 MK1 · lokal styring</small>';
      tabs.append(status);
    }
    const badge=q(".headline-status .badge.safe"); if(badge) badge.textContent="BETA 1.2";
    const iconMap={"Overblik":"⌂","Historik":"⌁","System":"▣","Home Assistant":"⌂","Diagnostik":"⌕","Opdateringer":"↻","Indstillinger":"⚙","Teknik":"⌘"};
    qa(".tabs button,.tabs .tab-link").forEach(el=>{const label=el.textContent.trim();el.dataset.navIcon=iconMap[label]||"•"});
  }

  function automationMarkup(){
    return `<section class="modern-automation card" id="modern-automation">
      <div class="modern-section-head"><div><small>INTELLIGENT STYRING</small><h2>Planlægning og automatik</h2><p>Pi-controlleren kombinerer ugeskema, natsænkning, ferie og frikøling. Luftkvalitet har fortsat prioritet.</p></div><div class="automation-state"><span id="auto-active-label">Automatik klar</span><i></i></div></div>
      <div class="automation-tiles">
        <article class="automation-tile"><header><span class="tile-icon">▣</span><div><b>Ugeskema</b><small id="schedule-active-label">Ikke aktivt</small></div><label class="switch"><input id="schedule-enabled" type="checkbox"><span></span></label></header><div class="tile-fields"><label>Hverdage fra<input id="weekday-start" type="time" value="07:00"></label><label>til<input id="weekday-end" type="time" value="22:00"></label><label>Trin<select id="weekday-level">${[1,2,3,4,5,6].map(v=>`<option>${v}</option>`).join("")}</select></label><label>Weekend fra<input id="weekend-start" type="time" value="08:00"></label><label>til<input id="weekend-end" type="time" value="22:00"></label><label>Trin<select id="weekend-level">${[1,2,3,4,5,6].map(v=>`<option>${v}</option>`).join("")}</select></label></div></article>
        <article class="automation-tile"><header><span class="tile-icon">☾</span><div><b>Natsænkning</b><small id="night-active-label">Ikke aktiv</small></div><label class="switch"><input id="night-enabled" type="checkbox"><span></span></label></header><div class="tile-fields compact"><label>Fra<input id="night-start" type="time" value="22:00"></label><label>Til<input id="night-end" type="time" value="06:00"></label><label>Trin<select id="night-level">${[1,2,3,4,5,6].map(v=>`<option>${v}</option>`).join("")}</select></label></div><p>Reducerer støj og luftmængde om natten. Høj CO₂/RH kan stadig hæve ventilationen.</p></article>
        <article class="automation-tile"><header><span class="tile-icon">☀</span><div><b>Ferie mode</b><small id="vacation-active-label">Ikke aktiv</small></div><label class="switch"><input id="vacation-enabled" type="checkbox"><span></span></label></header><div class="tile-fields one"><label>Ventilation under ferie<select id="vacation-level">${[1,2,3,4,5,6].map(v=>`<option>${v}</option>`).join("")}</select></label></div><p>Holder huset ventileret med et fast lavt niveau. Frikøling sættes på pause under ferie.</p></article>
        <article class="automation-tile"><header><span class="tile-icon">❄</span><div><b>Frikøling</b><small id="cooling-active-label">Ikke aktiv</small></div><label class="switch"><input id="cooling-enabled" type="checkbox"><span></span></label></header><div class="tile-fields cooling"><label>Inde mål<input id="cooling-setpoint" type="number" min="18" max="30" step="0.5"></label><label>Min. ude<input id="cooling-outdoor-min" type="number" min="-10" max="25" step="0.5"></label><label>Min. forskel<input id="cooling-delta" type="number" min="0.5" max="10" step="0.5"></label><label>Min. trin<select id="cooling-level">${[1,2,3,4,5,6].map(v=>`<option>${v}</option>`).join("")}</select></label></div><p>Åbner bypass automatisk når huset er varmt og udeluften reelt kan køle.</p></article>
      </div>
      <div class="automation-footer"><span id="automation-save-result">Ændringer gemmes på Raspberry Pi.</span><button id="save-modern-automation" type="button">Gem automatisk styring</button></div>
    </section>`;
  }

  function installAutomation(){
    const overview=q("#overview"), existing=q("#modern-automation"); if(!overview||existing)return;
    const holder=document.createElement("div");holder.innerHTML=automationMarkup();
    const section=holder.firstElementChild;
    const daily=q(".daily-control",overview); if(daily) daily.after(section); else overview.append(section);
    q("#save-modern-automation")?.addEventListener("click",saveAutomation);
  }

  function value(id,fallback=""){const el=q(id);return el?el.value:fallback}
  function checked(id){return q(id)?.checked===true}
  function setValue(id,v){const el=q(id);if(el && document.activeElement!==el)el.value=v??""}
  function setChecked(id,v){const el=q(id);if(el)el.checked=v===true}

  async function saveAutomation(){
    const button=q("#save-modern-automation"),result=q("#automation-save-result");
    if(button)button.disabled=true;if(result)result.textContent="Gemmer…";
    const schedule={};
    for(let day=0;day<7;day++){
      const weekend=day>=5;
      schedule[String(day)]={enabled:true,start:value(weekend?"#weekend-start":"#weekday-start"),end:value(weekend?"#weekend-end":"#weekday-end"),level:Number(value(weekend?"#weekend-level":"#weekday-level",3))};
    }
    const patch={
      schedule_enabled:checked("#schedule-enabled"),schedule,
      night_enabled:checked("#night-enabled"),night_start:value("#night-start"),night_end:value("#night-end"),night_level:Number(value("#night-level",2)),
      vacation_enabled:checked("#vacation-enabled"),vacation_level:Number(value("#vacation-level",1)),
      cooling_enabled:checked("#cooling-enabled"),cooling_room_setpoint:Number(value("#cooling-setpoint",23)),cooling_outdoor_min:Number(value("#cooling-outdoor-min",12)),cooling_min_delta:Number(value("#cooling-delta",1.5)),cooling_level:Number(value("#cooling-level",4))
    };
    try{await postController(patch,"Automatisk styring gemt");if(result)result.textContent="Automatisk styring er gemt og aktiv på Pi-controlleren."}
    catch(error){if(result)result.textContent=`Fejl: ${error.message}`}
    finally{if(button)button.disabled=false}
  }

  function renderAutomation(){
    const s=controllerState||{}; if(!q("#modern-automation"))return;
    setChecked("#schedule-enabled",s.schedule_enabled);setChecked("#night-enabled",s.night_enabled);setChecked("#vacation-enabled",s.vacation_enabled);setChecked("#cooling-enabled",s.cooling_enabled);
    const schedule=s.schedule||{},weekday=schedule["0"]||{},weekend=schedule["5"]||{};
    setValue("#weekday-start",weekday.start||"07:00");setValue("#weekday-end",weekday.end||"22:00");setValue("#weekday-level",weekday.level||3);
    setValue("#weekend-start",weekend.start||"08:00");setValue("#weekend-end",weekend.end||"22:00");setValue("#weekend-level",weekend.level||3);
    setValue("#night-start",s.night_start||"22:00");setValue("#night-end",s.night_end||"06:00");setValue("#night-level",s.night_level||2);setValue("#vacation-level",s.vacation_level||1);
    setValue("#cooling-setpoint",s.cooling_room_setpoint??23);setValue("#cooling-outdoor-min",s.cooling_outdoor_min??12);setValue("#cooling-delta",s.cooling_min_delta??1.5);setValue("#cooling-level",s.cooling_level||4);
    const labels=[["#schedule-active-label",s.schedule_active,"Aktivt nu","Klar"],["#night-active-label",s.night_active,"Aktiv nu","Klar"],["#vacation-active-label",s.vacation_active,"Aktiv nu","Ikke aktiv"],["#cooling-active-label",s.cooling_active,"Køler nu","Standby"]];
    labels.forEach(([id,active,on,off])=>{const el=q(id);if(el){el.textContent=active?on:off;el.classList.toggle("active",!!active)}});
    const master=s.active_master||"unknown", top=q("#auto-active-label");if(top)top.textContent=master==="pi"?"Pi styrer anlægget":master==="hcp4"?"HCP4 har overtaget":"Afventer sikker master";
    const side=q(".sidebar-status");if(side){side.classList.toggle("offline",master!=="pi" && state?.available!==true);const span=q("span",side);if(span)span.textContent=state?.available===true?"Anlæg online":"Forbindelse mangler"}
  }

  function installUpdatePanel(){
    const page=q("#updates"),card=q(".update-card",page);if(!card)return;
    card.classList.add("modern-update-card");
    card.innerHTML=`<div class="update-icon">↻</div><div class="update-body"><div class="modern-section-head"><div><small>HCH5 CONTROL</small><h2>Softwareopdatering</h2><p>Stable er standard. Beta skal vælges aktivt og kan indeholde nye funktioner før den stabile kanal.</p></div><label class="beta-opt"><input id="update-beta-channel" type="checkbox"><span>Brug beta-kanal</span></label></div><div class="version-grid"><div><small>Installeret</small><b id="update-current">—</b></div><div><small>Tilgængelig</small><b id="update-available">—</b></div><div><small>Kanal</small><b id="update-channel">Stable</b></div></div><div class="update-actions"><button id="check-update" type="button">Søg efter opdatering</button><button id="install-update" class="primary" type="button" disabled>Installer opdatering</button></div><p id="update-result" class="notice">Ingen automatisk installation. Der tages backup før programfiler udskiftes.</p></div>`;
    q("#update-beta-channel")?.addEventListener("change",()=>{q("#update-channel").textContent=checked("#update-beta-channel")?"Beta":"Stable";q("#install-update").disabled=true;q("#update-available").textContent="—"});
    q("#check-update")?.addEventListener("click",checkUpdate);
    q("#install-update")?.addEventListener("click",installUpdate);
  }

  async function adminAction(action,target){
    const response=await fetch("/api/admin/action",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":authState?.csrf||""},body:JSON.stringify({action,target})});
    let payload={};try{payload=await response.json()}catch(e){}
    if(!response.ok)throw Error(payload.error||`HTTP ${response.status}`);return payload;
  }
  async function checkUpdate(){
    const channel=checked("#update-beta-channel")?"beta":"stable",result=q("#update-result"),button=q("#check-update");if(button)button.disabled=true;if(result)result.textContent="Kontrollerer GitHub…";
    try{const info=await adminAction("check_update",channel);q("#update-current").textContent=info.current_version||"ukendt";q("#update-available").textContent=info.available_version||"—";q("#update-channel").textContent=channel==="beta"?"Beta":"Stable";q("#install-update").disabled=!info.update_available;if(result)result.textContent=info.update_available?"En opdatering er klar. Installationen bevarer login, tokens, controller-state og indstillinger.":"Du kører allerede den nyeste version på denne kanal."}
    catch(error){if(result)result.textContent=`Kunne ikke kontrollere opdateringer: ${error.message}`}
    finally{if(button)button.disabled=false}
  }
  async function installUpdate(){
    const channel=checked("#update-beta-channel")?"beta":"stable";if(!confirm(`Installer seneste ${channel==="beta"?"beta":"stable"} version nu? WebUI genstarter under opdateringen.`))return;
    const result=q("#update-result"),button=q("#install-update");if(button)button.disabled=true;if(result)result.textContent="Opdateringen er startet. Siden kan være utilgængelig et øjeblik…";
    try{await adminAction("install_update",channel);setTimeout(()=>location.reload(),15000)}catch(error){if(result)result.textContent=`Opdatering kunne ikke startes: ${error.message}`;if(button)button.disabled=false}
  }

  function installFavicon(){
    if(q('link[rel="icon"]'))return;
    const svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#132230"/><path d="M12 31 32 13l20 18v20H39V38H25v13H12Z" fill="none" stroke="#edf5f8" stroke-width="5"/><path d="M10 44c9-7 16-7 25 0 8 6 13 6 20 0" fill="none" stroke="#5ba8df" stroke-width="4" stroke-linecap="round"/><circle cx="49" cy="17" r="7" fill="#58bd79"/></svg>';
    const link=document.createElement("link");link.rel="icon";link.href=`data:image/svg+xml,${encodeURIComponent(svg)}`;document.head.append(link);
  }

  installFavicon();installBranding();installAutomation();installUpdatePanel();
  if(typeof renderController==="function"){
    const original=renderController;
    renderController=function(){original();renderAutomation()};
  }
  renderAutomation();
})();
