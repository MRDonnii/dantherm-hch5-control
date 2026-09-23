import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Flame, Gauge, Leaf, Snowflake, Wind, X } from "lucide-react";
import { Hch5UnitDiagram } from "../components/Hch5UnitDiagram";
import { HistoryChart, type HistorySeries } from "../components/HistoryChart";
import { postJson, requestJson } from "../lib/api";
import { bypassTravel, formatRemaining } from "../lib/bypass";
import { useTopbarNotice } from "../lib/topbar-notice";
import "../styles/overview.css";
import "../styles/history.css";

type Data = Record<string, unknown>;
type AfterheatValue = number | "off";
type AuthState = { csrf?: string | null };
// +/- only move a local draft; one command is sent once the user has stopped
// pressing, so each step does not wait for a save and RS485 round trip.
const AFTERHEAT_SEND_DELAY_MS = 1200;
const SENSOR_HISTORY: Record<string, { title: string; key: string; color: HistorySeries["color"] }> = {
  outdoor: { title: "Udeluft · T1", key: "outdoor_temp", color: "blue" },
  extract: { title: "Udsugning · T3", key: "extract_temp", color: "orange" },
  exhaust: { title: "Afkast · T4", key: "exhaust_temp", color: "red" },
  beforeHeater: { title: "T2 før eftervarme", key: "supply_temp", color: "blue" },
  afterHeater: { title: "T2AH efter eftervarme", key: "heating_coil_after_temperature", color: "green" },
  room: { title: "Rum · T5", key: "hrc2_t5_temperature", color: "green" },
  frost: { title: "Frostsensor", key: "heating_coil_frost_temperature", color: "blue" },
  flowWater: { title: "Eftervarmevand · Frem", key: "flow_temperature", color: "orange" },
  returnWater: { title: "Eftervarmevand · Retur", key: "return_temperature", color: "blue" },
  waterDelta: { title: "Eftervarmevand · Afkøl", key: "water_delta", color: "green" },
};
type HistorySample = Record<string, number | null>;

