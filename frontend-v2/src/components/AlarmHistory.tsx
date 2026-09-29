import { useCallback, useEffect, useState } from "react";
import { BellRing, CheckCircle2, KeyRound, ShieldAlert, TriangleAlert, UserCog } from "lucide-react";
import { requestJson } from "../lib/api";

export interface EventRow {
  time: number;
  kind: string;
  text: string;
  code?: string;
  severity?: "info" | "warning" | "critical";
  since?: number;
  duration?: number;
  user?: string;
  by?: string;
  ip?: string;
}
type Filter = "all" | "alarms" | "security";

const SEVERITY: Record<string, string> = { critical: "Kritisk", warning: "Advarsel", info: "Info" };

export function duration(seconds?: number | null): string {
  if (seconds === null || seconds === undefined) return "";
  if (seconds < 90) return `${Math.max(1, Math.round(seconds))} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} min`;
  const hours = Math.round(minutes / 6) / 10;
  if (hours < 48) return `${hours.toLocaleString("da-DK")} t`;
  return `${Math.round(hours / 24)} dage`;
}

function when(epoch: number) {
  return new Date(epoch * 1000).toLocaleString("da-DK", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function kindInfo(event: EventRow): { icon: typeof BellRing; label: string; tone: string } {
  switch (event.kind) {
    case "alarm_raised": return { icon: TriangleAlert, label: SEVERITY[event.severity ?? "info"] ?? "Alarm", tone: event.severity ?? "info" };
    case "alarm_cleared": return { icon: CheckCircle2, label: "Løst", tone: "ok" };
    case "login": return { icon: KeyRound, label: "Login", tone: "neutral" };
    case "login_failed": return { icon: ShieldAlert, label: "Fejlet login", tone: "warning" };
    case "password_reset": return { icon: KeyRound, label: "Nulstilling", tone: "neutral" };
    case "token_generated": return { icon: KeyRound, label: "API-nøgle", tone: "warning" };
    default: return { icon: UserCog, label: "Bruger", tone: "neutral" };
  }
}

export function AlarmHistory() {
  const [events, setEvents] = useState<EventRow[]>([]);
  const [active, setActive] = useState<EventRow[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const result = await requestJson<{ events: EventRow[]; active: EventRow[] }>("/api/events?limit=300", { timeoutMs: 5000 });
      setEvents(result.events ?? []); setActive(result.active ?? []); setError("");
    } catch { setError("Alarmhistorikken kunne ikke hentes."); }
  }, []);
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 60000); return () => window.clearInterval(timer); }, [load]);

  const hasSecurity = events.some(e => !e.kind.startsWith("alarm"));
  const shown = events.filter(e => filter === "all" || (filter === "alarms" ? e.kind.startsWith("alarm") : !e.kind.startsWith("alarm")));
  const now = Date.now() / 1000;

  return <article className="surface history-card alarm-history-card">
    <div className="pro-card-head compact"><div><h2>Alarmhistorik</h2><p>Hvornår alarmer opstod og blev løst{hasSecurity ? ", og hvem der har logget ind" : ""} · seneste 300</p></div><BellRing size={20}/></div>

    <div className={`alarm-active${active.length ? " has-alarms" : ""}`}>
      {active.length === 0
        ? <span><CheckCircle2 size={16}/> Ingen aktive alarmer</span>
        : active.map(a => <span key={a.code} className={`sev-${a.severity ?? "info"}`}><TriangleAlert size={16}/><strong>{a.text}</strong><small>aktiv i {duration(now - (a.since ?? now))}</small></span>)}
    </div>

    {hasSecurity && <div className="alarm-filter" role="group" aria-label="Filter">
      {([["all", "Alle"], ["alarms", "Alarmer"], ["security", "Login og brugere"]] as [Filter, string][]).map(([id, label]) =>
        <button key={id} type="button" className={filter === id ? "active" : ""} onClick={() => setFilter(id)}>{label}</button>)}
    </div>}

    {error ? <p className="settings-help">{error}</p> : shown.length === 0
      ? <div className="history-chart-empty" style={{ height: 80 }}><span>Ingen hændelser endnu. Alarmer fra Diagnostik bliver logget her, når de opstår.</span></div>
      : <ul className="alarm-log">{shown.map((event, index) => {
        const info = kindInfo(event);
        const Icon = info.icon;
        return <li key={`${event.time}-${index}`} className={`tone-${info.tone}`}>
          <time>{when(event.time)}</time>
          <span className="alarm-badge"><Icon size={14}/>{info.label}</span>
          <strong>{event.text}</strong>
          <em>{event.kind === "alarm_cleared" && event.duration !== undefined ? `varede ${duration(event.duration)}`
            : event.user ? `${event.user}${event.by && event.by !== event.user ? ` · af ${event.by}` : ""}${event.ip ? ` · ${event.ip}` : ""}` : event.code ?? ""}</em>
        </li>;
      })}</ul>}
  </article>;
}
