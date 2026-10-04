import { useCallback, useEffect, useState } from "react";
import { Activity, Fan, Leaf, Recycle, SlidersHorizontal } from "lucide-react";
import { AlarmHistory } from "../components/AlarmHistory";
import { HistoryChart } from "../components/HistoryChart";
import { requestJson } from "../lib/api";
import "../styles/history.css";

type Sample = Record<string, number | null>;
type HistoryResponse = { range: string; samples: Sample[] };
type ChangeEvent = { timestamp: number; source: string; changes: Record<string, [unknown, unknown]> };

// Readable names for the settings that are changed most often.
const SETTING_LABELS: Record<string, string> = {
  afterheat_setpoint: "Eftervarme setpunkt",
  afterheat_enabled: "Eftervarme tændt",
  mode: "Driftstilstand",
  manual_level: "Manuelt trin",
  local_normal_level: "Normaltrin",
  bypass: "Bypass",
  standby_minutes: "Sluk anlæg (min)",
  bonfire_minutes: "Bål i haven (min)",
  fireplace_minutes: "Pejsefunktion (min)",
  schedule_enabled: "Ugeplan tændt",
  schedule_periods: "Ugeplan",
  vacation_enabled: "Ferie",
  vacation_level: "Trin under ferie",
  vacation_from: "Ferie fra",
  vacation_until: "Ferie til",
};
function sourceLabel(source: string) {
  if (source === "home_assistant") return "Home Assistant";
  if (source.startsWith("webui:")) return `WebUI · ${source.slice(6)}`;
  return source === "api" ? "API" : source;
}
function valueLabel(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (value === true) return "til";
  if (value === false) return "fra";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function changeValue(key: string, value: unknown) {
  if ((key === "vacation_from" || key === "vacation_until") && value && Number.isFinite(Number(value))) {
    return new Date(Number(value) * 1000).toLocaleString("da-DK", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  }
  return valueLabel(value);
}

const RANGES: { value: string; label: string }[] = [
  { value: "1h", label: "1 time" },
  { value: "6h", label: "6 timer" },
  { value: "24h", label: "24 timer" },
  { value: "7d", label: "7 dage" },
  { value: "30d", label: "30 dage" },
];

export function HistoryPage() {
  const [range, setRange] = useState("24h");
  const [samples, setSamples] = useState<Sample[]>([]);
  const [online, setOnline] = useState(false);
  const [loading, setLoading] = useState(true);
  const [changes, setChanges] = useState<ChangeEvent[]>([]);

  const refresh = useCallback(async (activeRange: string) => {
    try {
      const result = await requestJson<HistoryResponse>(`/history.json?range=${activeRange}`, { timeoutMs: 6000 });
      setSamples(Array.isArray(result.samples) ? result.samples : []);
      const state = await requestJson<{ change_log?: ChangeEvent[] }>("/api/controller/state", { timeoutMs: 3500 }).catch(() => null);
      if (state && Array.isArray(state.change_log)) setChanges(state.change_log);
      setOnline(true);
    } catch {
      setOnline(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    void refresh(range);
    const timer = window.setInterval(() => void refresh(range), 60000);
    return () => window.clearInterval(timer);
  }, [range, refresh]);

  return (
    <section className="dashboard-overview page-enter">
      <header className="overview-heading-row">
        <div>
          <span className="eyebrow">HISTORIK</span>
          <h1>Udvikling over tid</h1>
          <p>Temperaturer, luftkvalitet, ventilatorer og varmegenvinding samlet i en fejltolerant historikvisning.</p>
        </div>
        <div className="overview-status-pills">
          <div><span className={`status-led ${online ? "" : "warn"}`}/><small>Historik</small><strong>{online ? "Live" : "Afventer"}</strong></div>
        </div>
      </header>

      <div className="pro-segment history-range-segment">
        {RANGES.map(item => (
          <button key={item.value} className={range === item.value ? "active" : ""} onClick={() => setRange(item.value)}>{item.label}</button>
        ))}
      </div>

      <div className="history-grid">
        <article className="surface history-card">
          <div className="pro-card-head compact"><div><h2>Temperaturer</h2><p>Ude-, udsugnings-, afkast- og indblæsningstemperatur</p></div><Activity size={20}/></div>
          {loading ? <div className="history-chart-empty" style={{ height: 200 }}><span>Henter…</span></div> : (
            <HistoryChart
              unit="°C"
              samples={samples}
              series={[
                { key: "outdoor_temp", label: "Udeluft", color: "blue" },
                { key: "extract_temp", label: "Udsugning", color: "orange" },
                { key: "exhaust_temp", label: "Afkast", color: "red" },
                { key: "supply_temp", label: "Tilluft", color: "green" },
              ]}
            />
          )}
        </article>

        <article className="surface history-card">
          <div className="pro-card-head compact"><div><h2>Eftervarmevand</h2><p>Fremløb og retur til varmefladen</p></div><Activity size={20}/></div>
          {loading ? <div className="history-chart-empty" style={{ height: 200 }}><span>Henter…</span></div> : (
            <HistoryChart
              unit="°C"
              samples={samples}
              series={[
                { key: "flow_temperature", label: "Fremløb", color: "orange" },
                { key: "return_temperature", label: "Retur", color: "blue" },
              ]}
            />
          )}
        </article>

        <article className="surface history-card">
          <div className="pro-card-head compact"><div><h2>Ventilatorer</h2><p>Omdrejninger for tilluft og fraluft</p></div><Fan size={20}/></div>
          {loading ? <div className="history-chart-empty" style={{ height: 200 }}><span>Henter…</span></div> : (
            <HistoryChart
              unit=" RPM"
              samples={samples}
              series={[
                { key: "fan_supply_rpm", label: "Tilluft", color: "green" },
                { key: "fan_extract_rpm", label: "Fraluft", color: "orange" },
              ]}
            />
          )}
        </article>

        <article className="surface history-card">
          <div className="pro-card-head compact"><div><h2>Luftkvalitet</h2><p>CO₂-niveau</p></div><Leaf size={20}/></div>
          {loading ? <div className="history-chart-empty" style={{ height: 200 }}><span>Henter…</span></div> : (
            <HistoryChart
              unit=" ppm"
              samples={samples}
              series={[{ key: "co2", label: "CO₂", color: "green" }]}
            />
          )}
        </article>

        <article className="surface history-card">
          <div className="pro-card-head compact"><div><h2>Genvinding · udsugningsside</h2><p>Beregnet fra T1, T3 og T4</p></div><Recycle size={20}/></div>
          {loading ? <div className="history-chart-empty" style={{ height: 200 }}><span>Henter…</span></div> : (
            <HistoryChart
              unit="%"
              samples={samples}
              series={[{ key: "heat_recovery_efficiency", label: "Udsugningsside", color: "blue" }]}
            />
          )}
        </article>

        <AlarmHistory/>

        <article className="surface history-card change-log-card">
          <div className="pro-card-head compact"><div><h2>Ændringer af indstillinger</h2><p>Hvem ændrede hvad · seneste 50</p></div><SlidersHorizontal size={20}/></div>
          {changes.length === 0 ? <div className="history-chart-empty" style={{ height: 80 }}><span>Ingen ændringer logget endnu</span></div> : (
            <ul className="change-log">
              {changes.map(event => Object.entries(event.changes).map(([key, [from, to]]) => (
                <li key={`${event.timestamp}-${key}`}>
                  <time>{new Date(event.timestamp * 1000).toLocaleString("da-DK", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</time>
                  <strong>{SETTING_LABELS[key] ?? key}</strong>
                  <span>{key === "schedule_periods" ? "perioder ændret" : `${changeValue(key, from)} → ${changeValue(key, to)}`}</span>
                  <em>{sourceLabel(event.source)}</em>
                </li>
              )))}
            </ul>
          )}
        </article>
      </div>
    </section>
  );
}