function number(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
function first(source: Data, ...keys: string[]) {
  for (const key of keys) {
    const value = number(source[key]);
    if (value !== null) return value;
  }
  return null;
}
function measurement(source: Data, key: string) {
  const values = source.measurements;
  return values && typeof values === "object" ? number((values as Data)[key]) : null;
}
function text(value: unknown, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}
function temp(value: number | null) {
  // Non-breaking space keeps the value and its unit on one line.
  return value === null ? "—" : `${value.toLocaleString("da-DK", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}\u00a0°C`;
}
function whole(value: number | null) {
  return value === null ? "—" : Math.round(value).toLocaleString("da-DK");
}
function modeLabel(value: unknown) {
  return ({ local_auto: "Local Auto", smart_auto: "Smart Auto", manual: "Manuel" } as Record<string, string>)[String(value)] ?? text(value);
}
function masterLabel(value: unknown) {
  if (value === "pi") return "Raspberry Pi";
  if (value === "hcp4") return "HCP4";
  return "Afventer";
}
function coolingLabel(value: unknown) {
  const labels: Record<string, string> = {
    disabled: "Standby", standby: "Standby", qualifying: "Kvalificerer", opening: "Åbner bypass",
    active: "Aktiv", minimum_on_hold: "Minimum køretid", minimum_off_hold: "Minimum pause",
    outdoor_too_cold: "Ude for kold", not_cooler_outside: "Ude ikke koldere", room_below_start: "Rum under start",
    room_satisfied: "Rumtemperatur nået", sensor_missing: "Mangler sensor", manual_mode: "Manuel mode", vacation: "Ferie",
  };
  return labels[String(value)] ?? text(value).replaceAll("_", " ");
}
function remaining(value: unknown) {
  const seconds = number(value);
  if (seconds === null || seconds <= 0) return "Ikke aktiv";
  const minutes = Math.ceil(seconds / 60);
  return `${minutes} min tilbage`;
}

export function OverviewPage() {
  const [unit, setUnit] = useState<Data>({});
  const [controller, setController] = useState<Data>({});
  const [csrf, setCsrf] = useState("");
  const [online, setOnline] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const { setNotice } = useTopbarNotice();
  const [afterheatDraft, setAfterheatDraft] = useState<AfterheatValue | null>(null);
  const afterheatTimer = useRef<number | null>(null);
  const afterheatPending = useRef<{ target: AfterheatValue; seq: number } | null>(null);
  const afterheatSeq = useRef(0);
  const thermostatDraft = useRef<Record<string, number | null>>({});
  const thermostatTimers = useRef<Record<string, number>>({});
  const [, setThermostatRevision] = useState(0);
  const [activeSensor, setActiveSensor] = useState<string | null>(null);
  const [historySamples, setHistorySamples] = useState<HistorySample[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const closeHistoryRef = useRef<HTMLButtonElement>(null);

  const refresh = useCallback(async () => {
    const [unitResult, controllerResult, authResult] = await Promise.allSettled([
      requestJson<Data>("/state.json", { timeoutMs: 3500 }),
      requestJson<Data>("/api/controller/state", { timeoutMs: 3500 }),
      requestJson<AuthState>("/api/auth/status", { timeoutMs: 3500 }),
    ]);
    if (unitResult.status === "fulfilled") setUnit(unitResult.value);
    if (controllerResult.status === "fulfilled") setController(controllerResult.value);
    if (authResult.status === "fulfilled") setCsrf(authResult.value.csrf ?? "");
    setOnline(unitResult.status === "fulfilled" && controllerResult.status === "fulfilled");
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!activeSensor) return;
    let cancelled = false;
    const loadHistory = async () => {
      try {
        const result = await requestJson<{ samples: HistorySample[] }>("/history.json?range=24h", { timeoutMs: 6000 });
        if (!cancelled) { setHistorySamples(Array.isArray(result.samples) ? result.samples.map(sample => ({ ...sample, water_delta: typeof sample.flow_temperature === "number" && typeof sample.return_temperature === "number" ? sample.flow_temperature - sample.return_temperature : null })) : []); setHistoryError(""); }
      } catch {
        if (!cancelled) setHistoryError("Historikken kunne ikke hentes. Prøv igen senere.");
      } finally {
        if (!cancelled) setHistoryLoading(false);
      }
    };
    setHistorySamples([]);
    setHistoryError("");
    setHistoryLoading(true);
    void loadHistory();
    const timer = window.setInterval(() => void loadHistory(), 60000);
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") setActiveSensor(null); };
    window.addEventListener("keydown", onKeyDown);
    closeHistoryRef.current?.focus();
    return () => { cancelled = true; window.clearInterval(timer); window.removeEventListener("keydown", onKeyDown); };
  }, [activeSensor]);

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

  const stepThermostat = (key: "t3_setpoint" | "t5_setpoint", label: string, current: number | null, direction: 1 | -1) => {
    const next = direction > 0
      ? current === null ? 10 : Math.min(35, current + 1)
      : current === null || current <= 10 ? null : current - 1;
    thermostatDraft.current[key] = next;
    setThermostatRevision(value => value + 1);
    window.clearTimeout(thermostatTimers.current[key]);
    thermostatTimers.current[key] = window.setTimeout(async () => {
      delete thermostatTimers.current[key];
      const value = next === null ? "OFF" : `${next} °C`;
      await command(
        key,
        { [key]: next },
        `${label} er gemt lokalt som ${value}; ingen hardwarekommando sendt.`,
      );
      if (thermostatDraft.current[key] === next) {
        delete thermostatDraft.current[key];
        setThermostatRevision(value => value + 1);
      }
    }, AFTERHEAT_SEND_DELAY_MS);
  };

  const sendAfterheat = useCallback(async (target: AfterheatValue, seq: number) => {
    await command(
      "afterheat",
      target === "off" ? { afterheat_enabled: false } : { afterheat_setpoint: target },
      target === "off" ? "Eftervarmen er sat til OFF." : `Eftervarmen er sat til ${target} °C.`,
    );
    // A newer press may have started another draft while this one was saving.
    if (afterheatSeq.current === seq) setAfterheatDraft(null);
  }, [command]);

  const flushAfterheat = useCallback(() => {
    if (afterheatTimer.current !== null) window.clearTimeout(afterheatTimer.current);
    afterheatTimer.current = null;
    const pending = afterheatPending.current;
    afterheatPending.current = null;
    if (pending) void sendAfterheat(pending.target, pending.seq);
  }, [sendAfterheat]);

  // Leaving the page must not drop a change that is still waiting to be sent.
  const flushAfterheatRef = useRef(flushAfterheat);
  flushAfterheatRef.current = flushAfterheat;
  useEffect(() => () => flushAfterheatRef.current(), []);

  const outdoor = first(unit, "outdoor_temp", "outdoor_temperature");
  const extract = first(unit, "extract_temp", "extract_temperature");
  const exhaust = first(unit, "exhaust_temp", "exhaust_temperature");
  const beforeHeater = first(controller, "actual_supply_before_heater_temperature") ?? first(unit, "supply_temperature", "supply_temp");
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
  const bypassRaw = number(controller.actual_bypass_raw) ?? number(unit.bypass_raw);
  const bypassMoving = bypassRaw !== null && bypassRaw !== 0 && bypassRaw !== 255;
  const bypassRequest = String(controller.actual_bypass_request ?? unit.bypass_request ?? controller.bypass ?? "off");
  // The damper takes about three minutes: say which way it runs, how far
  // along it is and how long is left, from the moment On is read back.
  const bypassTravelDirection = controller.actual_bypass_travel_direction as string | null | undefined;
  const bypassTravelSeconds = number(controller.actual_bypass_travel_seconds);
  const bypassTravelTotal = number(controller.bypass_travel_expected_seconds);
  const bypassRun = bypassTravel({ raw: bypassRaw, requestOn: bypassRequest.toLowerCase() === "on", direction: bypassTravelDirection, seconds: bypassTravelSeconds, total: bypassTravelTotal });
  const bypassActualLabel = bypassRun
    ? [
        bypassRun.direction === "opening" ? "åbner" : bypassRun.direction === "closing" ? "lukker" : "bevæger sig",
        bypassRun.percent === null ? null : `${bypassRun.percent} %`,
        bypassRun.awaitingEnd ? "afventer endestilling" : null,
        bypassRun.remainingSeconds === null ? null : `${formatRemaining(bypassRun.remainingSeconds)} tilbage`,
      ].filter(Boolean).join(" · ")
    : bypassActual ? "åben" : "lukket";
  const heatKnown = typeof controller.actual_afterheat === "boolean" || typeof unit.afterheat_active === "boolean";
  const heating = controller.actual_afterheat === true || unit.afterheat_active === true;
  // HAC1 never heats at 15 C outdoor or above; say so instead of just "Inaktiv".
  const afterheatLockout = controller.actual_afterheat_outdoor_lockout === true;
  const afterheatCutoff = number(controller.afterheat_outdoor_cutoff) ?? 15;
  const afterheatStatus = heating ? "Aktiv" : afterheatLockout ? "Spærret af sommerstop" : heatKnown ? "Inaktiv" : "Ukendt";
  const fireplace = controller.actual_fireplace === true || unit.fireplace === true;
  const mode = String(controller.mode ?? "local_auto");
  const level = number(controller.effective_level) ?? 3;
  const afterheatSetpoint = number(controller.afterheat_setpoint) ?? 20;
  const afterheatEnabled = controller.afterheat_enabled !== false;
  const shownAfterheat: AfterheatValue = afterheatDraft ?? (afterheatEnabled ? afterheatSetpoint : "off");
  const actualAfterheatSelectionNumber = number(controller.actual_afterheat_selection);
  const actualAfterheatSelection = controller.actual_afterheat_selection === "off"
    ? "OFF"
    : actualAfterheatSelectionNumber !== null
      ? `${whole(actualAfterheatSelectionNumber)} °C`
      : "Afventer";
  const busHealthy = controller.rs485_healthy === true || unit.bus_traffic === true || unit.available === true;
  const quickBoostActive = (number(controller.quick_boost_remaining_seconds) ?? 0) > 0;

  const recovery = useMemo(() => {
    if (bypassActual || outdoor === null || extract === null || exhaust === null || Math.abs(extract - outdoor) < .5) return null;
    const value = ((extract - exhaust) / (extract - outdoor)) * 100;
    return value >= 0 && value <= 105 ? Math.round(value) : null;
  }, [bypassActual, outdoor, extract, exhaust]);

  const levelPatch = mode === "manual" ? "manual_level" : "local_normal_level";
  // Remote-style range: OFF - 10 - 11 ... 35. Minus below 10 selects OFF.
  const stepAfterheat = (direction: 1 | -1) => {
    const next: AfterheatValue = direction > 0
      ? shownAfterheat === "off" ? 10 : Math.min(35, shownAfterheat + 1)
      : shownAfterheat === "off" || shownAfterheat <= 10 ? "off" : shownAfterheat - 1;
    const seq = ++afterheatSeq.current;
    setAfterheatDraft(next);
    afterheatPending.current = { target: next, seq };
    if (afterheatTimer.current !== null) window.clearTimeout(afterheatTimer.current);
    afterheatTimer.current = window.setTimeout(flushAfterheat, AFTERHEAT_SEND_DELAY_MS);
  };

  return (
    <section className="dashboard-overview page-enter">
      <header className="overview-heading-row">
        <div>
          <span className="eyebrow">OVERBLIK</span>
          <h1>Aktuel drift og status</h1>
          <p>Live visning af HCH5, luftveje, sensorer og den styring der er aktiv lige nu.</p>
        </div>
        <div className="overview-status-pills">
          <div><span className="status-led"/><small>Master</small><strong>{masterLabel(controller.active_master)}</strong></div>
          <div><span className={`status-led ${busHealthy ? "" : "warn"}`}/><small>Bus</small><strong>{busHealthy ? "Sund" : "Afventer"}</strong></div>
          <div><Leaf size={18}/><small>Driftstilstand</small><strong>{modeLabel(controller.mode)}</strong></div>
        </div>
      </header>

      <div className="dashboard-main-grid">
        <article className="surface pro-air-card">
          <div className="pro-card-head">
            <div><h2>Luftstrømme og temperaturer</h2><p>Live luftveje gennem HCH5 med aktuelle temperaturer og fysisk status.</p></div>
            <span className={`status-chip${online ? "" : " muted"}`}><span className="live-dot"/>{online ? "Live" : "Afventer"}</span>
          </div>
          <Hch5UnitDiagram
            onTemperatureClick={setActiveSensor}
            outdoor={outdoor} extract={extract} exhaust={exhaust} beforeHeater={beforeHeater} afterHeater={afterHeater}
            room={room} frost={frost} flowWater={flowWater} returnWater={returnWater}
            supplyRpm={supplyRpm} extractRpm={extractRpm} supplyPercent={supplyPercent} extractPercent={extractPercent}
            bypassActual={bypassActual} bypassRequest={bypassRequest} heating={heating} recovery={recovery}
            busActive={busHealthy} bypassRaw={bypassRaw} afterheatLockout={afterheatLockout}
            bypassTravelDirection={bypassTravelDirection} bypassTravelSeconds={bypassTravelSeconds} bypassTravelTotal={bypassTravelTotal}
          />
        </article>

        <aside className="pro-control-column">
          <article className="surface pro-control-card">
            <div className="pro-card-head compact"><div><h2>Drift og styring</h2><p>Daglige funktioner</p></div><Gauge size={22}/></div>
            <label className="control-label">Ventilationstilstand</label>
            <div className="pro-segment three">
              {["local_auto", "smart_auto", "manual"].map(value => (
                <button key={value} className={mode === value ? "active" : ""} disabled={busy !== null} onClick={() => void command(`mode-${value}`, { mode: value }, `${modeLabel(value)} valgt.`)}>{modeLabel(value)}</button>
              ))}
            </div>
            <label className="control-label">Ventilatorniveau</label>
            <div className="pro-levels">
              {[1,2,3,4,5,6].map(value => <button key={value} className={level === value ? "active" : ""} disabled={busy !== null} onClick={() => void command(`level-${value}`, { [levelPatch]: value }, `Ventilation sat til trin ${value}.`)}>{value}</button>)}
            </div>
            <div className="active-decision"><span>Aktiv beslutning</span><strong>Trin {whole(level)} · {text(controller.effective_source).replaceAll("_", " ")}</strong><small>{text(controller.effective_reason, "Afventer controllerens beslutning")}</small></div>
          </article>

          <div className="pro-control-pair">
            <article className="surface mini-control">
              <div className="mini-control-title"><Wind size={20}/><strong>Hurtig boost</strong></div>
              <div className="mini-buttons three">
                {[15,30,60].map(minutes => <button key={minutes} className={quickBoostActive && number(controller.quick_boost_minutes) === minutes ? "active" : ""} disabled={busy !== null || fireplace} onClick={() => void command(`boost-${minutes}`, { quick_boost_minutes: minutes }, `Quick Boost ${minutes} min startet.`)}>{minutes} min</button>)}
              </div>
              {quickBoostActive && <button className="text-action" onClick={() => void command("boost-stop", { quick_boost_minutes: 0 }, "Quick Boost stoppet.")}>{remaining(controller.quick_boost_remaining_seconds)} · stop</button>}
            </article>

            <article className="surface mini-control">
              <div className="mini-control-title"><ArrowRight size={20}/><strong>Bypass-styring</strong></div>
              <div className="mini-buttons two">
                <button className={String(controller.bypass ?? "off") === "off" ? "active" : ""} disabled={busy !== null || bypassMoving} onClick={() => void command("bypass-auto", { bypass: "off" }, "Bypass sat til Auto.")}>Auto</button>
                <button className={String(controller.bypass) === "on" ? "active" : ""} disabled={busy !== null || fireplace || bypassMoving} onClick={() => void command("bypass-on", { bypass: "on" }, "Bypass ønskes åben.")}>On</button>
              </div>
              <small className="control-footnote">Faktisk: {bypassActualLabel}</small>
            </article>
          </div>

          <div className="pro-control-pair">
            <article className="surface status-action-card">
              <div className="status-action-icon"><Snowflake size={24}/></div>
              <div><span>Frikøling</span><strong>{coolingLabel(controller.cooling_state)}</strong><small>{controller.cooling_enabled === true ? "Automatik aktiv" : "Deaktiveret"}</small></div>
              <button disabled={busy !== null} onClick={() => void command("cooling", { cooling_enabled: controller.cooling_enabled !== true }, controller.cooling_enabled === true ? "Frikøling deaktiveret." : "Frikøling aktiveret.")}><ArrowRight size={17}/></button>
            </article>
            <article className="surface status-action-card">
              <div className="status-action-icon flame"><Flame size={24}/></div>
              <div><span>Pejsefunktion</span><strong>{fireplace ? "Aktiv" : "Ikke aktiv"}</strong><small>{fireplace ? remaining(controller.fireplace_remaining_seconds) : "15 eller 30 min"}</small></div>
              <div className="fireplace-actions">
                {fireplace ? <button onClick={() => void command("fireplace-stop", { fireplace_minutes: 0 }, "Pejsefunktion stoppet.")}>Stop</button> : <><button onClick={() => void command("fireplace-15", { fireplace_minutes: 15 }, "Pejsefunktion startet i 15 min.")}>15</button><button onClick={() => void command("fireplace-30", { fireplace_minutes: 30 }, "Pejsefunktion startet i 30 min.")}>30</button></>}
              </div>
            </article>
          </div>
        </aside>

        <article className="surface climate-panel">
          <div className="pro-card-head compact"><div><h2>Indeklimadata</h2><p>Aktuelle værdier</p></div></div>
          <div className="climate-metrics">
            <div className="climate-metric green"><Leaf size={21}/><span>CO₂</span><strong>{whole(co2)} <small>ppm</small></strong><em>{co2 === null ? "Ukendt" : co2 < 800 ? "God" : co2 < 1200 ? "Moderat" : "Høj"}</em><i style={{ width: `${co2 === null ? 0 : Math.min(100, Math.max(5, co2 / 16))}%` }}/></div>
            <div className="climate-metric blue"><span className="metric-drop">●</span><span>Luftfugtighed</span><strong>{whole(humidity)} <small>%</small></strong><em>{humidity === null ? "Ukendt" : humidity < 60 ? "Normal" : "Høj"}</em><i style={{ width: `${humidity ?? 0}%` }}/></div>
            <div className="climate-metric cyan"><span className="metric-filter">▧</span><span>Filter</span><strong>{whole(filterLife)} <small>%</small></strong><em>{filterLife === null ? "Ukendt" : filterLife > 40 ? "OK" : filterLife > 15 ? "Snart skift" : "Skift filter"}</em><i style={{ width: `${Math.max(0, Math.min(100, filterLife ?? 0))}%` }}/></div>
            <div className="climate-metric neutral"><span className="metric-heat">≋</span><span>Eftervarme setpunkt</span><strong>{shownAfterheat === "off" ? "OFF" : temp(shownAfterheat)}</strong><em>{afterheatStatus}</em><i style={{ width: `${shownAfterheat === "off" ? 0 : ((shownAfterheat - 10) / 25) * 100}%` }}/></div>
          </div>
        </article>

        <article className="surface afterheat-setpoint-card">
          <div className="afterheat-row">
            <div className="afterheat-copy"><span>Eftervarme setpunkt</span>{afterheatLockout
              // The summer stop replaces the HAC1 details so the card stays compact.
              ? <div className="afterheat-lockout">Spærret af HAC1: udetemperaturen er {temp(outdoor)}. Eftervarmen tænder først, når det er under {whole(afterheatCutoff)}{"\u00a0"}°C ude.</div>
              : <><strong>I HAC1: {actualAfterheatSelection}</strong><small>Varmekald: {afterheatStatus}</small></>}</div>
            <div className="setpoint-stepper">
              <button disabled={shownAfterheat === "off"} onClick={() => stepAfterheat(-1)}>−</button>
              <strong>{shownAfterheat === "off" ? "OFF" : `${whole(shownAfterheat)} °C`}</strong>
              <button disabled={shownAfterheat === 35} onClick={() => stepAfterheat(1)}>+</button>
            </div>
          </div>
          {([["t3_setpoint", "T3 setpunkt"], ["t5_setpoint", "T5 setpunkt"]] as const).map(([key, label]) => {
            const value = Object.hasOwn(thermostatDraft.current, key) ? thermostatDraft.current[key] : number(controller[key]);
            const step = (direction: 1 | -1) => stepThermostat(key, label, value, direction);
            return (
              <div className="afterheat-row" key={key}>
                <div className="afterheat-copy"><span>{label}</span><strong>{value === null ? "OFF" : `${whole(value)} °C`}</strong></div>
                <div className="setpoint-stepper">
                  <button disabled={value === null || busy === key} onClick={() => step(-1)}>−</button>
                  <strong>{value === null ? "OFF" : `${whole(value)} °C`}</strong>
                  <button disabled={value === 35 || busy === key} onClick={() => step(1)}>+</button>
                </div>
              </div>
            );
          })}
          <p className="settings-help">T3- og T5-setpunkter gemmes lokalt. Der findes endnu ingen verificeret Modbus-mapping, så de sendes ikke til enheden.</p>
        </article>
      </div>
      {activeSensor && SENSOR_HISTORY[activeSensor] && <div className="sensor-history-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setActiveSensor(null); }}>
        <section className="sensor-history-dialog surface" role="dialog" aria-modal="true" aria-labelledby="sensor-history-title">
          <div className="sensor-history-heading"><div><span className="eyebrow">SENESTE 24 TIMER</span><h2 id="sensor-history-title">{SENSOR_HISTORY[activeSensor].title}</h2></div><button ref={closeHistoryRef} type="button" aria-label="Luk temperaturgraf" onClick={() => setActiveSensor(null)}><X size={20}/></button></div>
          {historyError ? <p className="sensor-history-message" role="alert">{historyError}</p> : historyLoading ? <div className="history-chart-empty" style={{ height: 230 }}>Henter historik…</div> : <HistoryChart height={230} unit="°C" samples={historySamples} series={[{ key: SENSOR_HISTORY[activeSensor].key, label: SENSOR_HISTORY[activeSensor].title, color: SENSOR_HISTORY[activeSensor].color }]}/>}
        </section>
      </div>}
    </section>
  );
}
