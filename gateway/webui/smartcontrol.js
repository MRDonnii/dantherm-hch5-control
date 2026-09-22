"use strict";
(() => {
  const q=(s,r=document)=>r.querySelector(s), qa=(s,r=document)=>[...r.querySelectorAll(s)];
  const days=["Man","Tir","Ons","Tor","Fre","Lør","Søn"];
  const longDays=["Mandag","Tirsdag","Onsdag","Torsdag","Fredag","Lørdag","Søndag"];
  const live=()=>typeof state!=="undefined"&&state?state:(typeof liveState!=="undefined"&&liveState?liveState:{});
  const ctrl=()=>typeof controllerState!=="undefined"&&controllerState?controllerState:{};
  const setText=(selector,value)=>{const el=q(selector);if(el)el.textContent=value==null||value===""?"—":String(value)};
  const setValue=(selector,value)=>{const el=q(selector);if(el&&document.activeElement!==el)el.value=value??""};
  const setChecked=(selector,value)=>{const el=q(selector);if(el&&document.activeElement!==el)el.checked=value===true};
  const checked=selector=>q(selector)?.checked===true;
  const value=(selector,fallback="")=>q(selector)?.value??fallback;
  const number=(v,d=1)=>Number.isFinite(Number(v))?Number(v).toLocaleString("da-DK",{maximumFractionDigits:d}):"—";

  function brandIcon(){return '<span class="modern-logo" aria-hidden="true"><svg viewBox="0 0 64 64"><path d="M12 31 32 13l20 18v20H39V38H25v13H12Z"/><path class="wave" d="M10 44c9-7 16-7 25 0 8 6 13 6 20 0"/></svg></span>'}

  function cleanupLegacyLabels(){
    const skip=new Set(["SCRIPT","STYLE","PRE","CODE","TEXTAREA"]);
    const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
    for(const node of nodes){
      if(skip.has(node.parentElement?.tagName))continue;
      let text=node.nodeValue||"";
      text=text.replaceAll("Dantherm HCH PassiveLink","HCH5 Control").replaceAll("Dantherm PassiveLink","HCH5 Control").replaceAll("PassiveLink","HCH5 Control");
      if(text!==node.nodeValue)node.nodeValue=text;
    }
  }

  function installBranding(){
    document.title=document.location.pathname==="/controller"?"HCH5 Control · Teknik":document.location.pathname==="/sniffer"?"HCH5 Control · Modbus Sniffer":"HCH5 Control";
    const oldBrand=q(".topbar .brand");
    if(oldBrand){oldBrand.hidden=false;oldBrand.innerHTML='<span class="brand-mark" aria-hidden="true">H</span><div><b>HCH5 CONTROL</b><small>Smart ventilation</small></div>'}
    const tabs=q(".tabs");
    if(tabs&&!q(".modern-brand",tabs)){
      const brand=document.createElement("div");brand.className="modern-brand";
      brand.innerHTML=`${brandIcon()}<div><strong>HCH5 <span>Control</span></strong><small>Smart ventilation · local first</small></div>`;
      tabs.prepend(brand);
      const status=document.createElement("div");status.className="sidebar-status";
      status.innerHTML='<i></i><span>Anlæg online</span><small>HCH5 MK1 · lokal styring</small>';
      tabs.append(status);
    }
    const iconMap={"Overblik og styring":"⌂","Historik":"⌁","Teknik":"⌘","System":"▣","Home Assistant":"⌂","Diagnostik":"⌕","Opdateringer":"↻","Indstillinger":"⚙"};
    qa(".tabs button,.tabs .tab-link").forEach(el=>{el.dataset.navIcon=iconMap[el.textContent.trim()]||"•"});
    const badge=q(".headline-status .badge.safe");if(badge)badge.textContent="BETA";
    const footer=q("footer span:last-child");if(footer)footer.textContent="HCH5 Control · lokal styring";
    const bypassOff=q('[data-bypass="off"]'),bypassOn=q('[data-bypass="on"]');
    if(bypassOff)bypassOff.textContent="Auto";if(bypassOn)bypassOn.textContent="Åbn";
    const bypassBox=bypassOff?.closest(".fireplace-control");
    if(bypassBox){const title=q(":scope > span",bypassBox);if(title)title.textContent="Bypass request"}
    const ha=q("#homeassistant");
    if(ha){
      const h1=q(".page-title h1",ha);if(h1)h1.textContent="Forbind HCH5 Control til Home Assistant";
      const heads=qa("h2",ha);if(heads[0])heads[0].textContent="Installér HCH5 Control integrationen";
      const ps=qa("p",ha);if(ps[0])ps[0].innerHTML='Installér <strong>HCH5 Control</strong> som custom integration via HACS. Den eksisterende interne domain bevares, så opgraderinger ikke skaber nye entities.';
      if(ps[1])ps[1].innerHTML='Brug denne Raspberry Pi som vært og port <strong>4196</strong> til live data. Controller-API bruges separat til de funktioner, der må styres.';
    }
    const diagnostics=q("#diagnostics");
    if(diagnostics){
      const title=q(".page-title h1",diagnostics);if(title)title.textContent="HCH5 Control og rå data";
      const support=q(".support-card",diagnostics);
      if(support&&!q(".sniffer-link",support)){
        const link=document.createElement("a");link.className="sniffer-link";link.href="/sniffer";link.textContent="Åbn Modbus Sniffer";support.append(link);
      }
    }
    cleanupLegacyLabels();
  }

  function preferredTheme(){
    try{return localStorage.getItem("hch5-theme-preference")||"system"}catch(e){return"system"}
  }
  function resolvedTheme(pref){return pref==="system"?(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"):pref}
  function applyPreferredTheme(pref,save=true){
    if(!["system","light","dark"].includes(pref))pref="system";
    const resolved=resolvedTheme(pref);
    if(save){try{localStorage.setItem("hch5-theme-preference",pref)}catch(e){}}
    try{localStorage.setItem("dantherm-theme",resolved)}catch(e){}
    if(typeof applyTheme==="function")applyTheme(resolved);else document.documentElement.dataset.theme=resolved;
    qa("[data-theme-choice]").forEach(button=>button.classList.toggle("active",button.dataset.themeChoice===pref));
    const toggle=q("#theme-toggle")||q("#sc-theme-toggle");if(toggle)toggle.textContent=resolved==="dark"?"☀":"☾";
    const meta=q('meta[name="theme-color"]');if(meta)meta.content=resolved==="dark"?"#0c141b":"#f7fafc";
  }
  function installTheme(){
    if(!q("#theme-toggle")){
      const top=q(".headline-status");if(top){const button=document.createElement("button");button.id="sc-theme-toggle";button.className="sc-theme-toggle";button.type="button";button.setAttribute("aria-label","Skift mellem lyst og mørkt tema");button.textContent="☾";top.append(button);button.addEventListener("click",()=>applyPreferredTheme(document.documentElement.dataset.theme==="dark"?"light":"dark"))}
    }else{
      q("#theme-toggle")?.addEventListener("click",()=>setTimeout(()=>{const current=document.documentElement.dataset.theme||"light";try{localStorage.setItem("hch5-theme-preference",current)}catch(e){};qa("[data-theme-choice]").forEach(button=>button.classList.toggle("active",button.dataset.themeChoice===current))},0));
    }
    const settings=q("#settings");
    if(settings&&!q("#appearance-card")){
      const card=document.createElement("article");card.className="card appearance-card";card.id="appearance-card";
      card.innerHTML='<div class="section-heading"><div><small>UDSEENDE</small><h2>Farvetema</h2></div><span class="badge">GEMMES LOKALT</span></div><div class="appearance-options"><button type="button" data-theme-choice="system"><strong>System</strong><small>Følg enhedens lyse/mørke tilstand</small></button><button type="button" data-theme-choice="light"><strong>Lys</strong><small>Lyst professionelt kontrolpanel</small></button><button type="button" data-theme-choice="dark"><strong>Mørk</strong><small>Mørkt kontrolrum med høj kontrast</small></button></div>';
      settings.insertBefore(card,settings.querySelector(".auth-settings")||null);
      qa("[data-theme-choice]",card).forEach(button=>button.addEventListener("click",()=>applyPreferredTheme(button.dataset.themeChoice)));
    }
    applyPreferredTheme(preferredTheme(),false);
    const media=matchMedia("(prefers-color-scheme: dark)");
    const listener=()=>{if(preferredTheme()==="system")applyPreferredTheme("system",false)};
    if(media.addEventListener)media.addEventListener("change",listener);else if(media.addListener)media.addListener(listener);
  }

  function scheduleRows(){return days.map((day,index)=>`<div class="schedule-row" data-schedule-row="${index}"><label class="switch switch-mini" title="Aktivér ${longDays[index]}"><input id="sc-day-${index}-enabled" type="checkbox"><span></span></label><div class="schedule-day">${day}</div><input id="sc-day-${index}-start" type="time" aria-label="${longDays[index]} start"><span class="schedule-arrow">→</span><input id="sc-day-${index}-end" type="time" aria-label="${longDays[index]} slut"><select id="sc-day-${index}-level" aria-label="${longDays[index]} niveau">${[1,2,3,4,5,6].map(v=>`<option value="${v}">Trin ${v}</option>`).join("")}</select></div>`).join("")}

  function automationMarkup(){return `<section class="modern-automation card" id="modern-automation">
    <div class="modern-section-head"><div><small>INTELLIGENT STYRING</small><h2>Planlægning og automatik</h2><p>HCH5 Control kombinerer luftkvalitet, ugeskema, natsænkning, ferie og frikøling. Sikker master-arbitration ligger under alle funktioner.</p></div><div class="automation-state"><i></i><span id="auto-active-label">Afventer controller</span></div></div>
    <div class="automation-summary"><div><small>AKTIV KILDE</small><b id="sc-effective-source">—</b></div><div><small>NIVEAU</small><b id="sc-effective-level">—</b></div><div><small>BYPASS REQUEST</small><b id="sc-effective-bypass">—</b></div><div><small>FYSISK BYPASS</small><b id="sc-physical-bypass">—</b></div></div>
    <div class="automation-layout">
      <section class="automation-panel"><div class="automation-panel-head"><span class="tile-icon">▣</span><div><b>Ugeskema</b><small id="schedule-active-label">Ikke aktivt nu</small></div><label class="switch"><input id="schedule-enabled" type="checkbox"><span></span></label></div><div class="schedule-table">${scheduleRows()}</div></section>
      <div class="automation-side">
        <section class="automation-panel"><div class="automation-panel-head"><span class="tile-icon">☾</span><div><b>Natsænkning</b><small id="night-active-label">Standby</small></div><label class="switch"><input id="night-enabled" type="checkbox"><span></span></label></div><div class="automation-fields"><label class="automation-field"><span>Fra</span><input id="night-start" type="time"></label><label class="automation-field"><span>Til</span><input id="night-end" type="time"></label><label class="automation-field full"><span>Maks. normalniveau om natten</span><select id="night-level">${[1,2,3,4,5,6].map(v=>`<option value="${v}">Trin ${v}</option>`).join("")}</select></label></div><p class="automation-help">CO₂ og fugt kan stadig hæve ventilationen, så luftkvaliteten ikke ofres for støjniveauet.</p></section>
        <section class="automation-panel"><div class="automation-panel-head"><span class="tile-icon">⌂</span><div><b>Ferie mode</b><small id="vacation-active-label">Ikke aktiv</small></div><label class="switch"><input id="vacation-enabled" type="checkbox"><span></span></label></div><div class="automation-fields"><label class="automation-field full"><span>Fast ventilationsniveau</span><select id="vacation-level">${[1,2,3,4,5,6].map(v=>`<option value="${v}">Trin ${v}</option>`).join("")}</select></label></div><p class="automation-help">Ferie har høj prioritet, holder et sikkert grundskifte og pauser automatisk frikøling, indtil ferie-mode slås fra.</p></section>
        <section class="automation-panel"><div class="automation-panel-head"><span class="tile-icon">❄</span><div><b>Frikøling</b><small id="cooling-active-label">Standby</small></div><label class="switch"><input id="cooling-enabled" type="checkbox"><span></span></label></div><div class="automation-fields"><label class="automation-field"><span>Inde mål</span><input id="cooling-setpoint" type="number" min="18" max="30" step="0.5"></label><label class="automation-field"><span>Hysterese</span><input id="cooling-hysteresis" type="number" min="0.2" max="3" step="0.1"></label><label class="automation-field"><span>Min. udetemp.</span><input id="cooling-outdoor-min" type="number" min="-10" max="25" step="0.5"></label><label class="automation-field"><span>Min. inde/ude ΔT</span><input id="cooling-delta" type="number" min="0.5" max="10" step="0.5"></label><label class="automation-field full"><span>Minimum ventilation under køling</span><select id="cooling-level">${[1,2,3,4,5,6].map(v=>`<option value="${v}">Trin ${v}</option>`).join("")}</select></label></div><div class="automation-live">Inde <b id="sc-room-temp">—</b> · Ude <b id="sc-outdoor-temp">—</b> · ΔT <b id="sc-cooling-delta-live">—</b></div><p class="automation-help">Bypass-request sættes automatisk til åben, når huset er varmt og udeluften kan give reel gratis køling. Fysisk spjældstatus vises separat.</p></section>
      </div>
    </div>
    <div class="automation-footer"><span id="automation-save-result">Indstillinger gemmes persistent på Raspberry Pi.</span><button id="save-modern-automation" type="button">Gem automatik</button></div>
  </section>`}

  function installAutomation(){
    const overview=q("#overview");if(!overview||q("#modern-automation"))return;
    const holder=document.createElement("div");holder.innerHTML=automationMarkup();const section=holder.firstElementChild;
    const daily=q(".daily-control",overview);if(daily)daily.after(section);else overview.append(section);
    q("#save-modern-automation")?.addEventListener("click",saveAutomation);
    for(let day=0;day<7;day++)q(`#sc-day-${day}-enabled`)?.addEventListener("change",()=>updateScheduleRowState(day));
  }
  function updateScheduleRowState(day){q(`[data-schedule-row="${day}"]`)?.classList.toggle("disabled",!checked(`#sc-day-${day}-enabled`))}

  async function saveAutomation(){
    const button=q("#save-modern-automation"),result=q("#automation-save-result");if(button)button.disabled=true;if(result)result.textContent="Gemmer…";
    const schedule={};for(let day=0;day<7;day++)schedule[String(day)]={enabled:checked(`#sc-day-${day}-enabled`),start:value(`#sc-day-${day}-start`),end:value(`#sc-day-${day}-end`),level:Number(value(`#sc-day-${day}-level`,3))};
    const patch={schedule_enabled:checked("#schedule-enabled"),schedule,night_enabled:checked("#night-enabled"),night_start:value("#night-start"),night_end:value("#night-end"),night_level:Number(value("#night-level",2)),vacation_enabled:checked("#vacation-enabled"),vacation_level:Number(value("#vacation-level",1)),cooling_enabled:checked("#cooling-enabled"),cooling_room_setpoint:Number(value("#cooling-setpoint",23)),cooling_hysteresis:Number(value("#cooling-hysteresis",0.5)),cooling_outdoor_min:Number(value("#cooling-outdoor-min",12)),cooling_min_delta:Number(value("#cooling-delta",1.5)),cooling_level:Number(value("#cooling-level",4))};
    try{
      if(typeof postController!=="function")throw Error("Controller API er ikke tilgængelig på denne side");
      await postController(patch,"Automatik gemt");if(result)result.textContent="Gemt. Controlleren bruger de nye regler med det samme, når Pi er sikker master.";
    }catch(error){if(result)result.textContent=`Fejl: ${error.message}`}
    finally{if(button)button.disabled=false}
  }

  function semanticBypassRequest(s,l){
    const raw=s.actual_bypass_request??l.bypass_request??l.bypass_request_raw??s.effective_bypass??s.bypass;
    const text=String(raw??"").trim().toLowerCase();
    if(["on","255","open","åbn","manual_on"].includes(text))return"Åbn";
    if(["off","0","auto"].includes(text))return"Auto";
    return raw==null?"—":String(raw);
  }
  function physicalBypass(l){
    if(l.bypass_active===true)return"Åben";
    if(l.bypass_active===false)return"Lukket";
    const raw=Number(l.bypass_raw);if(Number.isFinite(raw)&&raw>0&&raw<255)return`Bevæger sig · ${raw}`;
    return"—";
  }

  function renderAutomation(){
    if(!q("#modern-automation"))return;const s=ctrl(),l=live(),schedule=s.schedule||{};
    setChecked("#schedule-enabled",s.schedule_enabled);setChecked("#night-enabled",s.night_enabled);setChecked("#vacation-enabled",s.vacation_enabled);setChecked("#cooling-enabled",s.cooling_enabled);
    for(let day=0;day<7;day++){const entry=schedule[String(day)]||schedule[day]||{};setChecked(`#sc-day-${day}-enabled`,entry.enabled!==false);setValue(`#sc-day-${day}-start`,entry.start||"07:00");setValue(`#sc-day-${day}-end`,entry.end||"22:00");setValue(`#sc-day-${day}-level`,entry.level||3);updateScheduleRowState(day)}
    setValue("#night-start",s.night_start||"22:00");setValue("#night-end",s.night_end||"06:00");setValue("#night-level",s.night_level||2);setValue("#vacation-level",s.vacation_level||1);
    setValue("#cooling-setpoint",s.cooling_room_setpoint??23);setValue("#cooling-hysteresis",s.cooling_hysteresis??0.5);setValue("#cooling-outdoor-min",s.cooling_outdoor_min??12);setValue("#cooling-delta",s.cooling_min_delta??1.5);setValue("#cooling-level",s.cooling_level||4);
    const status=[["#schedule-active-label",s.schedule_active,"Aktivt nu","Klar"],["#night-active-label",s.night_active,"Aktiv nu","Standby"],["#vacation-active-label",s.vacation_active,"Aktiv nu","Ikke aktiv"],["#cooling-active-label",s.cooling_active,"Køler nu","Standby"]];
    status.forEach(([selector,active,on,off])=>{const el=q(selector);if(el){el.textContent=active?on:off;el.classList.toggle("active",!!active)}});
    const master=s.active_master||"unknown";setText("#auto-active-label",master==="pi"?"Pi styrer sikkert":master==="hcp4"?"HCP4 har prioritet":"Afventer sikker master");
    setText("#sc-effective-source",String(s.effective_source||"—").replaceAll("_"," "));setText("#sc-effective-level",s.effective_level?`Trin ${s.effective_level}`:"—");
    setText("#sc-effective-bypass",(s.effective_bypass||s.bypass||"—")==="on"?"Åbn":"Auto");setText("#sc-physical-bypass",physicalBypass(l));
    setText("#overview-bypass-request",semanticBypassRequest(s,l));setText("#overview-bypass-actual",physicalBypass(l));
    const room=Number(s.measurements?.room),outdoor=Number(s.measurements?.outdoor??l.outdoor_temp);setText("#sc-room-temp",Number.isFinite(room)?`${number(room)} °C`:"—");setText("#sc-outdoor-temp",Number.isFinite(outdoor)?`${number(outdoor)} °C`:"—");setText("#sc-cooling-delta-live",Number.isFinite(room)&&Number.isFinite(outdoor)?`${number(room-outdoor)} K`:"—");
    const side=q(".sidebar-status");if(side){const online=l.available===true||master==="pi"||master==="hcp4";side.classList.toggle("offline",!online);const span=q("span",side);if(span)span.textContent=online?"Anlæg online":"Forbindelse mangler";const small=q("small",side);if(small)small.textContent=master==="pi"?"Pi master · writes tilladt efter arbitration":master==="hcp4"?"HCP4 master · Pi passiv":"Afventer master"}
  }

  function installUpdatePanel(){
    const page=q("#updates"),card=q(".update-card",page);if(!card)return;card.classList.add("modern-update-card");
    card.innerHTML='<div class="update-icon">↻</div><div class="update-body"><div class="modern-section-head"><div><small>HCH5 CONTROL</small><h2>Softwareopdatering</h2><p>Stable er standard. Beta-kanalen skal vælges eksplicit og følger den aktive beta-branch, så rettelser kan installeres direkte fra WebUI.</p></div><label class="beta-opt"><input id="update-beta-channel" type="checkbox"><span>Brug beta-kanal</span></label></div><div class="version-grid"><div><small>Installeret</small><b id="update-current">—</b></div><div><small>Tilgængelig</small><b id="update-available">—</b></div><div><small>Kanal</small><b id="update-channel">Stable</b></div></div><div class="update-actions"><button id="check-update" type="button">Søg efter opdatering</button><button id="install-update" class="primary" type="button" disabled>Installer opdatering</button></div><p id="update-result" class="notice">Opdateringer er manuelle. Programfiler sikkerhedskopieres før udskiftning, mens persistent controller-state og login bevares.</p></div>';
    q("#update-beta-channel")?.addEventListener("change",()=>{setText("#update-channel",checked("#update-beta-channel")?"Beta":"Stable");q("#install-update").disabled=true;setText("#update-available","—")});
    q("#check-update")?.addEventListener("click",checkUpdate);q("#install-update")?.addEventListener("click",installUpdate);
  }
  async function adminAction(action,target){const response=await fetch("/api/admin/action",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":typeof authState!=="undefined"?(authState?.csrf||""):""},body:JSON.stringify({action,target})});let payload={};try{payload=await response.json()}catch(e){}if(!response.ok)throw Error(payload.error||`HTTP ${response.status}`);return payload}
  async function checkUpdate(){const channel=checked("#update-beta-channel")?"beta":"stable",result=q("#update-result"),button=q("#check-update");if(button)button.disabled=true;if(result)result.textContent="Kontrollerer GitHub…";try{const info=await adminAction("check_update",channel);setText("#update-current",info.current_version||"ukendt");setText("#update-available",info.available_version||"—");setText("#update-channel",channel==="beta"?"Beta":"Stable");q("#install-update").disabled=!info.update_available;if(result)result.textContent=info.update_available?"En nyere build er klar. Installationen bevarer persistent config, state og login.":"Du kører allerede den nyeste build på denne kanal."}catch(error){if(result)result.textContent=`Kunne ikke kontrollere opdateringer: ${error.message}`}finally{if(button)button.disabled=false}}
  async function installUpdate(){const channel=checked("#update-beta-channel")?"beta":"stable";if(!confirm(`Installer seneste ${channel==="beta"?"beta":"stable"} build nu? WebUI genstarter under opdateringen.`))return;const result=q("#update-result"),button=q("#install-update");if(button)button.disabled=true;if(result)result.textContent="Opdateringen er startet. Siden genindlæses automatisk…";try{await adminAction("install_update",channel);setTimeout(()=>location.reload(),15000)}catch(error){if(result)result.textContent=`Opdatering kunne ikke startes: ${error.message}`;if(button)button.disabled=false}}

  function installFavicon(){if(q('link[rel="icon"]'))return;const svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#132230"/><path d="M12 31 32 13l20 18v20H39V38H25v13H12Z" fill="none" stroke="#edf5f8" stroke-width="5"/><path d="M10 44c9-7 16-7 25 0 8 6 13 6 20 0" fill="none" stroke="#67afe5" stroke-width="4" stroke-linecap="round"/><circle cx="49" cy="17" r="7" fill="#58bd79"/></svg>';const link=document.createElement("link");link.rel="icon";link.href=`data:image/svg+xml,${encodeURIComponent(svg)}`;document.head.append(link)}

  installFavicon();installBranding();installTheme();installAutomation();installUpdatePanel();
  if(typeof renderController==="function"){
    const originalRenderController=renderController;
    renderController=function(){originalRenderController();renderAutomation()};
  }
  renderAutomation();
})();
