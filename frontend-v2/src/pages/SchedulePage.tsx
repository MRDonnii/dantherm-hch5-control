import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { CalendarClock, Copy, Moon, Palmtree, Plus, Save, Trash2, Undo2, X } from "lucide-react";
import { postJson, requestJson } from "../lib/api";
import {
  DAY_NAMES, DAY_SHORT, LABEL_SUGGESTIONS, MAX_PERIODS_PER_DAY, TEMPLATES, WEEKDAYS, WEEKEND,
  cloneWeek, formatDuration, fromLocalInput, overlaps, sameWeek, segments, snap, sortDay, span,
  toLocalInput, toMinutes, toTime, wrapsMidnight, type Period, type PeriodMode, type WeekPeriods,
} from "../lib/schedule";
import { useTopbarNotice } from "../lib/topbar-notice";
import "../styles/schedule.css";

type Data = Record<string, unknown>;
type Selected = { day: number; index: number } | null;
type Drag = { day: number; index: number; kind: "move" | "start" | "end"; x: number; width: number; start: number; end: number; moved: boolean };
type NextChange = { at: number; level: number | null; label: string | null; mode: PeriodMode | null } | null;
type NowPeriod = (Period & { set_level: number | null; min_level: number | null }) | null;

const MODE_TEXT: Record<PeriodMode, { title: string; help: string }> = {
  set: { title: "Grundtrin", help: "Erstatter det normale grundtrin. CO₂ og fugt kan stadig hæve ventilationen." },
  min: { title: "Mindst", help: "Ventilationen kører mindst på dette trin; automatikken må gerne gå højere." },
};

