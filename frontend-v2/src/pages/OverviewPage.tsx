import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import { Flame, Gauge, Leaf, Wind } from "lucide-react";
import { postJson, requestJson } from "../lib/api";
import "../styles/overview.css";

type Data = Record<string, unknown>;
type AuthState = { csrf?: string | null };

const NORMAL = {
  outdoor: "M36 160 H302 L445 270",
  supply: "M560 282 L695 346 H1064",
  extract: "M1064 160 H695 L560 258",
  exhaust: "M445 246 L302 346 H36",
};
const BYPASS = {
  outdoor: "M36 160 H300 Q335 160 350 195 L350 318 Q350 346 382 346 H1064",
  supply: "M36 160 H300 Q335 160 350 195 L350 318 Q350 346 382 346 H1064",
  extract: "M1064 160 H710 Q675 160 658 194 L658 312 Q658 346 625 346 H36",
  exhaust: "M1064 160 H710 Q675 160 658 194 L658 312 Q658 346 625 346 H36",
};

function n(value: unknown): number | null {
  const valueNumber = Number(value);
  return Number.isFinite(valueNumber) ? valueNumber : null;
}
function first(source: Data, ...keys: string[]): number | null {
  for (const key of keys) {
    const value = n(source[key]);
    if (value !== null) return value;
  }
  return null;
}
function measurement(source: Data, key: string): number | null {
  const values = source.measurements;
  if (!values || typeof values !== "object") return null;
  return n((values as Record<string, unknown>)[key]);
}
function t(value: unknown, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}
function temp(value: number | null) {
  return value === null ? "—" : `${value.toLocaleString("da-DK", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}°`;
}
function whole(value: number | null) {
  return value === null ? "—" : Math.round(value).toLocaleString("da-DK");
}
function modeLabel(value: unknown) {
  return ({ local_auto: "Local Auto", smart_auto: "Smart Auto", manual: "Manuel" } as Record<string, string>)[String(value)] ?? t(value);
}
function masterLabel(value: unknown) {
  if (value === "pi") return "Raspberry Pi";
  if (value === "hcp4") return "HCP4";
  return "Afventer";
}
function sourceLabel(value: unknown) {
  return t(value).replaceAll("_", " ");
}
function remaining(value: unknown) {
  const seconds = n(value);
  if (seconds === null || seconds <= 0) return "Ikke aktiv";
  const minutes = Math.ceil(seconds / 60);
  return minutes < 60 ? `${minutes} min tilbage` : `${Math.floor(minutes / 60)}t ${minutes % 60}m tilbage`;
}
function coolingLabel(value: unknown) {
  const labels: Record<string, string> = {
    disabled: "Deaktiveret", standby: "Standby", qualifying: "Kvalificerer", opening: "Åbner bypass",
    active: "Aktiv", minimum_on_hold: "Minimum køretid", minimum_off_hold: "Minimum pause",
    outdoor_too_cold: "Ude for kold", not_cooler_outside: "Ude ikke koldere", room_below_start: "Rum under start",
    room_satisfied: "Rumtemperatur nået", sensor_missing: "Mangler sensor", manual_mode: "Manuel mode", vacation: "Ferie",
  };
  return labels[String(value)] ?? sourceLabel(value);
}

function SensorTag({ x, y, code, label, value, anchor = "start", tone = "neutral" }: {
  x: number; y: number; code: string; label: string; value: string;
  anchor?: "start" | "middle" | "end"; tone?: "cold" | "warm" | "neutral" | "green";
}) {
  const width = 112;
  const left = anchor === "middle" ? x - width / 2 : anchor === "end" ? x - width : x;
  return (
    <g className={`sensor-tag tone-${tone}`} transform={`translate(${left} ${y})`}>
      <rect width={width} height="48" rx="11" />
      <circle cx="13" cy="14" r="3.5" />
      <text className="sensor-code" x="22" y="17">{code}</text>
      <text className="sensor-value" x="12" y="35">{value}</text>
      <title>{label}</title>
    </g>
  );
}

