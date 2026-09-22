import { useCallback, useEffect, useState } from "react";
import { Activity, Fan, Leaf, Recycle } from "lucide-react";
import { HistoryChart } from "../components/HistoryChart";
import { requestJson } from "../lib/api";
import "../styles/history.css";

type Sample = Record<string, number | null>;
type HistoryResponse = { range: string; samples: Sample[] };

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

  const refresh = useCallback(async (activeRange: string) => {
    try {
      const result = await requestJson<HistoryResponse>(`/history.json?range=${activeRange}`, { timeoutMs: 6000 });
      setSamples(Array.isArray(result.samples) ? result.samples : []);
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
          <div className="pro-card-head compact"><div><h2>Varmegenvinding</h2><p>Beregnet virkningsgrad</p></div><Recycle size={20}/></div>
          {loading ? <div className="history-chart-empty" style={{ height: 200 }}><span>Henter…</span></div> : (
            <HistoryChart
              unit="%"
              samples={samples}
              series={[{ key: "heat_recovery_efficiency", label: "Virkningsgrad", color: "blue" }]}
            />
          )}
        </article>
      </div>
    </section>
  );
}
