import { useCallback, useEffect, useState } from "react";
import { Cable, HardDrive, Network, Server } from "lucide-react";
import { InfoList } from "../components/InfoList";
import { postJson, requestJson } from "../lib/api";
import "../styles/panels.css";

type Data = Record<string, unknown>;
type AuthState = { csrf?: string | null };
type UpdateInfo = { channel?: string; current_version?: string; available_version?: string; update_available?: boolean };

function text(value: unknown, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}
function number(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
function percent(value: unknown) {
  const parsed = number(value);
  return parsed === null ? "—" : `${parsed.toLocaleString("da-DK", { maximumFractionDigits: 1 })}%`;
}
function bytesToMb(value: unknown) {
  const parsed = number(value);
  return parsed === null ? "—" : `${Math.round(parsed / 1024 / 1024)} MB`;
}
function serviceTone(state: unknown) {
  return state === "active" ? "ok" : state === undefined || state === null ? "neutral" : "bad";
}

export function SystemPage() {
  const [state, setState] = useState<Data>({});
  const [online, setOnline] = useState(false);
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [csrf, setCsrf] = useState("");

  const refresh = useCallback(async () => {
    try {
      const result = await requestJson<Data>("/state.json", { timeoutMs: 4000 });
      setState(result);
      setOnline(true);
    } catch {
      setOnline(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    void requestJson<AuthState>("/api/auth/status", { timeoutMs: 3500 }).then(result => setCsrf(result.csrf ?? "")).catch(() => {});
  }, []);

  useEffect(() => {
    if (!csrf) return;
    let stopped = false;
    const check = async () => {
      try {
        const result = await postJson<UpdateInfo>("/api/admin/action", { action: "check_update" }, csrf);
        if (!stopped) setUpdateInfo(result);
      } catch {
        // Versionsstatus er sekundær information her.
      }
    };
    void check();
    const timer = window.setInterval(() => void check(), 300000);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [csrf]);

  return (
    <section className="dashboard-overview page-enter">
      <header className="overview-heading-row">
        <div>
          <span className="eyebrow">SYSTEM</span>
          <h1>Raspberry Pi og gateway</h1>
          <p>Drift, services, netværk, ressourcer og versionsstatus.</p>
        </div>
        <div className="overview-status-pills">
          <div><span className={`status-led ${online ? "" : "warn"}`}/><small>System</small><strong>{online ? "Live" : "Afventer"}</strong></div>
          <div><span className="status-led"/><small>Version</small><strong>{text(updateInfo?.current_version)}</strong></div>
        </div>
      </header>

      <div className="panel-grid">
        <article className="surface panel-card">
          <div className="pro-card-head compact"><div><h2>Raspberry Pi</h2><p>Vært, CPU og hukommelse</p></div><Server size={20}/></div>
          <InfoList rows={[
            { label: "Hostname", value: text(state.system_hostname) },
            { label: "OS", value: text(state.system_os) },
            { label: "Arkitektur", value: text(state.system_architecture) },
            { label: "Systemtid", value: text(state.system_time) },
            { label: "CPU-frekvens", value: state.system_cpu_frequency_mhz ? `${text(state.system_cpu_frequency_mhz)} MHz` : "—" },
            { label: "CPU-forbrug", value: percent(state.system_cpu_usage_percent), tone: (number(state.system_cpu_usage_percent) ?? 0) > 85 ? "warn" : "ok" },
            { label: "Swap i brug", value: percent(state.system_swap_used_percent) },
          ]}/>
        </article>

        <article className="surface panel-card">
          <div className="pro-card-head compact"><div><h2>Disk</h2><p>Rodpartition</p></div><HardDrive size={20}/></div>
          <InfoList rows={[
            { label: "Størrelse", value: state.system_root_total_gb ? `${text(state.system_root_total_gb)} GB` : "—" },
            { label: "Brugt", value: percent(state.system_root_used_percent), tone: (number(state.system_root_used_percent) ?? 0) > 85 ? "warn" : "ok" },
            { label: "Kilde", value: text(state.system_root_source) },
            { label: "Filsystem", value: text(state.system_rootfs_type) },
            { label: "Skrivebeskyttet", value: state.system_root_read_only === true ? "Ja" : state.system_root_read_only === false ? "Nej" : "—" },
          ]}/>
        </article>

        <article className="surface panel-card">
          <div className="pro-card-head compact"><div><h2>Netværk</h2><p>Aktiv rute og interface</p></div><Network size={20}/></div>
          <InfoList rows={[
            { label: "Interface", value: text(state.network_interface) },
            { label: "Status", value: text(state.network_link_status), tone: state.network_link_status === "up" ? "ok" : "warn" },
            { label: "IPv4", value: state.network_ipv4 ? `${text(state.network_ipv4)}/${text(state.network_prefix)}` : "—" },
            { label: "Gateway", value: text(state.network_gateway) },
            { label: "DNS", value: text(state.network_dns) },
            { label: "MAC", value: text(state.network_mac) },
            { label: "Linkhastighed", value: state.network_link_speed_mbps ? `${text(state.network_link_speed_mbps)} Mbps` : "—" },
            { label: "Netværksstack", value: text(state.network_stack) },
            { label: "RX/TX fejl", value: `${text(state.network_rx_errors, "0")} / ${text(state.network_tx_errors, "0")}` },
          ]}/>
        </article>

        <article className="surface panel-card">
          <div className="pro-card-head compact"><div><h2>Services</h2><p>Gateway, 1-Wire og SSH</p></div><Cable size={20}/></div>
          <InfoList rows={[
            { label: "Gateway", value: text(state.service_gateway_activestate), tone: serviceTone(state.service_gateway_activestate) },
            { label: "Gateway genstarter", value: text(state.service_gateway_nrestarts, "0") },
            { label: "Gateway hukommelse", value: bytesToMb(state.service_gateway_memorycurrent) },
            { label: "1-Wire", value: text(state.service_onewire_activestate), tone: serviceTone(state.service_onewire_activestate) },
            { label: "SSH", value: text(state.service_ssh_activestate), tone: serviceTone(state.service_ssh_activestate) },
            { label: "SSH-port lytter", value: state.diagnostic_ssh_port_listening === true ? "Ja" : "Nej" },
            { label: "Fejlede enheder", value: text(state.diagnostic_failed_units, "Ingen"), tone: state.diagnostic_failed_units && state.diagnostic_failed_units !== "Ingen" ? "bad" : "ok" },
          ]}/>
        </article>

        <article className="surface panel-card">
          <div className="pro-card-head compact"><div><h2>Versionsstatus</h2><p>Installeret build og opdateringskanal</p></div><Server size={20}/></div>
          <InfoList rows={[
            { label: "Kanal", value: updateInfo?.channel === "stable" ? "Stable" : "Beta" },
            { label: "Nuværende version", value: text(updateInfo?.current_version) },
            { label: "Tilgængelig version", value: text(updateInfo?.available_version) },
            { label: "Opdatering klar", value: updateInfo?.update_available ? "Ja" : "Nej", tone: updateInfo?.update_available ? "warn" : "ok" },
          ]}/>
        </article>
      </div>
    </section>
  );
}