export function OverviewPage() {
  const [unit, setUnit] = useState<Data>({});
  const [controller, setController] = useState<Data>({});
  const [csrf, setCsrf] = useState<string | undefined>();
  const [online, setOnline] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string>("");

  const refresh = useCallback(async () => {
    const [unitResult, controllerResult, authResult] = await Promise.allSettled([
      requestJson<Data>("/state.json", { timeoutMs: 3500 }),
      requestJson<Data>("/api/controller/state", { timeoutMs: 3500 }),
      requestJson<AuthState>("/api/auth/status", { timeoutMs: 3500 }),
    ]);
    if (unitResult.status === "fulfilled") setUnit(unitResult.value);
    if (controllerResult.status === "fulfilled") setController(controllerResult.value);
    if (authResult.status === "fulfilled" && authResult.value.csrf) setCsrf(authResult.value.csrf);
    setOnline(unitResult.status === "fulfilled" && controllerResult.status === "fulfilled");
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const command = useCallback(async (name: string, patch: Data, success: string) => {
    if (!csrf) {
      setNotice("Sikkerhedstoken mangler. Genindlæs siden og prøv igen.");
      return;
    }
    setBusy(name);
    setNotice("Gemmer…");
    try {
      const next = await postJson<Data>("/api/controller/config", patch, csrf);
      setController(next);
      setNotice(success);
    } catch (error) {
      setNotice(`Kunne ikke gemme: ${error instanceof Error ? error.message : "ukendt fejl"}`);
      await refresh();
    } finally {
      setBusy(null);
    }
  }, [csrf, refresh]);

  const outdoor = first(unit, "outdoor_temp", "outdoor_temperature");
  const extract = first(unit, "extract_temp", "extract_temperature");
  const exhaust = first(unit, "exhaust_temp", "exhaust_temperature");
  const beforeHeater = first(controller, "actual_supply_before_heater_temperature") ?? first(unit, "supply_temp");
  const afterHeater = first(controller, "actual_supply_air_temperature") ?? first(unit, "heating_coil_after_temperature", "supply_temp");
  const room = measurement(controller, "room") ?? first(unit, "hrc2_t5_temperature", "room_temp", "extract_temp");
  const frost = first(controller, "actual_afterheat_frost_temperature") ?? first(unit, "heating_coil_frost_temperature");
  const flowWater = first(unit, "flow_temperature");
  const returnWater = first(unit, "return_temperature");
  const supplyRpm = first(controller, "actual_fan_supply_rpm") ?? first(unit, "fan_supply_rpm");
  const extractRpm = first(controller, "actual_fan_extract_rpm") ?? first(unit, "fan_extract_rpm");
  const supplyPercent = first(controller, "actual_fan_supply_percent") ?? first(unit, "fan_supply_percent");
  const extractPercent = first(controller, "actual_fan_extract_percent") ?? first(unit, "fan_extract_percent");
  const humidity = first(unit, "humidity", "relative_humidity");
  const co2 = first(unit, "co2");
  const filterLife = first(unit, "filter_life_percent");
  const bypassActual = unit.bypass_active === true || controller.actual_bypass === true;
  const bypassRequest = String(controller.actual_bypass_request ?? unit.bypass_request ?? controller.bypass ?? "off");
  const heating = controller.actual_afterheat === true || unit.afterheat_active === true;
  const fireplace = controller.actual_fireplace === true || unit.fireplace === true;
  const routes = bypassActual ? BYPASS : NORMAL;
  const mode = String(controller.mode ?? "local_auto");
  const level = n(controller.effective_level) ?? 3;
  const afterheatSetpoint = n(controller.afterheat_setpoint) ?? 20;
  const quickBoostActive = (n(controller.quick_boost_remaining_seconds) ?? 0) > 0;
  const busHealthy = controller.rs485_healthy === true || unit.available === true;
  const recovery = useMemo(() => {
    if (bypassActual || outdoor === null || extract === null || exhaust === null || Math.abs(extract - outdoor) < 0.5) return null;
    const value = ((extract - exhaust) / (extract - outdoor)) * 100;
    return value >= 0 && value <= 105 ? Math.round(value) : null;
  }, [bypassActual, outdoor, extract, exhaust]);
  const supplySpeed = supplyRpm && supplyRpm > 0 ? Math.max(0.75, 3.2 - supplyRpm / 750) : 0;
  const extractSpeed = extractRpm && extractRpm > 0 ? Math.max(0.75, 3.2 - extractRpm / 750) : 0;
  const levelPatch = mode === "manual" ? "manual_level" : "local_normal_level";

  return (
    <section className="page-view page-enter overview-live">
      <header className="page-hero overview-hero">
        <div><span className="eyebrow">OVERBLIK</span><h1>Ventilation, samlet ét sted</h1><p>Live HCH5, HAC1, temperaturer, luftstrømme og den styring der faktisk er aktiv lige nu.</p></div>
        <div className="hero-status-grid">
          <div><span>Master</span><strong>{masterLabel(controller.active_master)}</strong></div>
          <div><span>Bus</span><strong className={busHealthy ? "ok-text" : "warn-text"}>{busHealthy ? "Sund" : "Afventer"}</strong></div>
          <div><span>Mode</span><strong>{modeLabel(controller.mode)}</strong></div>
        </div>
      </header>

      <div className="overview-grid-v2">
        <article className="surface airflow-card-v2 airflow-card-live">
          <div className="section-head">
            <div><span className="eyebrow">LUFTSTRØM · LIVE</span><h2>HCH5 varmegenvinding</h2></div>
            <span className={`status-chip ${online ? "" : "muted"}`}><span className="live-dot" /> {online ? "Live data" : "Forbindelse afventer"}</span>
          </div>

          <div className={`airflow-stage airflow-stage-live ${bypassActual ? "bypass-open" : "heat-recovery"}`} aria-label="HCH5 luftstrøm med fysisk bypass, sensorer og eftervarme">
            <span className="sr-only">Bypass faktisk lukket eller åbent afhængigt af live data.</span>
            <svg viewBox="0 0 1100 505" role="img">
              <defs>
                <filter id="glow"><feGaussianBlur stdDeviation="3.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
                <linearGradient id="coldAir" x1="0" x2="1"><stop offset="0" stopColor="#58a9e8"/><stop offset="1" stopColor="#72d4c3"/></linearGradient>
                <linearGradient id="warmAir" x1="0" x2="1"><stop offset="0" stopColor="#ffb45b"/><stop offset="1" stopColor="#d67b5b"/></linearGradient>
                <linearGradient id="supplyAir" x1="0" x2="1"><stop offset="0" stopColor="#63d1b1"/><stop offset="1" stopColor="#5eb9ea"/></linearGradient>
              </defs>
              <rect className="unit-shell live-shell" x="276" y="82" width="500" height="350" rx="38" />
              <text className="unit-title" x="526" y="111" textAnchor="middle">HCH5 · HCH5 CONTROL</text>
              <path className="duct-bg" d={routes.outdoor}/><path className="duct-bg" d={routes.supply}/><path className="duct-bg" d={routes.extract}/><path className="duct-bg" d={routes.exhaust}/>
              <path className={`flow-line outdoor-flow ${supplySpeed === 0 ? "stopped" : ""}`} style={{ animationDuration: supplySpeed ? `${supplySpeed}s` : undefined }} d={routes.outdoor}/>
              <path className={`flow-line supply-flow ${supplySpeed === 0 ? "stopped" : ""}`} style={{ animationDuration: supplySpeed ? `${supplySpeed}s` : undefined }} d={routes.supply}/>
              <path className={`flow-line extract-flow ${extractSpeed === 0 ? "stopped" : ""}`} style={{ animationDuration: extractSpeed ? `${extractSpeed}s` : undefined }} d={routes.extract}/>
              <path className={`flow-line exhaust-flow ${extractSpeed === 0 ? "stopped" : ""}`} style={{ animationDuration: extractSpeed ? `${extractSpeed}s` : undefined }} d={routes.exhaust}/>
              <g className={`exchanger live-exchanger ${bypassActual ? "bypassed" : ""}`} transform="translate(505 258) rotate(45)"><rect x="-78" y="-78" width="156" height="156" rx="27" /><path d="M-51 -38 H51 M-51 -13 H51 M-51 12 H51 M-51 37 H51" /></g>
              <text className="recovery-label" x="505" y="252" textAnchor="middle">{recovery === null ? "—" : `${recovery}%`}</text><text className="recovery-sub" x="505" y="272" textAnchor="middle">{bypassActual ? "BYPASSET" : "GENVINDING"}</text>
              <g className={`bypass-gate ${bypassActual ? "open" : "closed"}`} transform="translate(638 205)"><rect x="-54" y="-19" width="108" height="38" rx="12" /><path d="M-32 0 H32" /><circle cx={bypassActual ? 27 : -27} cy="0" r="9" /><text x="0" y="38" textAnchor="middle">BYPASS {bypassActual ? "ÅBEN" : "LUKKET"}</text></g>
              <g className={`fan-v2 live-fan extract-fan ${extractSpeed === 0 ? "stopped" : ""}`} style={{ "--fan-speed": extractSpeed ? `${extractSpeed}s` : "0s" } as CSSProperties} transform="translate(742 160)"><circle r="33"/><path d="M0-21c18 0 23 13 12 21C5 6-2 0 0-21Zm19 12c8 16-1 26-15 21-9-3-4-11 15-21Zm-19 19c-17 2-24-11-14-21 8-8 13-1 14 21Z" /></g>
              <g className={`fan-v2 live-fan supply-fan ${supplySpeed === 0 ? "stopped" : ""}`} style={{ "--fan-speed": supplySpeed ? `${supplySpeed}s` : "0s" } as CSSProperties} transform="translate(742 346)"><circle r="33"/><path d="M0-21c18 0 23 13 12 21C5 6-2 0 0-21Zm19 12c8 16-1 26-15 21-9-3-4-11 15-21Zm-19 19c-17 2-24-11-14-21 8-8 13-1 14 21Z" /></g>
              <g className={`heater-coil ${heating ? "active" : ""}`} transform="translate(860 346)"><rect x="-31" y="-41" width="62" height="82" rx="12" /><path d="M-16-26 C18-18-18-5 16 3 C-18 12 18 24-16 31" /><text x="0" y="61" textAnchor="middle">EFTERVARME</text></g>
              <path className="water-loop flow" d="M842 390 V445 H910 V390" /><path className="water-loop return" d="M856 390 V426 H896 V390" /><text className="water-label" x="924" y="427">F {temp(flowWater)}</text><text className="water-label" x="924" y="444">R {temp(returnWater)}</text>
              <g className="air-label endpoint left top"><text x="36" y="119">UDELUFT</text><text className="temp" x="36" y="144">{temp(outdoor)}</text></g>
              <g className="air-label endpoint left bottom"><text x="36" y="390">AFKAST</text><text className="temp" x="36" y="415">{temp(exhaust)}</text></g>
              <g className="air-label endpoint right top"><text x="1064" y="119" textAnchor="end">UDSUGNING</text><text className="temp" x="1064" y="144" textAnchor="end">{temp(extract)}</text></g>
              <g className="air-label endpoint right bottom"><text x="1064" y="390" textAnchor="end">INDBLÆSNING</text><text className="temp" x="1064" y="415" textAnchor="end">{temp(afterHeater)}</text></g>
              <SensorTag x={300} y={118} code="T1" label="Udeluftsensor" value={temp(outdoor)} tone="cold" />
              <SensorTag x={300} y={367} code="T4" label="Afkasttemperatur" value={temp(exhaust)} tone="neutral" />
              <SensorTag x={646} y={118} code="T3" label="Udsugningstemperatur" value={temp(extract)} tone="warm" />
              <SensorTag x={790} y={286} code="T2" label="Indblæsning før eftervarme" value={temp(beforeHeater)} tone="green" />
              <SensorTag x={935} y={286} code="T2AH" label="Indblæsning efter eftervarme" value={temp(afterHeater)} tone={heating ? "warm" : "green"} />
              <SensorTag x={1002} y={205} code="T5" label="Rumtemperatur" value={temp(room)} anchor="end" tone="warm" />
              <SensorTag x={895} y={205} code="FROST" label="Eftervarme frostsensor" value={temp(frost)} anchor="end" tone="cold" />
            </svg>
          </div>

          <div className="airflow-footer live-footer">
            <span><i className="legend-dot supply" /> Indblæsning {whole(supplyRpm)} RPM · {whole(supplyPercent)}%</span><span><i className="legend-dot extract" /> Udsugning {whole(extractRpm)} RPM · {whole(extractPercent)}%</span><span><i className={`legend-dot ${bypassActual ? "active" : "neutral"}`} /> Bypass faktisk {bypassActual ? "åben" : "lukket"}</span><span>Ønske: {bypassRequest === "on" || bypassRequest === "255" ? "On" : "Auto"}</span><span>Eftervarme: {heating ? "aktiv" : "inaktiv"}</span>
          </div>
          <div className="inline-bypass-control"><div><span>Bypass styring</span><small>Auto lader HCH5 bestemme fysisk position. On beder om bypass.</small></div><div className="mini-segmented"><button disabled={busy !== null} className={controller.bypass !== "on" ? "active" : ""} onClick={() => void command("bypass", { bypass: "off" }, "Bypass sat til Auto")}>Auto</button><button disabled={busy !== null || fireplace} className={controller.bypass === "on" ? "active" : ""} onClick={() => void command("bypass", { bypass: "on" }, "Bypass ønskes åbnet")}>On</button></div></div>
        </article>

        <aside className="control-column">
          <article className="surface control-card-v2">
            <div className="section-head compact"><div><span className="eyebrow">DAGLIG STYRING</span><h2>Ventilation</h2></div><Gauge size={21} /></div>
            <div className="segmented-v2">{(["local_auto", "smart_auto", "manual"] as const).map(value => <button key={value} disabled={busy !== null} className={mode === value ? "active" : ""} onClick={() => void command("mode", { mode: value }, `${modeLabel(value)} valgt`)}>{modeLabel(value)}</button>)}</div>
            <div className="level-row"><span>{mode === "manual" ? "Manuelt niveau" : "Normalniveau"}</span><div>{[1,2,3,4,5,6].map(item => <button disabled={busy !== null} key={item} className={Number(level) === item ? "active" : ""} onClick={() => void command("level", { [levelPatch]: item }, `Niveau ${item} gemt`)}>{item}</button>)}</div></div>
            <div className="control-summary"><span>Aktiv beslutning</span><strong>Trin {level} · {sourceLabel(controller.effective_source)}</strong><small>{t(controller.effective_reason, "Afventer controllerbeslutning")}</small></div>
            {notice && <div className={`control-notice ${notice.startsWith("Kunne") ? "error" : ""}`}>{notice}</div>}
          </article>

          <article className="surface quick-card quick-card-live"><div className="quick-icon"><Wind size={20}/></div><div><span>Quick Boost</span><strong>{quickBoostActive ? remaining(controller.quick_boost_remaining_seconds) : "15 · 30 · 60 min"}</strong></div><div className="quick-actions">{quickBoostActive ? <button disabled={busy !== null} onClick={() => void command("boost", { quick_boost_minutes: 0 }, "Quick Boost stoppet")}>Stop</button> : [15,30,60].map(minutes => <button disabled={busy !== null || fireplace} key={minutes} onClick={() => void command("boost", { quick_boost_minutes: minutes }, `Quick Boost startet i ${minutes} min`)}>{minutes}</button>)}</div></article>
          <article className="surface quick-card quick-card-live"><div className="quick-icon warm"><Flame size={20}/></div><div><span>Eftervarme</span><strong>{afterheatSetpoint}° setpunkt · {heating ? "aktiv" : "inaktiv"}</strong></div><div className="quick-actions stepper"><button disabled={busy !== null || afterheatSetpoint <= 18} onClick={() => void command("afterheat", { afterheat_setpoint: afterheatSetpoint - 1 }, `Eftervarme ønsket ${afterheatSetpoint - 1}°`)}>−</button><button disabled={busy !== null || afterheatSetpoint >= 30} onClick={() => void command("afterheat", { afterheat_setpoint: afterheatSetpoint + 1 }, `Eftervarme ønsket ${afterheatSetpoint + 1}°`)}>+</button></div></article>
          <article className="surface quick-card quick-card-live"><div className="quick-icon green"><Leaf size={20}/></div><div><span>Frikøling</span><strong>{controller.cooling_enabled === true ? coolingLabel(controller.cooling_state) : "Deaktiveret"}</strong></div><button disabled={busy !== null || mode === "manual"} onClick={() => void command("cooling", { cooling_enabled: controller.cooling_enabled !== true }, controller.cooling_enabled === true ? "Frikøling deaktiveret" : "Frikøling aktiveret")}>{controller.cooling_enabled === true ? "Slå fra" : "Aktiver"}</button></article>
          <article className="surface quick-card quick-card-live"><div className="quick-icon warm"><Flame size={20}/></div><div><span>Pejsefunktion</span><strong>{fireplace ? remaining(controller.fireplace_remaining_seconds) : "Slukket"}</strong></div><div className="quick-actions">{fireplace ? <button disabled={busy !== null} onClick={() => void command("fireplace", { fireplace_minutes: 0 }, "Pejsefunktion stoppet")}>Stop</button> : <><button disabled={busy !== null || controller.bypass === "on"} onClick={() => void command("fireplace", { fireplace_minutes: 15 }, "Pejsefunktion 15 min")}>15</button><button disabled={busy !== null || controller.bypass === "on"} onClick={() => void command("fireplace", { fireplace_minutes: 30 }, "Pejsefunktion 30 min")}>30</button></>}</div></article>
        </aside>
      </div>

      <div className="metrics-row-v2 overview-metrics-live">
        <article className="surface metric-v2"><span>CO₂</span><strong>{whole(co2)} <small>ppm</small></strong><em className={co2 !== null && co2 < 800 ? "good-pill" : ""}>{co2 === null ? "Ingen data" : co2 < 800 ? "God" : co2 < 1200 ? "Moderat" : "Høj"}</em></article>
        <article className="surface metric-v2"><span>Luftfugtighed</span><strong>{whole(humidity)} <small>%</small></strong><em>{humidity === null ? "Ingen data" : `${whole(humidity)} % RH`}</em></article>
        <article className="surface metric-v2"><span>Filter</span><strong>{whole(filterLife)} <small>%</small></strong><div className="mini-meter"><i style={{ width: `${Math.max(0, Math.min(100, filterLife ?? 0))}%` }}/></div><em>{t(unit.filter_status, "Lokal filterstatus")}</em></article>
        <article className="surface metric-v2"><span>Eftervarme</span><strong>{heating ? "Aktiv" : "Standby"}</strong><em>{temp(beforeHeater)} før · {temp(afterHeater)} efter</em></article>
        <article className="surface metric-v2"><span>Rum / T5</span><strong>{temp(room)}</strong><em>Lokalt referencepunkt</em></article>
        <article className="surface metric-v2"><span>Frostføler</span><strong>{temp(frost)}</strong><em>HAC1 sikkerhed</em></article>
        <article className="surface metric-v2"><span>Vandkreds</span><strong>{temp(flowWater)}</strong><em>Fremløb · retur {temp(returnWater)}</em></article>
        <article className="surface metric-v2"><span>Controller</span><strong>Trin {level}</strong><em>{controller.hardware_writes_allowed === true ? "Pi skriver til anlægget" : `Writes pauset · ${masterLabel(controller.active_master)}`}</em></article>
      </div>
    </section>
  );
}
