import { useCallback, useEffect, useState } from "react";
import { Activity, Cpu, GitBranch, Radio, Waves } from "lucide-react";
import { InfoList } from "../components/InfoList";
import { requestJson } from "../lib/api";
import "../styles/panels.css";

type Data = Record<string, unknown>;

function text(value: unknown, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}
function number(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
function bool(value: unknown, whenTrue: string, whenFalse: string) {
  return value === true ? whenTrue : value === false ? whenFalse : "—";
}
function seconds(value: unknown, fallback = "—") {
  const parsed = number(value);
  if (parsed === null) return fallback;
  if (parsed < 60) return `${Math.round(parsed)} sek`;
  if (parsed < 3600) return `${Math.round(parsed / 60)} min`;
  return `${(parsed / 3600).toLocaleString("da-DK", { maximumFractionDigits: 1 })} t`;
}
function epoch(value: unknown) {
  const parsed = number(value);
  return parsed === null ? "—" : new Date(parsed * 1000).toLocaleString("da-DK");
}
function masterLabel(value: unknown) {
  if (value === "pi") return "Raspberry Pi";
  if (value === "hcp4") return "HCP4";
  return "Afventer";
}

export function TechniquePage() {
  const [controller, setController] = useState<Data>({});
  const [online, setOnline] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const result = await requestJson<Data>("/api/controller/state", { timeoutMs: 3500 });
      setController(result);
      setOnline(true);
    } catch {
      setOnline(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const master = String(controller.active_master ?? "unknown");
  const busHealthy = controller.rs485_healthy === true;
  const writesAllowed = controller.hardware_writes_allowed === true;

  return (
    <section className="dashboard-overview page-enter">
      <header className="overview-heading-row">
        <div>
          <span className="eyebrow">TEKNIK</span>
          <h1>Controller og bus</h1>
          <p>Masterstatus, hardware writes, sensor freshness, readbacks og beslutningslog.</p>
        </div>
        <div className="overview-status-pills">
          <div><span className="status-led"/><small>Master</small><strong>{masterLabel(master)}</strong></div>
          <div><span className={`status-led ${busHealthy ? "" : "warn"}`}/><small>Bus</small><strong>{busHealthy ? "Sund" : "Afventer"}</strong></div>
          <div><span className={`status-led ${writesAllowed ? "" : "warn"}`}/><small>Skrivning</small><strong>{writesAllowed ? "Tilladt" : "Blokeret"}</strong></div>
        </div>
      </header>

      <div className="panel-grid">
        <article className="surface panel-card">
          <div className="pro-card-head compact"><div><h2>Master-arbitrering</h2><p>Hvem ejer bussen lige nu</p></div><Radio size={20}/></div>
          <InfoList rows={[
            { label: "Aktiv master", value: masterLabel(master) },
            { label: "HCP4 detekteret", value: bool(controller.hcp4_detected, "Ja", "Nej"), tone: controller.hcp4_detected ? "warn" : "ok" },
            { label: "Master siden", value: seconds(controller.master_age_seconds) },
            { label: "Seneste bus-frame", value: seconds(controller.master_bus_frame_age) },
            { label: "Seneste fremmede skrivning", value: seconds(controller.hcp4_last_foreign_write_age) },
            { label: "Fremmede writes (10s / 60s)", value: `${text(controller.hcp4_foreign_writes_10s, "0")} / ${text(controller.hcp4_foreign_writes_60s, "0")}` },
            { label: "Egne writes / echo", value: `${text(controller.own_write_count, "0")} / ${text(controller.own_echo_count, "0")}` },
            { label: "Detektionsårsag", value: text(controller.hcp4_detection_reason) },
          ]}/>
        </article>

        <article className="surface panel-card">
          <div className="pro-card-head compact"><div><h2>Hardware writes</h2><p>Sikkerhedstilstand og seneste fejl</p></div><Cpu size={20}/></div>
          <InfoList rows={[
            { label: "Skrivning tilladt", value: writesAllowed ? "Ja" : "Nej", tone: writesAllowed ? "ok" : "warn" },
            { label: "Kontroltilstand", value: text(controller.hardware_control_state).replaceAll("_", " ") },
            { label: "Seneste write", value: epoch(controller.last_write_at) },
            { label: "Seneste fejl", value: text(controller.last_error, "Ingen"), tone: controller.last_error ? "bad" : "ok" },
            { label: "Fejlede writes", value: text(controller.write_failures, "0"), tone: number(controller.write_failures) ? "warn" : "ok" },
            { label: "Retry-grænse", value: text(controller.retry_limit) },
            { label: "Næste retry", value: controller.next_retry_at ? epoch(controller.next_retry_at) : "Ingen ventende" },
            { label: "Controller oppetid", value: seconds(controller.controller_uptime_seconds) },
          ]}/>
        </article>

        <article className="surface panel-card">
          <div className="pro-card-head compact"><div><h2>Aktiv beslutning</h2><p>Hvorfor det aktuelle niveau er valgt</p></div><GitBranch size={20}/></div>
          <InfoList rows={[
            { label: "Driftstilstand", value: text(controller.mode) },
            { label: "Kilde", value: text(controller.effective_source).replaceAll("_", " ") },
            { label: "Effektivt niveau", value: text(controller.effective_level) },
            { label: "Begrundelse", value: text(controller.effective_reason) },
            { label: "HA online", value: bool(controller.ha_online, "Ja", "Nej"), tone: controller.ha_online ? "ok" : "warn" },
            { label: "HA data alder", value: seconds(controller.ha_age_seconds) },
          ]}/>
        </article>

        <article className="surface panel-card">
          <div className="pro-card-head compact"><div><h2>Smart Auto input</h2><p>Room-data fra Home Assistant</p></div><Waves size={20}/></div>
          <InfoList rows={[
            { label: "Input online", value: bool(controller.smart_inputs_online, "Ja", "Nej"), tone: controller.smart_inputs_online ? "ok" : "warn" },
            { label: "Data alder", value: seconds(controller.smart_inputs_age_seconds) },
            { label: "Demand", value: text(controller.smart_demand) },
            { label: "Ønsket niveau", value: text(controller.smart_requested_level) },
            { label: "Styrende rum", value: text(controller.smart_controlling_room) },
            { label: "Styrende måling", value: text(controller.smart_controlling_metric) },
            { label: "Højeste CO₂", value: controller.smart_max_co2 !== null && controller.smart_max_co2 !== undefined ? `${text(controller.smart_max_co2)} ppm (${text(controller.smart_max_co2_room)})` : "—" },
            { label: "Højeste RH", value: controller.smart_max_rh !== null && controller.smart_max_rh !== undefined ? `${text(controller.smart_max_rh)} % (${text(controller.smart_max_rh_room)})` : "—" },
            { label: "Begrundelse", value: text(controller.smart_reason) },
          ]}/>
        </article>

        <article className="surface panel-card" style={{ gridColumn: "1 / -1" }}>
          <div className="pro-card-head compact"><div><h2>Readbacks</h2><p>Faktisk hardware-status læst fra bussen</p></div><Activity size={20}/></div>
          <div className="panel-grid" style={{ marginTop: 6 }}>
            <InfoList rows={[
              { label: "Tilluft ventilator", value: `${text(controller.actual_fan_supply_rpm)} RPM · ${text(controller.actual_fan_supply_percent)}%` },
              { label: "Fraluft ventilator", value: `${text(controller.actual_fan_extract_rpm)} RPM · ${text(controller.actual_fan_extract_percent)}%` },
              { label: "Bypass faktisk", value: bool(controller.actual_bypass, "Åben", "Lukket") },
              { label: "Bypass ønske", value: text(controller.actual_bypass_request) },
            ]}/>
            <InfoList rows={[
              { label: "Eftervarme aktiv", value: bool(controller.actual_afterheat, "Ja", "Nej") },
              { label: "RS485 eftervarmevalg", value: controller.actual_afterheat_selection === "off" ? "OFF" : controller.actual_afterheat_selection !== null && controller.actual_afterheat_selection !== undefined ? `${text(controller.actual_afterheat_selection)} °C` : "—" },
              { label: "Seneste temperatursetpunkt", value: controller.actual_afterheat_setpoint !== null && controller.actual_afterheat_setpoint !== undefined ? `${text(controller.actual_afterheat_setpoint)} °C` : "—" },
              { label: "Indblæsning kilde", value: text(controller.actual_supply_air_temperature_source) },
              { label: "Frostbeskyttelse", value: controller.actual_afterheat_frost_temperature !== null && controller.actual_afterheat_frost_temperature !== undefined ? `${text(controller.actual_afterheat_frost_temperature)} °C` : "—" },
            ]}/>
          </div>
        </article>
      </div>
      {!online && <div className="control-notice error" style={{ marginTop: 12 }}>Kunne ikke hente controller-status.</div>}
    </section>
  );
}
