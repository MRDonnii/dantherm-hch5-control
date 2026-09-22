import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, Flame, Gauge, Leaf, RefreshCw, Snowflake, Wind } from "lucide-react";
import { Link } from "react-router-dom";
import { Hch5UnitDiagram } from "../components/Hch5UnitDiagram";
import { postJson, requestJson } from "../lib/api";
import "../styles/overview.css";

type Data = Record<string, unknown>;
type AuthState = { csrf?: string | null };
type UpdateInfo = {
  channel?: "stable" | "beta";
  current_version?: string;
  available_version?: string;
  update_available?: boolean;
  update?: { running?: boolean; progress?: number; phase?: string; detail?: string; last_error?: string | null };
};

function number(value: unknown): number | null {
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
  return value === null ? "—" : `${value.toLocaleString("da-DK", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} °C`;
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
  const [notice, setNotice] = useState("");
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);

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
    if (!csrf) return;
    let stopped = false;
    const check = async () => {
      try {
        const result = await postJson<UpdateInfo>("/api/admin/action", { action: "check_update", target: "beta" }, csrf);
        if (!stopped) setUpdateInfo(result);
      } catch {
        // Update status is secondary to ventilation control.
      }
    };
    void check();
    const timer = window.setInterval(() => void check(), updateInfo?.update?.running ? 2500 : 60000);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [csrf, updateInfo?.update?.running]);

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
  const bypassActualLabel = bypassMoving ? "bevæger sig" : bypassActual ? "åben" : "lukket";
  const bypassRequest = String(controller.actual_bypass_request ?? unit.bypass_request ?? controller.bypass ?? "off");
  const heating = controller.actual_afterheat === true || unit.afterheat_active === true;
  const fireplace = controller.actual_fireplace === true || unit.fireplace === true;
  const mode = String(controller.mode ?? "local_auto");
  const level = number(controller.effective_level) ?? 3;
  const afterheatSetpoint = number(controller.afterheat_setpoint) ?? 20;
  const busHealthy = controller.rs485_healthy === true || unit.bus_traffic === true || unit.available === true;
  const quickBoostActive = (number(controller.quick_boost_remaining_seconds) ?? 0) > 0;
  const updateProgress = Math.max(0, Math.min(100, number(updateInfo?.update?.progress) ?? (updateInfo?.update?.running ? 8 : 0)));

  const recovery = useMemo(() => {
    if (bypassActual || outdoor === null || extract === null || exhaust === null || Math.abs(extract - outdoor) < .5) return null;
    const value = ((extract - exhaust) / (extract - outdoor)) * 100;
    return value >= 0 && value <= 105 ? Math.round(value) : null;
  }, [bypassActual, outdoor, extract, exhaust]);

  const levelPatch = mode === "manual" ? "manual_level" : "local_normal_level";
  const setAfterheat = (next: number) => void command("afterheat", { afterheat_setpoint: Math.max(18, Math.min(30, next)) }, "Eftervarmens ønskede indblæsningstemperatur er gemt.");

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
            outdoor={outdoor} extract={extract} exhaust={exhaust} beforeHeater={beforeHeater} afterHeater={afterHeater}
            room={room} frost={frost} flowWater={flowWater} returnWater={returnWater}
            supplyRpm={supplyRpm} extractRpm={extractRpm} supplyPercent={supplyPercent} extractPercent={extractPercent}
            bypassActual={bypassActual} bypassRequest={bypassRequest} heating={heating} recovery={recovery}
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

          <article className="surface afterheat-setpoint-card">
            <div className="afterheat-copy"><span>Eftervarme setpunkt</span><strong>Ønsket indblæsningstemperatur</strong><small>Styrer kun temperatur-setpunkt. HAC1 regulerer selv varmefladen og frostsikringen.</small></div>
            <div className="setpoint-stepper">
              <button disabled={busy !== null || afterheatSetpoint <= 18} onClick={() => setAfterheat(afterheatSetpoint - 1)}>−</button>
              <strong>{whole(afterheatSetpoint)} °C</strong>
              <button disabled={busy !== null || afterheatSetpoint >= 30} onClick={() => setAfterheat(afterheatSetpoint + 1)}>+</button>
            </div>
          </article>
          {notice && <div className={`control-notice${notice.startsWith("Kunne") ? " error" : ""}`}>{notice}</div>}
        </aside>
      </div>

      <div className="dashboard-bottom-grid">
        <article className="surface climate-panel">
          <div className="pro-card-head compact"><div><h2>Indeklimadata</h2><p>Aktuelle værdier</p></div></div>
          <div className="climate-metrics">
            <div className="climate-metric green"><Leaf size={21}/><span>CO₂</span><strong>{whole(co2)} <small>ppm</small></strong><em>{co2 === null ? "Ukendt" : co2 < 800 ? "God" : co2 < 1200 ? "Moderat" : "Høj"}</em><i style={{ width: `${co2 === null ? 0 : Math.min(100, Math.max(5, co2 / 16))}%` }}/></div>
            <div className="climate-metric blue"><span className="metric-drop">●</span><span>Luftfugtighed</span><strong>{whole(humidity)} <small>%</small></strong><em>{humidity === null ? "Ukendt" : humidity < 60 ? "Normal" : "Høj"}</em><i style={{ width: `${humidity ?? 0}%` }}/></div>
            <div className="climate-metric cyan"><span className="metric-filter">▧</span><span>Filter</span><strong>{whole(filterLife)} <small>%</small></strong><em>{filterLife === null ? "Ukendt" : filterLife > 40 ? "OK" : filterLife > 15 ? "Snart skift" : "Skift filter"}</em><i style={{ width: `${Math.max(0, Math.min(100, filterLife ?? 0))}%` }}/></div>
            <div className="climate-metric neutral"><span className="metric-heat">≋</span><span>Eftervarme setpunkt</span><strong>{temp(afterheatSetpoint)}</strong><em>{heating ? "Varmeflade aktiv" : "Automatik standby"}</em><i style={{ width: `${((afterheatSetpoint - 18) / 12) * 100}%` }}/></div>
          </div>
        </article>

        <article className="surface update-overview-card">
          <div className="pro-card-head compact"><div><h2>Softwareopdatering</h2><p>Failsafe Beta-kanal</p></div><RefreshCw size={20}/></div>
          <div className="update-summary-line"><span className="channel-badge">{updateInfo?.channel === "stable" ? "Stable" : "Beta"}</span><span>Version</span><strong>{updateInfo?.current_version ?? "—"}</strong></div>
          {updateInfo?.update?.running ? (
            <>
              <div className="update-progress-copy"><strong>{updateInfo.update.detail ?? "Installerer opdatering…"}</strong><span>{Math.round(updateProgress)}%</span></div>
              <div className="update-progress-track"><i style={{ width: `${updateProgress}%` }}/></div>
              <small>{updateInfo.update.phase ?? "working"} · anlægget fortsætter driften under validering.</small>
            </>
          ) : (
            <>
              <div className="update-progress-copy"><strong>{updateInfo?.update_available ? `${updateInfo.available_version ?? "Ny build"} er klar` : "Systemet er opdateret"}</strong><span>{updateInfo?.update_available ? "Ny" : "OK"}</span></div>
              <div className="update-progress-track idle"><i style={{ width: updateInfo?.update_available ? "18%" : "100%" }}/></div>
              <small>{updateInfo?.update?.last_error ? `Seneste fejl: ${updateInfo.update.last_error}` : "Opdateringer valideres før genstart og rulles tilbage ved fejl."}</small>
            </>
          )}
          <Link className="update-link" to="/updates">Åbn opdateringer <ArrowRight size={15}/></Link>
        </article>
      </div>
    </section>
  );
}