function num(value: unknown, fallback: number) { const n = Number(value); return Number.isFinite(n) ? n : fallback; }
function clock(epoch: number) {
  const d = new Date(epoch * 1000);
  const today = new Date();
  const time = d.toLocaleTimeString("da-DK", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return `i dag ${time}`;
  return `${DAY_NAMES[(d.getDay() + 6) % 7].toLowerCase()} ${time}`;
}
function periodName(period: Period) { return period.label || `${period.start}–${period.end}`; }

export function SchedulePage() {
  const { setNotice } = useTopbarNotice();
  const [controller, setController] = useState<Data>({});
  const [csrf, setCsrf] = useState("");
  const [saved, setSaved] = useState<WeekPeriods>(cloneWeek(null));
  const [draft, setDraft] = useState<WeekPeriods>(cloneWeek(null));
  const [enabled, setEnabled] = useState(false);
  const [selected, setSelected] = useState<Selected>(null);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const [copyTargets, setCopyTargets] = useState<number[]>([]);
  const [copyDay, setCopyDay] = useState<number | null>(null);
  const drag = useRef<Drag | null>(null);
  // Holiday form
  const [vacation, setVacation] = useState({ enabled: false, from: "", until: "", level: 1 });

  const apply = useCallback((next: Data) => {
    setController(next);
    const week = cloneWeek(next.schedule_periods as WeekPeriods | undefined);
    setSaved(week); setDraft(week);
    setEnabled(next.schedule_enabled === true);
    setVacation({ enabled: next.vacation_enabled === true, from: toLocalInput(next.vacation_from), until: toLocalInput(next.vacation_until), level: num(next.vacation_level, 1) });
  }, []);

  const refresh = useCallback(async () => {
    const [state, auth] = await Promise.all([
      requestJson<Data>("/api/controller/state?compact=1", { timeoutMs: 4000 }),
      requestJson<{ csrf?: string | null }>("/api/auth/status", { timeoutMs: 3500 }),
    ]);
    apply(state); setCsrf(auth.csrf ?? "");
  }, [apply]);
  useEffect(() => { void refresh().catch(() => setNotice("Kunne ikke hente ugeplanen.")); }, [refresh, setNotice]);
  useEffect(() => { const timer = window.setInterval(() => setNow(new Date()), 30000); return () => window.clearInterval(timer); }, []);

  const dirty = !sameWeek(draft, saved) || enabled !== (controller.schedule_enabled === true);
  const rows = useMemo(() => segments(draft), [draft]);
  const today = (now.getDay() + 6) % 7;
  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  const current = selected ? draft[String(selected.day)]?.[selected.index] : undefined;
  const nightOn = controller.night_enabled === true;
  const nightStart = toMinutes(String(controller.night_start ?? "22:00"));
  const nightEnd = toMinutes(String(controller.night_end ?? "06:00"));
  const nightLevel = num(controller.night_level, 2);

  const updatePeriod = (day: number, index: number, patch: Partial<Period>) => {
    setDraft(week => {
      const next = cloneWeek(week);
      next[String(day)][index] = { ...next[String(day)][index], ...patch };
      return next;
    });
  };
  const commitSort = (day: number, index: number) => {
    // Sort by start time and keep the selection on the same period.
    const next = cloneWeek(draft);
    const period = next[String(day)][index];
    if (!period) return;
    next[String(day)] = sortDay(next[String(day)]);
    setDraft(next);
    setSelected({ day, index: next[String(day)].indexOf(period) });
  };
  const addPeriod = (day: number, atMinute: number) => {
    if ((draft[String(day)] ?? []).length >= MAX_PERIODS_PER_DAY) { setNotice(`Højst ${MAX_PERIODS_PER_DAY} perioder pr. dag.`); return; }
    const start = Math.min(snap(atMinute, 30), 1440 - 60);
    const period: Period = { start: toTime(start), end: toTime(Math.min(start + 120, 1440)), level: 3, mode: "set", label: "" };
    const next = cloneWeek(draft);
    next[String(day)] = sortDay([...next[String(day)], period]);
    setDraft(next);
    setSelected({ day, index: next[String(day)].indexOf(period) });
    setCopyTargets([]);
  };
  const removePeriod = () => {
    if (!selected) return;
    const next = cloneWeek(draft);
    next[String(selected.day)].splice(selected.index, 1);
    setDraft(next); setSelected(null);
  };
  const copyTo = (targets: number[]) => {
    if (!selected || !current) return;
    const next = cloneWeek(draft);
    for (const day of targets) {
      if (day === selected.day) continue;
      const list = next[String(day)].filter(p => !(p.start === current.start && p.end === current.end));
      if (list.length >= MAX_PERIODS_PER_DAY) continue;
      next[String(day)] = sortDay([...list, { ...current }]);
    }
    setDraft(next);
    setNotice(`Perioden er kopieret til ${targets.filter(d => d !== selected.day).map(d => DAY_SHORT[d]).join(", ") || "ingen dage"}.`);
    setCopyTargets([]);
  };
  const copyWholeDay = (from: number, targets: number[]) => {
    const next = cloneWeek(draft);
    for (const day of targets) if (day !== from) next[String(day)] = next[String(from)].map(p => ({ ...p }));
    setDraft(next);
    setNotice(`${DAY_NAMES[from]} er kopieret.`);
  };

  const save = async () => {
    if (!csrf) { setNotice("Sikkerhedstoken mangler. Genindlæs siden."); return; }
    setBusy(true);
    try {
      const next = await postJson<Data>("/api/controller/config", { schedule_enabled: enabled, schedule_periods: draft }, csrf);
      apply(next); setSelected(null);
      setNotice(enabled ? "Ugeplanen er gemt og aktiv." : "Ugeplanen er gemt (slået fra).");
    } catch (error) {
      setNotice(`Kunne ikke gemme: ${error instanceof Error ? error.message : "ukendt fejl"}`);
    } finally { setBusy(false); }
  };
  const undo = () => { setDraft(cloneWeek(saved)); setEnabled(controller.schedule_enabled === true); setSelected(null); };

  const saveVacation = async (enabledNow: boolean) => {
    if (!csrf) return;
    setBusy(true);
    try {
      const next = await postJson<Data>("/api/controller/config", {
        vacation_enabled: enabledNow, vacation_level: vacation.level,
        vacation_from: enabledNow ? fromLocalInput(vacation.from) : null,
        vacation_until: enabledNow ? fromLocalInput(vacation.until) : null,
      }, csrf);
      apply(next);
      setNotice(enabledNow ? "Ferie er gemt." : "Ferie er slået fra.");
    } catch (error) {
      setNotice(`Kunne ikke gemme ferie: ${error instanceof Error ? error.message : "ukendt fejl"}`);
    } finally { setBusy(false); }
  };
  const vacationPreset = (days: number) => {
    const start = vacation.from ? new Date(vacation.from) : new Date();
    const end = new Date(start.getTime() + days * 86400000);
    setVacation(v => ({ ...v, until: toLocalInput(end.getTime() / 1000) }));
  };

  // Drag to move or resize a period, snapped to 15 minutes.
  const onPointerDown = (event: ReactPointerEvent<HTMLElement>, day: number, index: number, kind: Drag["kind"]) => {
    event.stopPropagation();
    const track = (event.currentTarget.closest(".week-track") as HTMLElement | null)?.getBoundingClientRect();
    const period = draft[String(day)][index];
    if (!track || !period) return;
    const [start, end] = span(period);
    drag.current = { day, index, kind, x: event.clientX, width: track.width, start, end, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLElement>) => {
    const d = drag.current;
    if (!d) return;
    const dx = event.clientX - d.x;
    if (!d.moved && Math.abs(dx) < 4) return;
    d.moved = true;
    const delta = snap((dx / d.width) * 1440);
    const length = d.end - d.start;
    let start = d.start, end = d.end;
    if (d.kind === "move") { start = Math.max(0, Math.min(1440 - Math.min(length, 1440), d.start + delta)); end = start + length; }
    if (d.kind === "start") start = Math.max(0, Math.min(d.end - 15, d.start + delta));
    if (d.kind === "end") end = Math.max(d.start + 15, Math.min(d.start + 1440 - 15, d.end + delta));
    updatePeriod(d.day, d.index, { start: toTime(start), end: toTime(end) });
  };
  const onPointerUp = (event: ReactPointerEvent<HTMLElement>) => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    event.currentTarget.releasePointerCapture(event.pointerId);
    if (d.moved) commitSort(d.day, d.index);
    else { setSelected({ day: d.day, index: d.index }); setCopyTargets([]); }
  };
  const onTrackClick = (event: React.MouseEvent<HTMLDivElement>, day: number) => {
    const rect = event.currentTarget.getBoundingClientRect();
    addPeriod(day, ((event.clientX - rect.left) / rect.width) * 1440);
  };

  const nowPeriod = controller.schedule_now as NowPeriod;
  const nextChange = controller.schedule_next_change as NextChange;
  const scheduleActive = controller.schedule_active === true;
  const vacationActive = controller.vacation_active === true;
  const vacationPending = controller.vacation_pending === true;
  const manual = controller.mode === "manual";

  const nightBands = (day: number) => {
    if (!nightOn || nightStart === nightEnd) return [];
    if (nightStart < nightEnd) return [[nightStart, nightEnd]];
    return [[nightStart, 1440], [0, nightEnd]];
  };

  return <section className="dashboard-overview page-enter schedule-page">
    <header className="overview-heading-row"><div>
      <span className="eyebrow">UGEPLAN</span>
      <h1>Ugeplan og ferie</h1>
      <p>Tegn husets rytme: lav ventilation mens I er ude, mere når der laves mad. Klik på en dag for at tilføje en periode, og træk i den for at flytte eller ændre længden.</p>
    </div></header>

    <div className="schedule-status">
      <div className={`schedule-tile${scheduleActive ? " is-active" : ""}`}>
        <span>Lige nu</span>
        {vacationActive ? <strong>Ferie · trin {num(controller.vacation_level, 1)}</strong>
          : manual ? <strong>Manuel drift</strong>
          : scheduleActive && nowPeriod ? <strong>{periodName(nowPeriod)} · trin {nowPeriod.set_level ?? nowPeriod.min_level}</strong>
          : <strong>Normal drift · trin {num(controller.effective_level, 0) || "—"}</strong>}
        <small>{manual ? "Ugeplanen gælder ikke i Manuel." : vacationActive ? "Ferie går forud for ugeplanen." : controller.effective_reason ? String(controller.effective_reason) : "—"}</small>
      </div>
      <div className="schedule-tile">
        <span>Næste ændring</span>
        {controller.schedule_enabled === true && nextChange
          ? <><strong>{clock(nextChange.at)}</strong><small>{nextChange.level ? `${nextChange.label || MODE_TEXT[nextChange.mode ?? "set"].title} · trin ${nextChange.level}` : "Tilbage til normal drift"}</small></>
          : <><strong>—</strong><small>{controller.schedule_enabled === true ? "Ingen perioder i ugeplanen" : "Ugeplanen er slået fra"}</small></>}
      </div>
      <div className={`schedule-tile${vacationActive || vacationPending ? " is-vacation" : ""}`}>
        <span>Ferie</span>
        <strong>{vacationActive ? "Aktiv" : vacationPending ? "Planlagt" : "Fra"}</strong>
        <small>{vacationActive ? (controller.vacation_remaining_seconds ? `Slutter om ${formatDuration(num(controller.vacation_remaining_seconds, 0))}` : "Indtil den slås fra")
          : vacationPending ? `Starter om ${formatDuration(num(controller.vacation_starts_in_seconds, 0))}` : "Ingen ferie planlagt"}</small>
      </div>
    </div>

    <article className="surface panel-card schedule-card">
      <div className="pro-card-head compact">
        <div><h2>Uge</h2><p>Farven viser trinnet. Perioder gælder i Local Auto og Smart Auto.</p></div>
        <label className="schedule-switch"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)}/><span/><strong>{enabled ? "Ugeplan til" : "Ugeplan fra"}</strong></label>
      </div>

      <div className="schedule-toolbar">
        <label>Skabelon<select value="" onChange={e => { const t = TEMPLATES.find(item => item.id === e.target.value); if (t && window.confirm(`${t.name}: ${t.description}\n\nErstat den nuværende uge?`)) { setDraft(t.build()); setSelected(null); } }}>
          <option value="">Vælg…</option>{TEMPLATES.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select></label>
        <div className="schedule-legend" aria-label="Trin">{[1, 2, 3, 4, 5, 6].map(level => <span key={level} className={`lvl-${level}`}>{level}</span>)}{nightOn && <span className="legend-night"><Moon size={11}/> Nat · trin {nightLevel}</span>}</div>
      </div>

      <div className={`week-grid${enabled ? "" : " is-off"}`}>
        <div className="week-ruler" aria-hidden="true"><span/>{[0, 3, 6, 9, 12, 15, 18, 21, 24].map(hour => <i key={hour} style={{ left: `${(hour / 24) * 100}%` }}>{String(hour).padStart(2, "0")}</i>)}</div>
        {rows.map((row, day) => <div key={day} className={`week-row${day === today ? " is-today" : ""}`}>
          <div className="week-day"><strong>{DAY_SHORT[day]}</strong>
            <button type="button" className="week-day-copy" title={`Kopiér ${DAY_NAMES[day].toLowerCase()} til andre dage`} aria-label={`Kopiér ${DAY_NAMES[day].toLowerCase()} til andre dage`} aria-expanded={copyDay === day} onClick={() => setCopyDay(open => open === day ? null : day)}><Copy size={12}/></button>
            {copyDay === day && <div className="week-copy-menu" role="menu">
              <small>Kopiér {DAY_NAMES[day].toLowerCase()} til</small>
              {([["Hverdage", WEEKDAYS], ["Weekend", WEEKEND], ["Alle dage", [0, 1, 2, 3, 4, 5, 6]]] as [string, number[]][]).map(([label, targets]) =>
                <button key={label} type="button" role="menuitem" onClick={() => { copyWholeDay(day, targets); setCopyDay(null); }}>{label}</button>)}
              <button type="button" role="menuitem" className="muted" onClick={() => setCopyDay(null)}>Annuller</button>
            </div>}
          </div>
          <div className="week-track" onClick={event => onTrackClick(event, day)} role="group" aria-label={DAY_NAMES[day]}>
            {[6, 12, 18].map(hour => <b key={hour} className="week-hour-line" style={{ left: `${(hour / 24) * 100}%` }}/>)}
            {nightBands(day).map(([from, to], i) => <div key={i} className="week-night" style={{ left: `${(from / 1440) * 100}%`, width: `${((to - from) / 1440) * 100}%` }} title={`Natsænkning ${controller.night_start}–${controller.night_end} · trin ${nightLevel}`}/>)}
            {row.map(segment => {
              const isSelected = selected?.day === segment.day && selected.index === segment.index;
              const p = segment.period;
              const widthPct = ((segment.to - segment.from) / 1440) * 100;
              return <div key={`${segment.day}-${segment.index}-${segment.continued}`}
                className={`week-block lvl-${p.level} mode-${p.mode}${isSelected ? " is-selected" : ""}${segment.continued ? " is-continued" : ""}`}
                style={{ left: `${(segment.from / 1440) * 100}%`, width: `${widthPct}%` }}
                title={`${periodName(p)} · ${p.start}–${p.end} · ${MODE_TEXT[p.mode].title} trin ${p.level}`}
                onClick={event => event.stopPropagation()}
                onPointerDown={event => segment.continued || wrapsMidnight(p) ? (event.stopPropagation(), setSelected({ day: segment.day, index: segment.index })) : onPointerDown(event, segment.day, segment.index, "move")}
                onPointerMove={onPointerMove} onPointerUp={onPointerUp}>
                {!segment.continued && !wrapsMidnight(p) && <span className="week-handle start" onPointerDown={event => onPointerDown(event, segment.day, segment.index, "start")} onPointerMove={onPointerMove} onPointerUp={onPointerUp}/>}
                <span className="week-block-text">{widthPct > 7 && <strong>{p.mode === "min" && widthPct > 11 ? "≥" : ""}{p.level}</strong>}{widthPct > 14 && <small>{p.label || `${p.start}–${p.end}`}</small>}</span>
                {!segment.continued && !wrapsMidnight(p) && <span className="week-handle end" onPointerDown={event => onPointerDown(event, segment.day, segment.index, "end")} onPointerMove={onPointerMove} onPointerUp={onPointerUp}/>}
              </div>;
            })}
            {day === today && <div className="week-now" style={{ left: `${(nowMinutes / 1440) * 100}%` }} title={`Nu ${toTime(nowMinutes)}`}/>}
          </div>
        </div>)}
      </div>

      {current && selected ? <div className="period-editor">
        <div className="period-editor-head">
          <h3>{DAY_NAMES[selected.day]} · {periodName(current)}</h3>
          <button type="button" className="icon-button" aria-label="Luk" onClick={() => setSelected(null)}><X size={16}/></button>
        </div>
        <div className="settings-grid">
          <label>Navn<input value={current.label} maxLength={40} placeholder="Fx Ude, Madlavning" onChange={e => updatePeriod(selected.day, selected.index, { label: e.target.value })}/>
            <span className="period-chips">{LABEL_SUGGESTIONS.map(label => <button key={label} type="button" onClick={() => updatePeriod(selected.day, selected.index, { label })}>{label}</button>)}</span></label>
          <div className="period-times">
            <label>Fra<input type="time" step={900} value={current.start} onChange={e => e.target.value && updatePeriod(selected.day, selected.index, { start: e.target.value })} onBlur={() => commitSort(selected.day, selected.index)}/></label>
            <label>Til<input type="time" step={900} value={current.end} onChange={e => e.target.value && updatePeriod(selected.day, selected.index, { end: e.target.value })}/></label>
          </div>
          <div className="period-field"><span>Trin</span><div className="pro-levels period-levels">{[1, 2, 3, 4, 5, 6].map(level => <button key={level} type="button" className={`lvl-${level}${current.level === level ? " active" : ""}`} onClick={() => updatePeriod(selected.day, selected.index, { level })}>{level}</button>)}</div></div>
          <div className="period-field"><span>Type</span><div className="pro-segment period-mode">{(["set", "min"] as PeriodMode[]).map(mode => <button key={mode} type="button" className={current.mode === mode ? "active" : ""} onClick={() => updatePeriod(selected.day, selected.index, { mode })}>{MODE_TEXT[mode].title}</button>)}</div><small className="settings-field-help">{MODE_TEXT[current.mode].help}</small></div>
        </div>
        {wrapsMidnight(current) && <p className="settings-help">Perioden fortsætter efter midnat til {DAY_NAMES[(selected.day + 1) % 7].toLowerCase()} kl. {current.end}.</p>}
        {overlaps(draft, selected.day, selected.index) && <p className="settings-warning">Perioden overlapper en anden. Hvor de overlapper, bruges det højeste trin.</p>}
        {nightOn && <p className="settings-help"><Moon size={12}/> Natsænkningen ({String(controller.night_start)}–{String(controller.night_end)}) begrænser stadig ventilationen om natten.</p>}
        <div className="period-copy">
          <span>Kopiér til</span>
          {DAY_SHORT.map((name, day) => <button key={day} type="button" disabled={day === selected.day} className={copyTargets.includes(day) ? "active" : ""} onClick={() => setCopyTargets(t => t.includes(day) ? t.filter(d => d !== day) : [...t, day])}>{name}</button>)}
          <button type="button" className="text-action" onClick={() => setCopyTargets(WEEKDAYS)}>Hverdage</button>
          <button type="button" className="text-action" onClick={() => setCopyTargets(WEEKEND)}>Weekend</button>
          <button type="button" className="secondary-action" disabled={!copyTargets.length} onClick={() => copyTo(copyTargets)}><Copy size={13}/>Kopiér</button>
        </div>
        <div className="diag-actions"><button type="button" className="danger-outline" onClick={removePeriod}><Trash2 size={14}/>Slet periode</button></div>
      </div> : <p className="schedule-hint"><Plus size={13}/> Klik på en dag for at tilføje en periode. Klik på en periode for at redigere den.</p>}
    </article>

    <article className="surface panel-card schedule-card vacation-card">
      <div className="pro-card-head compact">
        <div><h2>Ferie</h2><p>Kører et fast lavt trin, mens huset står tomt. Går forud for ugeplan, nat og automatik.</p></div>
        <Palmtree size={20}/>
      </div>
      <div className="settings-grid">
        <label>Fra<input type="datetime-local" value={vacation.from} onChange={e => setVacation(v => ({ ...v, from: e.target.value }))}/><small className="settings-field-help">Tom = med det samme.</small></label>
        <label>Til<input type="datetime-local" value={vacation.until} onChange={e => setVacation(v => ({ ...v, until: e.target.value }))}/>
          <span className="period-chips">{[[3, "3 dage"], [7, "1 uge"], [14, "2 uger"], [21, "3 uger"]].map(([days, label]) => <button key={label} type="button" onClick={() => vacationPreset(Number(days))}>{label}</button>)}</span>
          <small className="settings-field-help">Tom = indtil den slås fra.</small></label>
        <div className="period-field"><span>Trin under ferie</span><div className="pro-levels period-levels">{[1, 2, 3].map(level => <button key={level} type="button" className={`lvl-${level}${vacation.level === level ? " active" : ""}`} onClick={() => setVacation(v => ({ ...v, level }))}>{level}</button>)}</div>
          <small className="settings-field-help">Husets minimumstrin (Hus og luftmængde) gælder stadig.</small></div>
      </div>
      <div className="diag-actions">
        <button type="button" className="primary-action" disabled={busy || !csrf} onClick={() => void saveVacation(true)}><Palmtree size={14}/>{vacation.enabled ? "Gem ferie" : vacation.from ? "Planlæg ferie" : "Start ferie"}</button>
        {vacation.enabled && <button type="button" className="secondary-action" disabled={busy} onClick={() => void saveVacation(false)}>Stop ferie</button>}
      </div>
    </article>

    {dirty && <div className="settings-savebar schedule-savebar">
      <span><CalendarClock size={14}/> Ugeplanen har ændringer, der ikke er gemt.</span>
      <div className="diag-actions">
        <button type="button" className="secondary-action" disabled={busy} onClick={undo}><Undo2 size={14}/>Fortryd</button>
        <button type="button" className="primary-action" disabled={busy || !csrf} onClick={() => void save()}><Save size={14}/>{busy ? "Gemmer…" : "Gem ugeplan"}</button>
      </div>
    </div>}
  </section>;
}
