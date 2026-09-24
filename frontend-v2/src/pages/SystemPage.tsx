import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Activity, Bluetooth, Cpu, HardDrive, MemoryStick, Network, RefreshCw, Server, Thermometer, Timer, Wifi, WifiOff } from "lucide-react";
import { HistoryChart } from "../components/HistoryChart";
import { requestJson } from "../lib/api";
import "../styles/panels.css";
import "../styles/history.css";
import "../styles/system.css";

type Data = Record<string, unknown>;
type Sample = Record<string, number | null>;
type NetworkItem = { ssid: string; signal: number; security: string; connected: boolean };
type AdminStatus = { power_profile?: string; available_profiles?: string[]; governor?: string; network_manager_available?: boolean; wifi_available?: boolean; wifi_enabled?: boolean; wifi_connection?: string | null; wifi_ipv4?: string | null; bluetooth_available?: boolean; networks?: NetworkItem[] };
const profiles = [
  { key: "powersave", title: "Strømspare", detail: "Lavere CPU-frekvens og forbrug" },
  { key: "balanced", title: "Balanceret", detail: "Tilpasser hastighed efter belastning" },
  { key: "performance", title: "Ydelse", detail: "Holder CPU klar ved høj hastighed" },
];
const number = (value: unknown) => value == null || value === "" || !Number.isFinite(Number(value)) ? null : Number(value);
const text = (value: unknown) => value == null || value === "" ? "—" : String(value);
const percent = (value: unknown) => number(value) == null ? "—" : `${number(value)!.toLocaleString("da-DK", { maximumFractionDigits: 1 })}%`;
const gb = (value: unknown) => number(value) == null ? "—" : `${(number(value)! / 1073741824).toLocaleString("da-DK", { maximumFractionDigits: 1 })} GB`;
const traffic = (value: unknown) => number(value) == null ? "—" : number(value)! >= 1073741824 ? gb(value) : `${(number(value)! / 1048576).toLocaleString("da-DK", { maximumFractionDigits: 1 })} MB`;
const errorText = (error: unknown) => {
  const code = error instanceof Error ? error.message : "";
  if (code.includes("wifi_radio_unavailable")) return "Wi-Fi-radioen er endnu ikke klar. Genstart Pi’en efter firmwareændringen.";
  if (code.includes("invalid_wifi_password")) return "Adgangskoden skal være 8–63 tegn.";
  if (code.includes("wifi_connection_failed")) return "Forbindelsen kunne ikke oprettes. Kontrollér adgangskoden og signalet.";
  if (code.includes("wifi_scan_failed")) return "Wi-Fi-netværk kunne ikke findes lige nu.";
  return "Handlingen kunne ikke gennemføres. Prøv igen.";
};

function Metric({ title, value, detail, amount, tone = "blue", Icon }: { title: string; value: string; detail: string; amount?: number | null; tone?: string; Icon: typeof Cpu }) {
  return <article className={`surface system-metric ${tone}`}><div><span>{title}</span><Icon size={18} /></div><strong>{value}</strong><small>{detail}</small>{amount != null && <i className="system-track"><b style={{ width: `${Math.max(0, Math.min(100, amount))}%` }} /></i>}</article>;
}
function Chart({ title, detail, samples, field, color, unit }: { title: string; detail: string; samples: Sample[]; field: string; color: "blue" | "orange" | "green"; unit: string }) {
  return <article className="surface system-chart"><div className="pro-card-head compact"><div><h2>{title}</h2><p>{detail}</p></div><Activity size={18} /></div><HistoryChart samples={samples} series={[{ key: field, label: title, color }]} unit={unit} height={160} /></article>;
}

