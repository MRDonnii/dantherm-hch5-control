"use strict";
(() => {
  const q=(s,r=document)=>r.querySelector(s), qa=(s,r=document)=>[...r.querySelectorAll(s)];
  let csrf="", controller={}, live={};
  const text=(s,v)=>{const e=q(s);if(e)e.textContent=v==null||v===""?"—":String(v)};
  const value=(s,v)=>{const e=q(s);if(e&&document.activeElement!==e)e.value=v??""};
  const checked=s=>q(s)?.checked===true;
  const field=(s,f="")=>q(s)?.value??f;
  const duration=s=>{s=Math.max(0,Number(s)||0);const h=Math.floor(s/3600),m=Math.floor((s%3600)/60);return h?`${h}t ${m}m`:`${m} min`};
  const coolingLabels={disabled:"Deaktiveret",sensor_missing:"Mangler temperaturdata",manual_mode:"Manuel mode",vacation:"Ferie mode",qualifying:"Kvalificerer",opening:"Åbner bypass",active:"Aktiv",minimum_on_hold:"Min. køretid",minimum_off_hold:"Min. pausetid",outdoor_too_cold:"Ude for kold",not_cooler_outside:"Ude ikke koldere",room_below_start:"Rum under startgrænse",room_satisfied:"Rumtemperatur nået",standby:"Standby"};
  const healthLabels={healthy:"Sund",degraded:"Begrænset",stale:"Forældet",unknown:"Ukendt"};
  const comfortLabels={comfortable:"Komfortabel",cold:"Kølig indblæsning",warm:"Varm indblæsning",unknown:"Ukendt"};

  async function loadAuth(){try{const r=await fetch("/api/auth/status",{cache:"no-store"});const p=await r.json();csrf=p.csrf||""}catch(e){csrf=""}}
  async function postConfig(patch){const r=await fetch("/api/controller/config",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:JSON.stringify(patch)});const p=await r.json().catch(()=>({}));if(!r.ok)throw Error(p.error||`HTTP ${r.status}`);controller=p;try{controllerState=p}catch(e){}return p}
  async function fetchState(){try{const [c,l]=await Promise.all([fetch("/api/controller/state",{cache:"no-store"}),fetch("/state.json",{cache:"no-store"})]);if(c.ok)controller=await c.json();if(l.ok)live=await l.json();try{controllerState=controller}catch(e){}render()}catch(e){}}

  function boostMarkup(compact=false){return `<section class="${compact?"card modern-controller-tools":"automation-panel quick-boost-panel"}" id="${compact?"controller-modern-tools":"quick-boost-panel"}">${compact?'<div class="section-heading"><div><small>MODERNE AUTOMATIK</small><h2>Quick Boost og frikøling</h2></div><span class="badge">LOCAL FIRST</span></div>':'<div class="automation-panel-head"><span class="tile-icon">↟</span><div><b>Quick Boost</b><small id="quick-boost-label">Ikke aktiv</small></div><select id="quick-boost-level" aria-label="Quick Boost niveau"><option value="4">Trin 4</option><option value="5">Trin 5</option><option value="6" selected>Trin 6</option></select></div>'}<div class="boost-actions"><button type="button" data-quick-boost="15">15 min</button><button type="button" data-quick-boost="30">30 min</button><button type="button" data-quick-boost="60">60 min</button><button type="button" data-quick-boost="0">Stop</button></div><div class="boost-meta"><div><small>Quick Boost</small><b id="${compact?"ctl-":""}boost-remaining">—</b></div><div><small>Frikøling</small><b id="${compact?"ctl-":""}cooling-state">—</b></div></div>${compact?'<div class="modern-control-result" id="controller-modern-reason">Afventer controller…</div>':''}</section>`}

  function installObservabilityStyles(){
    if(q("#controller-observability-style"))return;
    const style=document.createElement("style");style.id="controller-observability-style";style.textContent=`
      .controller-health-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:16px 0}
      .controller-health-grid>div{padding:14px 16px;border:1px solid var(--line,#d9e1e8);border-radius:14px;background:var(--card-soft,rgba(127,145,160,.06))}
      .controller-health-grid small{display:block;font-size:.68rem;letter-spacing:.08em;opacity:.7;margin-bottom:5px}.controller-health-grid b{font-size:1rem}
      .decision-log{display:grid;gap:8px;margin-top:14px}.decision-event{display:grid;grid-template-columns:72px 120px 70px 1fr;gap:10px;align-items:start;padding:10px 12px;border-radius:12px;background:var(--card-soft,rgba(127,145,160,.06));border:1px solid var(--line,#d9e1e8);font-size:.82rem}.decision-event time{font-variant-numeric:tabular-nums;opacity:.75}.decision-event .decision-reason{opacity:.82;line-height:1.35}.decision-empty{padding:14px;opacity:.7}
      @media(max-width:900px){.controller-health-grid{grid-template-columns:1fr 1fr}.decision-event{grid-template-columns:62px 1fr}.decision-event .decision-level,.decision-event .decision-reason{grid-column:2}}
    `;document.head.append(style)
  }

  function installDashboardControls(){
    const root=q("#modern-automation");if(!root)return false;
    const side=q(".automation-side",root);
    if(side&&!q("#quick-boost-panel")){const host=document.createElement("div");host.innerHTML=boostMarkup(false);side.prepend(host.firstElementChild)}
    const vacation=q("#vacation-enabled")?.closest(".automation-panel");
    if(vacation&&!q("#vacation-until")){const fields=q(".automation-fields",vacation);const label=document.createElement("label");label.className="automation-field full";label.innerHTML='<span>Ferie slutter automatisk</span><input id="vacation-until" type="datetime-local"><small>Lad feltet være tomt for ferie indtil manuel deaktivering.</small>';fields?.append(label)}
    const cooling=q("#cooling-enabled")?.closest(".automation-panel");
    if(cooling&&!q("#cooling-start-delay")){const grid=document.createElement("div");grid.className="advanced-cooling-grid";grid.innerHTML='<label><span>Startforsinkelse</span><select id="cooling-start-delay"><option value="0">Ingen</option><option value="60">1 min</option><option value="180">3 min</option><option value="300">5 min</option><option value="600">10 min</option></select></label><label><span>Minimum aktiv</span><select id="cooling-min-on"><option value="0">Ingen</option><option value="300">5 min</option><option value="600">10 min</option><option value="900">15 min</option><option value="1800">30 min</option></select></label><label><span>Minimum pause</span><select id="cooling-min-off"><option value="0">Ingen</option><option value="180">3 min</option><option value="300">5 min</option><option value="600">10 min</option><option value="900">15 min</option></select></label><label><span>Aktuator timeout</span><select id="cooling-transition-timeout"><option value="60">60 s</option><option value="90">90 s</option><option value="120">120 s</option><option value="180">180 s</option><option value="300">300 s</option></select></label>';
      const liveBox=q(".automation-live",cooling);if(liveBox)liveBox.before(grid);else cooling.append(grid)}
    const old=q("#save-modern-automation");
    if(old&&!old.dataset.extended){const replacement=old.cloneNode(true);replacement.dataset.extended="1";old.replaceWith(replacement);replacement.addEventListener("click",saveAutomation)}
    qa("[data-quick-boost]",root).forEach(b=>{if(b.dataset.bound)return;b.dataset.bound="1";b.addEventListener("click",()=>setBoost(Number(b.dataset.quickBoost)))})
    return true;
  }

  function installControllerTools(){
    if(location.pathname!=="/controller"||q("#controller-modern-tools"))return;
    installObservabilityStyles();
    const hero=q(".controller-hero");if(!hero)return;
    const status=document.createElement("section");status.className="modern-controller-status";status.innerHTML='<div><small>AKTIV KILDE</small><b id="ctl-effective-source">—</b></div><div><small>QUICK BOOST</small><b id="ctl-boost-summary">—</b></div><div><small>FRIKØLING</small><b id="ctl-cooling-summary">—</b></div><div><small>BYPASS</small><b id="ctl-bypass-summary">—</b></div>';hero.after(status);
    const host=document.createElement("div");host.innerHTML=boostMarkup(true);status.after(host.firstElementChild);
    const health=document.createElement("section");health.className="card";health.id="controller-health";health.innerHTML='<div class="section-heading"><div><small>CONTROLLER HEALTH</small><h2>Datakvalitet og beslutninger</h2><p>Read-only overvågning. Denne del sender ingen Modbus-kommandoer.</p></div><span class="badge" id="ctl-health-badge">—</span></div><div class="controller-health-grid"><div><small>LOKALE DATA</small><b id="ctl-data-health">—</b></div><div><small>SENESTE BUSFRAME</small><b id="ctl-bus-age">—</b></div><div><small>KOMFORT</small><b id="ctl-comfort">—</b></div><div><small>BESLUTNINGER</small><b id="ctl-decision-count">—</b></div></div><div class="section-heading"><div><small>DECISION LOG</small><h2>Hvorfor ændrede styringen sig?</h2></div></div><div class="decision-log" id="ctl-decision-log"><div class="decision-empty">Afventer controllerhistorik…</div></div>';
    q("#controller-modern-tools")?.after(health);
    qa("[data-quick-boost]",q("#controller-modern-tools")).forEach(b=>b.addEventListener("click",()=>setBoost(Number(b.dataset.quickBoost))))
  }

  function schedulePatch(){const schedule={};for(let i=0;i<7;i++)schedule[String(i)]={enabled:checked(`#sc-day-${i}-enabled`),start:field(`#sc-day-${i}-start`),end:field(`#sc-day-${i}-end`),level:Number(field(`#sc-day-${i}-level`,3))};return schedule}
  async function saveAutomation(){
    const b=q("#save-modern-automation"),result=q("#automation-save-result");if(b)b.disabled=true;if(result)result.textContent="Gemmer…";
    const patch={schedule_enabled:checked("#schedule-enabled"),schedule:schedulePatch(),night_enabled:checked("#night-enabled"),night_start:field("#night-start"),night_end:field("#night-end"),night_level:Number(field("#night-level",2)),vacation_enabled:checked("#vacation-enabled"),vacation_level:Number(field("#vacation-level",1)),vacation_until:field("#vacation-until")||null,cooling_enabled:checked("#cooling-enabled"),cooling_room_setpoint:Number(field("#cooling-setpoint",23)),cooling_hysteresis:Number(field("#cooling-hysteresis",0.5)),cooling_outdoor_min:Number(field("#cooling-outdoor-min",12)),cooling_min_delta:Number(field("#cooling-delta",1.5)),cooling_level:Number(field("#cooling-level",4)),cooling_start_delay_seconds:Number(field("#cooling-start-delay",180)),cooling_min_on_seconds:Number(field("#cooling-min-on",600)),cooling_min_off_seconds:Number(field("#cooling-min-off",300)),cooling_transition_timeout_seconds:Number(field("#cooling-transition-timeout",90))};
    try{await postConfig(patch);if(result)result.textContent="Gemt. Controlleren bruger de nye tider ved næste vurdering."}catch(e){if(result)result.textContent=`Fejl: ${e.message}`}finally{if(b)b.disabled=false}
  }
  async function setBoost(minutes){const level=Number(field("#quick-boost-level",6));const targets=qa("[data-quick-boost]");targets.forEach(b=>b.disabled=true);try{await postConfig({quick_boost_level:level,quick_boost_minutes:minutes});await fetchState()}catch(e){const result=q("#automation-save-result")||q("#controller-modern-reason");if(result)result.textContent=`Quick Boost fejl: ${e.message}`}finally{targets.forEach(b=>b.disabled=false)}}

  function localDateTime(v){if(!v)return"";const d=new Date(v);if(Number.isNaN(d.getTime()))return String(v).slice(0,16);const pad=n=>String(n).padStart(2,"0");return`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`}
  function renderDecisionLog(s){
    const root=q("#ctl-decision-log");if(!root)return;const events=Array.isArray(s.decision_log)?s.decision_log.slice(-8).reverse():[];root.replaceChildren();
    if(!events.length){const empty=document.createElement("div");empty.className="decision-empty";empty.textContent="Ingen tilstandsskift registreret endnu.";root.append(empty);return}
    for(const event of events){const row=document.createElement("div");row.className="decision-event";const timeEl=document.createElement("time");const d=new Date(Number(event.timestamp||0)*1000);timeEl.textContent=Number.isNaN(d.getTime())?"—":d.toLocaleTimeString("da-DK",{hour:"2-digit",minute:"2-digit",second:"2-digit"});const source=document.createElement("b");source.textContent=String(event.source||"—").replaceAll("_"," ");const level=document.createElement("span");level.className="decision-level";level.textContent=event.level?`Trin ${event.level}`:"—";const reason=document.createElement("span");reason.className="decision-reason";reason.textContent=event.reason||"Tilstand ændret";row.append(timeEl,source,level,reason);root.append(row)}
  }
  function render(){
    installDashboardControls();installControllerTools();
    const s=controller||{};
    value("#quick-boost-level",s.quick_boost_level||6);value("#vacation-until",localDateTime(s.vacation_until));value("#cooling-start-delay",s.cooling_start_delay_seconds??180);value("#cooling-min-on",s.cooling_min_on_seconds??600);value("#cooling-min-off",s.cooling_min_off_seconds??300);value("#cooling-transition-timeout",s.cooling_transition_timeout_seconds??90);
    const boostRemaining=Number(s.quick_boost_remaining_seconds)||0,boostText=boostRemaining>0?duration(boostRemaining):"Ikke aktiv";text("#quick-boost-label",boostText);text("#boost-remaining",boostText);text("#ctl-boost-remaining",boostText);text("#ctl-boost-summary",boostText);
    const cool=coolingLabels[s.cooling_state]||String(s.cooling_state||"—").replaceAll("_"," ");let coolingDetail=cool;if(s.cooling_state==="qualifying"&&s.cooling_qualification_remaining_seconds!=null)coolingDetail+=` · ${duration(s.cooling_qualification_remaining_seconds)}`;if(s.cooling_state==="minimum_on_hold"&&s.cooling_min_on_remaining_seconds)coolingDetail+=` · ${duration(s.cooling_min_on_remaining_seconds)}`;if(s.cooling_state==="minimum_off_hold"&&s.cooling_min_off_remaining_seconds)coolingDetail+=` · ${duration(s.cooling_min_off_remaining_seconds)}`;text("#cooling-state",coolingDetail);text("#ctl-cooling-state",coolingDetail);text("#ctl-cooling-summary",coolingDetail);
    text("#ctl-effective-source",String(s.effective_source||"—").replaceAll("_"," "));const physical=live.bypass_active===true?"Åben":live.bypass_active===false?"Lukket":"—";const requested=(s.effective_bypass||s.bypass)==="on"?"Åbn":"Auto";text("#ctl-bypass-summary",`${requested} / ${physical}`);text("#controller-modern-reason",s.effective_reason||"—");
    const vacationRemaining=s.vacation_remaining_seconds;if(q("#vacation-active-label")&&s.vacation_enabled&&vacationRemaining!=null)text("#vacation-active-label",`Aktiv · ${duration(vacationRemaining)} tilbage`);
    const health=s.data_health||{},healthState=healthLabels[health.state]||health.state||"Ukendt";text("#ctl-health-badge",healthState.toUpperCase());text("#ctl-data-health",healthState);text("#ctl-bus-age",health.bus_age_seconds==null?"—":`${Number(health.bus_age_seconds).toLocaleString("da-DK",{maximumFractionDigits:1})} s`);const comfort=s.comfort_guard||{};text("#ctl-comfort",comfortLabels[comfort.state]||comfort.reason||"Ukendt");text("#ctl-decision-count",s.decision_log_size??0);renderDecisionLog(s)
  }

  function boot(){loadAuth();installObservabilityStyles();let attempts=0;const timer=setInterval(()=>{installDashboardControls();installControllerTools();if(++attempts>40)clearInterval(timer)},150);fetchState();setInterval(fetchState,2500)}
  if(document.readyState==="loading")addEventListener("DOMContentLoaded",boot,{once:true});else boot();
})();