export function SystemPage() {
  const [state, setState] = useState<Data>({});
  const [samples, setSamples] = useState<Sample[]>([]);
  const [online, setOnline] = useState(false);
  const [range, setRange] = useState("24h");
  const [csrf, setCsrf] = useState("");
  const [admin, setAdmin] = useState<AdminStatus | null>(null);
  const [networks, setNetworks] = useState<NetworkItem[]>([]);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const passwordRef = useRef<HTMLInputElement>(null);

  const adminAction = useCallback(async <T,>(action: string, target?: unknown, timeoutMs = 5000) => {
    return requestJson<T>("/api/admin/action", { method: "POST", timeoutMs, headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify({ action, target }) });
  }, [csrf]);
  const refresh = useCallback(async (period: string) => {
    const [snapshot, history, auth] = await Promise.allSettled([
      requestJson<Data>("/state.json", { timeoutMs: 5000 }),
      requestJson<{ samples: Sample[] }>(`/history.json?range=${period}`, { timeoutMs: 7000 }),
      requestJson<{ csrf?: string | null }>("/api/auth/status", { timeoutMs: 4000 }),
    ]);
    if (snapshot.status === "fulfilled") { setState(snapshot.value); setOnline(true); }
    else { setState({}); setOnline(false); }
    setSamples(history.status === "fulfilled" && Array.isArray(history.value.samples) ? history.value.samples : []);
    if (auth.status === "fulfilled") setCsrf(auth.value.csrf ?? "");
  }, []);
  useEffect(() => { void refresh(range); const timer = window.setInterval(() => void refresh(range), 30000); return () => window.clearInterval(timer); }, [range, refresh]);
  useEffect(() => {
    if (!csrf) return;
    let cancelled = false;
    const load = async () => { try { const result = await adminAction<AdminStatus>("get_system_status"); if (!cancelled) setAdmin(result); } catch { if (!cancelled) setAdmin(null); } };
    void load(); const timer = window.setInterval(() => void load(), 30000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [csrf, adminAction]);
  const changeProfile = async (profile: string) => {
    setBusy("profile"); setNotice("");
    try { await adminAction("power_profile", profile); setAdmin(await adminAction<AdminStatus>("get_system_status")); setNotice("Power-profilen er gemt."); }
    catch (error) { setNotice(errorText(error)); }
    finally { setBusy(""); }
  };
  const scan = async () => {
    setBusy("scan"); setNotice("");
    try { const result = await adminAction<AdminStatus>("wifi_scan", undefined, 30000); setNetworks(result.networks ?? []); if (!result.networks?.length) setNotice("Ingen netværk fundet. Kontrollér Wi-Fi-radioen og prøv igen."); }
    catch (error) { setNotice(errorText(error)); }
    finally { setBusy(""); }
  };
  const enableWifi = async () => {
    setBusy("wifi"); setNotice("");
    try { setAdmin(await adminAction<AdminStatus>("wifi_enable")); setNotice("Wi-Fi-radioen er slået til."); }
    catch (error) { setNotice(errorText(error)); }
    finally { setBusy(""); }
  };
  const connectWifi = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const password = passwordRef.current?.value ?? "";
    if (!selected || password.length < 8) { setNotice("Vælg et netværk og angiv en adgangskode på mindst 8 tegn."); return; }
    setBusy("connect"); setNotice("");
    try { setAdmin(await adminAction<AdminStatus>("wifi_connect", { ssid: selected, password }, 45000)); setNotice("Wi-Fi er forbundet."); setNetworks([]); }
    catch (error) { setNotice(errorText(error)); }
    finally { if (passwordRef.current) passwordRef.current.value = ""; setBusy(""); }
  };

  const temp = number(state.pi_cpu_temperature ?? state.system_cpu_temperature);
  const uptime = number(state.system_uptime_seconds ?? state.pi_uptime_seconds);
  const serviceTone = (value: unknown) => value === "active" ? "ok" : value === "failed" ? "bad" : value === "inactive" ? "stopped" : "unknown";
  const services = [["Controller / gateway", state.service_gateway_activestate], ["WebUI", online ? "active" : "unknown"], ["Admin / update", state.service_admin_activestate], ["1-Wire", state.service_onewire_activestate], ["SSH", state.service_ssh_activestate]];
  return <section className="dashboard-overview page-enter system-page">
    <header className="overview-heading-row"><div><span className="eyebrow">SYSTEM · RASPBERRY PI</span><h1>System</h1><p>Ressourcer, netværk og drift på Pi’en.</p></div><span className={`system-online ${online ? "ok" : "unknown"}`}>● {online ? "Pi online" : "Data utilgængelige"}</span></header>
    <div className="system-metrics">
      <Metric title="CPU" value={percent(state.system_cpu_usage_percent)} detail={`${text(state.system_cpu_frequency_mhz)} MHz · ${text(state.system_cpu_count)} kerner`} amount={number(state.system_cpu_usage_percent)} Icon={Cpu} />
      <Metric title="CPU-temperatur" value={temp == null ? "—" : `${temp.toLocaleString("da-DK")}°C`} detail={temp == null ? "Ingen måling" : temp >= 80 ? "Kritisk temperatur" : temp >= 70 ? "Høj temperatur" : "Normal temperatur"} amount={temp} tone={temp != null && temp >= 80 ? "red" : temp != null && temp >= 70 ? "orange" : "green"} Icon={Thermometer} />
      <Metric title="RAM" value={percent(state.system_memory_used_percent)} detail={`${gb(state.system_memory_used_bytes)} / ${gb(state.system_memory_total_bytes)}`} amount={number(state.system_memory_used_percent)} Icon={MemoryStick} />
      <Metric title="Disk · /" value={percent(state.system_root_used_percent)} detail={`${text(state.system_root_used_gb)} GB brugt · ${text(state.system_root_free_gb)} GB ledig`} amount={number(state.system_root_used_percent)} tone={(number(state.system_root_used_percent) ?? 0) >= 85 ? "orange" : "blue"} Icon={HardDrive} />
      <Metric title="Uptime" value={uptime == null ? "—" : `${Math.floor(uptime / 86400)}d ${Math.floor(uptime % 86400 / 3600)}t ${Math.floor(uptime % 3600 / 60)}m`} detail={`Boot ${text(state.system_boot_time)}`} Icon={Timer} />
    </div>
    <div className="system-heading"><div><span className="eyebrow">PI · INDSTILLINGER</span><h2>Strøm og trådløst netværk</h2></div></div>
    <div className="system-controls">
      <article className="surface system-panel system-power"><div className="pro-card-head compact"><div><h2>Power-profil</h2><p>CPU-governor: {text(admin?.governor)}</p></div><Cpu size={19} /></div><div className="system-profiles">{profiles.map(profile => <button key={profile.key} type="button" className={admin?.power_profile === profile.key ? "selected" : ""} disabled={!csrf || !!busy || !admin?.available_profiles?.includes(profile.key)} onClick={() => void changeProfile(profile.key)}><strong>{profile.title}</strong><small>{profile.detail}</small></button>)}</div><p className="system-footnote">Gælder med det samme og gemmes til næste genstart.</p></article>
      <article className="surface system-panel system-wifi"><div className="pro-card-head compact"><div><h2>Wi-Fi</h2><p>{admin?.wifi_connection ? `Forbundet: ${admin.wifi_connection}` : admin?.wifi_available ? "Klar til opsætning" : admin?.network_manager_available === false ? "NetworkManager er ikke installeret" : "Radio ikke tilgængelig før genstart"}</p></div>{admin?.wifi_available ? <Wifi size={19} /> : <WifiOff size={19} />}</div><div className="system-radio-status"><span><Wifi size={15} /> Wi-Fi: {admin?.wifi_enabled ? "Til" : admin?.wifi_available ? "Slået fra" : "Mangler"}</span><span><Bluetooth size={15} /> Bluetooth: {admin?.bluetooth_available ? "Tilgængelig" : "Mangler"}</span></div>{admin?.wifi_ipv4 && <p className="system-wifi-ip">Wi-Fi IP: {admin.wifi_ipv4}</p>}
        <div className="system-wifi-actions">{admin?.wifi_available && !admin.wifi_enabled && <button className="secondary-action" disabled={!!busy || !csrf} onClick={() => void enableWifi()}>Slå Wi-Fi til</button>}<button className="secondary-action" disabled={!admin?.wifi_available || !admin.wifi_enabled || !!busy || !csrf} onClick={() => void scan()}><RefreshCw size={14} />{busy === "scan" ? "Søger…" : "Find netværk"}</button></div>
        {networks.length > 0 && <div className="system-networks" role="listbox" aria-label="Wi-Fi-netværk">{networks.map(network => <button key={network.ssid} type="button" className={selected === network.ssid ? "selected" : ""} onClick={() => { setSelected(network.ssid); if (passwordRef.current) passwordRef.current.value = ""; }}><strong>{network.ssid}</strong><span>{network.signal}% · {network.security || "Åbent"}{network.connected ? " · Forbundet" : ""}</span></button>)}</div>}
        <form className="system-wifi-form" onSubmit={event => void connectWifi(event)}><label>Netværksnavn<input type="text" value={selected} maxLength={32} onChange={event => setSelected(event.target.value)} placeholder="Vælg ovenfor eller skriv SSID" disabled={!admin?.wifi_available || !!busy} /></label><label>Adgangskode<input ref={passwordRef} type="password" autoComplete="new-password" minLength={8} maxLength={63} placeholder="Wi-Fi-adgangskode" disabled={!admin?.wifi_available || !!busy} /></label><button className="primary-action" type="submit" disabled={!csrf || !admin?.wifi_available || !admin.wifi_enabled || !!busy || !selected}>{busy === "connect" ? "Forbinder…" : "Forbind Wi-Fi"}</button></form>
        <p className="system-footnote">Hvis Ethernet er tilsluttet, har det højere prioritet. Wi-Fi kan bruges som selvstændig forbindelse på en Pi med SD-kort.</p>
      </article>
    </div>
    {notice && <p className="system-notice" role="status">{notice}</p>}
    <div className="system-heading system-history-heading"><div><span className="eyebrow">RESSOURCER</span><h2>Udvikling over tid</h2></div><div className="pro-segment system-range">{[["1h", "1 time"], ["6h", "6 timer"], ["24h", "24 timer"]].map(([value, label]) => <button key={value} type="button" className={range === value ? "active" : ""} onClick={() => setRange(value)}>{label}</button>)}</div></div>
    <div className="system-charts"><Chart title="CPU-forbrug" detail="Belastning i procent" samples={samples} field="system_cpu_usage_percent" color="blue" unit="%" /><Chart title="CPU-temperatur" detail="Advarsel ved 70°C" samples={samples} field="pi_cpu_temperature" color="orange" unit="°C" /><Chart title="RAM-forbrug" detail="Brugt fysisk hukommelse" samples={samples} field="system_memory_used_percent" color="green" unit="%" /></div>
    <div className="system-lower"><article className="surface system-panel"><div className="pro-card-head compact"><div><h2>Services</h2><p>Aktuel status på Pi’en</p></div><Server size={19} /></div><div className="system-services">{services.map(([name, value]) => <div key={String(name)}><i className={serviceTone(value)} /><strong>{text(name)}</strong><span className={serviceTone(value)}>{value === "active" ? "OK" : value === "failed" ? "Fejl" : value === "inactive" ? "Stoppet" : "Ukendt"}</span></div>)}</div></article>
      <article className="surface system-panel"><div className="pro-card-head compact"><div><h2>Netværk</h2><p>Aktiv forbindelse og trafik</p></div><Network size={19} /></div><div className="system-network"><strong>{text(state.network_interface)}</strong><span>{text(state.network_ipv4)}</span></div><div className="system-pairs">{[["Modtaget", traffic(state.network_rx_bytes)], ["Sendt", traffic(state.network_tx_bytes)], ["Gateway", state.network_gateway], ["Link", number(state.network_link_speed_mbps) == null ? "—" : `${state.network_link_speed_mbps} Mbps`]].map(([key, value]) => <div key={String(key)}><span>{text(key)}</span><strong>{text(value)}</strong></div>)}</div></article>
      <article className="surface system-panel"><div className="pro-card-head compact"><div><h2>Systeminformation</h2><p>Hardware og software</p></div><Cpu size={19} /></div><div className="system-pairs">{[["Model", state.pi_model ?? state.system_model], ["Boot", state.system_boot_mode], ["Hostname", state.system_hostname], ["OS", state.system_os], ["Kernel", state.system_kernel], ["Arkitektur", state.system_architecture], ["Python", state.system_python_version], ["HCH5 Control", state.system_hch5_version], ["Load 1 / 5 / 15", `${text(state.system_load_1m)} / ${text(state.system_load_5m)} / ${text(state.system_load_15m)}`]].map(([key, value]) => <div key={String(key)}><span>{text(key)}</span><strong>{text(value)}</strong></div>)}</div></article></div>
  </section>;
}
