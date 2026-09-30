import { useCallback, useEffect, useMemo, useState } from "react";
import { Calculator, ClipboardList, FileText, Gauge, House, Plus, Printer, Save, Trash2, Undo2 } from "lucide-react";
import { postJson, requestJson } from "../lib/api";
import {
  LS_TO_M3H, ROOM_TYPES, calculate, emptyMeta, fmt, newRoom, recommendedLevel, sizingPatch,
  type LevelPlan, type Meta, type Project, type Room, type RoomType, type Status,
} from "../lib/balancing";
import { useTopbarNotice } from "../lib/topbar-notice";
import { BalancingReport, buildReport, type Report } from "../components/BalancingReport";
import "../styles/balancing.css";

type Data = Record<string, unknown>;
type Step = "rooms" | "design" | "measure" | "report";
type ReportSummary = { id: string; created_at: number; created_by?: string | null; site?: string; verdict?: string; level?: number | null };

const STEPS: { id: Step; title: string; lead: string; icon: typeof House }[] = [
  { id: "rooms", title: "1 · Rum", lead: "Navn, type, m² og loftshøjde", icon: House },
  { id: "design", title: "2 · Beregning", lead: "Krav pr. rum og anbefalet trin", icon: Calculator },
  { id: "measure", title: "3 · Måling", lead: "Målt l/s ved hver ventil", icon: Gauge },
  { id: "report", title: "4 · Rapport", lead: "Udskriv eller gem som PDF", icon: FileText },
];

const STATUS_TEXT: Record<Status, string> = { ok: "OK", warn: "Justér", bad: "Afviger", none: "—" };

function numberOrNull(value: string): number | null {
  if (value.trim() === "") return null;
  const n = Number(value.replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

function NumInput({ value, onChange, step = 0.1, min = 0, placeholder }: { value: number | null; onChange: (v: number | null) => void; step?: number; min?: number; placeholder?: string }) {
  const [text, setText] = useState(value === null || value === undefined ? "" : String(value).replace(".", ","));
  useEffect(() => { setText(value === null || value === undefined ? "" : String(value).replace(".", ",")); }, [value]);
  return <input inputMode="decimal" value={text} placeholder={placeholder} data-step={step} data-min={min}
    onChange={e => { setText(e.target.value); const n = numberOrNull(e.target.value); if (n !== null || e.target.value.trim() === "") onChange(n); }}/>;
}

export function BalancingPage() {
  const { setNotice } = useTopbarNotice();
  const [step, setStep] = useState<Step>("rooms");
  const [saved, setSaved] = useState<Project>({ rooms: [], meta: emptyMeta(), measure_level: null });
  const [project, setProject] = useState<Project>({ rooms: [], meta: emptyMeta(), measure_level: null });
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [controller, setController] = useState<Data>({});
  const [unitState, setUnitState] = useState<Data>({});
  const [csrf, setCsrf] = useState("");
  const [busy, setBusy] = useState(false);
  const [openReport, setOpenReport] = useState<Report | null>(null);
  const [previousMode, setPreviousMode] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [state, ctrl, auth] = await Promise.all([
      requestJson<{ project: Project; reports: ReportSummary[] }>("/api/balancing"),
      requestJson<Data>("/api/controller/state?compact=1", { timeoutMs: 4000 }),
      requestJson<{ csrf?: string | null }>("/api/auth/status"),
    ]);
    const next = { ...state.project, meta: { ...emptyMeta(), ...state.project.meta } };
    setSaved(next); setProject(next); setReports(state.reports ?? []); setController(ctrl); setCsrf(auth.csrf ?? "");
    requestJson<Data>("/state.json", { timeoutMs: 3000 }).then(setUnitState).catch(() => {});
  }, []);
  useEffect(() => { void load().catch(error => setNotice(`Kunne ikke hente indreguleringen: ${error instanceof Error ? error.message : ""}`)); }, [load, setNotice]);

  const excess = Number((controller.balance as { target_excess_percent?: number } | undefined)?.target_excess_percent ?? controller.balance_extract_excess_percent ?? 5);
  const result = useMemo(() => calculate(project.rooms, Number.isFinite(excess) ? excess : 5), [project.rooms, excess]);
  const plan = (controller.airflow_plan ?? {}) as { levels?: LevelPlan };
  const recommended = recommendedLevel(result, plan.levels);
  const level = project.measure_level ?? recommended;
  const profiles = (controller.profiles ?? {}) as Record<string, { supply: number; extract: number }>;
  const profile = level ? profiles[String(level)] ?? null : null;
  const dirty = JSON.stringify(project) !== JSON.stringify(saved);
  const defaultHeight = project.rooms.at(-1)?.height ?? 2.5;

  const setRoom = (id: string, patch: Partial<Room>) => setProject(p => ({ ...p, rooms: p.rooms.map(r => r.id === id ? { ...r, ...patch } : r) }));
  const setType = (id: string, type: RoomType) => setRoom(id, { type, supply: ROOM_TYPES[type].supply, extract: ROOM_TYPES[type].extract });
  const setMeta = (patch: Partial<Meta>) => setProject(p => ({ ...p, meta: { ...p.meta, ...patch } }));
  const addRoom = (type: RoomType) => setProject(p => ({ ...p, rooms: [...p.rooms, newRoom(type, defaultHeight)] }));
  const removeRoom = (id: string) => setProject(p => ({ ...p, rooms: p.rooms.filter(r => r.id !== id) }));

  const save = async (quiet = false) => {
    if (!csrf) return false;
    setBusy(true);
    try {
      const state = await postJson<{ project: Project; reports: ReportSummary[] }>("/api/balancing/project", project, csrf);
      const next = { ...state.project, meta: { ...emptyMeta(), ...state.project.meta } };
      setSaved(next); setProject(next);
      if (!quiet) setNotice("Indreguleringen er gemt på Pi'en.");
      return true;
    } catch (error) {
      setNotice(`Kunne ikke gemme: ${error instanceof Error ? error.message : "ukendt fejl"}`);
      return false;
    } finally { setBusy(false); }
  };

  const config = async (patch: Data, success: string) => {
    if (!csrf) return;
    setBusy(true);
    try { setController(await postJson<Data>("/api/controller/config", patch, csrf)); setNotice(success); }
    catch (error) { setNotice(`Kunne ikke ændre anlægget: ${error instanceof Error ? error.message : "ukendt fejl"}`); }
    finally { setBusy(false); }
  };
  const startMeasuring = () => {
    if (!level) return;
    if (previousMode === null) setPreviousMode(String(controller.mode ?? "local_auto"));
    void config({ mode: "manual", manual_level: level }, `Anlægget kører nu fast på trin ${level}. Vent et par minutter, før du måler.`);
  };
  const stopMeasuring = () => {
    const mode = previousMode && previousMode !== "manual" ? previousMode : "local_auto";
    void config({ mode }, "Målingen er afsluttet, og anlægget kører automatisk igen.");
    setPreviousMode(null);
  };
  const storeMeasuredTotals = () => {
    if (!level || !profile || result.measuredSupply === null || result.measuredExtract === null) return;
    const measured = { ...((controller.airflow_measured ?? {}) as Data) };
    measured[String(level)] = {
      supply: Math.round(result.measuredSupply * LS_TO_M3H), extract: Math.round(result.measuredExtract * LS_TO_M3H),
      supply_percent: profile.supply, extract_percent: profile.extract,
    };
    void config({ airflow_measured: measured }, `Målt luftmængde gemt for trin ${level}. Husberegningen bruger den nu.`);
  };
  const applySizing = () => {
    if (!project.rooms.length) return;
    const patch = sizingPatch(project.rooms);
    if (!window.confirm(`Overfør til Hus og luftmængde?\n\nAreal ${patch.house_area_m2} m², loft ${patch.ceiling_height_m} m, ${patch.house_bathrooms} bad, ${patch.house_utility_rooms} toilet/bryggers. Grundtrinnet beregnes så ud fra huset.`)) return;
    void config(patch, "Husets størrelse er overført til Hus og luftmængde.");
  };

  const currentReport = buildReport(result, project.meta, level, profile, {
    version: String(unitState.version ?? unitState.system_hch5_version ?? ""),
    outdoor: typeof unitState.outdoor_temp === "number" ? unitState.outdoor_temp : null,
    extract: typeof unitState.extract_temp === "number" ? unitState.extract_temp : null,
  });
  const saveReport = async () => {
    if (dirty && !(await save(true))) return;
    setBusy(true);
    try {
      const state = await postJson<{ reports: ReportSummary[] }>("/api/balancing/report", currentReport, csrf);
      setReports(state.reports ?? []);
      setNotice("Rapporten er gemt på Pi'en og kan udskrives igen senere.");
    } catch (error) { setNotice(`Kunne ikke gemme rapporten: ${error instanceof Error ? error.message : "ukendt fejl"}`); }
    finally { setBusy(false); }
  };
  const showReport = async (id: string) => {
    try { setOpenReport(await requestJson<Report>(`/api/balancing/report?id=${encodeURIComponent(id)}`)); }
    catch { setNotice("Rapporten kunne ikke hentes."); }
  };
  const deleteReport = async (id: string) => {
    if (!window.confirm("Slet den gemte rapport?")) return;
    try { const state = await postJson<{ reports: ReportSummary[] }>("/api/balancing/report/delete", { id }, csrf); setReports(state.reports ?? []); if (openReport?.id === id) setOpenReport(null); }
    catch { setNotice("Rapporten kunne ikke slettes."); }
  };

  const measuring = controller.mode === "manual" && Number(controller.manual_level) === level;

  return <section className="dashboard-overview page-enter balancing-page">
    <header className="overview-heading-row no-print"><div>
      <span className="eyebrow">INDREGULERING</span>
      <h1>Indregulering af luftmængder</h1>
      <p>Skriv husets rum ind. Siden beregner luftmængden pr. ventil efter BR18, foreslår et grundtrin, hjælper med målingen og laver en rapport, der kan udskrives.</p>
    </div></header>

    <nav className="balancing-steps no-print" aria-label="Trin">
      {STEPS.map(item => { const Icon = item.icon; return <button key={item.id} type="button" aria-current={step === item.id ? "step" : undefined} onClick={() => { setStep(item.id); setOpenReport(null); }}>
        <Icon size={18}/><span><strong>{item.title}</strong><small>{item.lead}</small></span>
      </button>; })}
    </nav>

    {step === "rooms" && <article className="surface panel-card balancing-card">
      <div className="pro-card-head compact"><div><h2>Husets rum</h2><p>Alle opvarmede rum, også dem uden ventil (fx gang). Typen afgør kravet til udsugning.</p></div><House size={20}/></div>
      <div className="settings-table-wrap"><table className="settings-table balancing-rooms">
        <thead><tr><th>Navn</th><th>Type</th><th>Areal m²</th><th>Loft m</th><th>Indblæsning</th><th>Udsugning</th><th/></tr></thead>
        <tbody>{project.rooms.map(room => <tr key={room.id}>
          <td><input className="settings-table-name" value={room.name} maxLength={60} onChange={e => setRoom(room.id, { name: e.target.value })}/></td>
          <td><select value={room.type} onChange={e => setType(room.id, e.target.value as RoomType)}>{Object.entries(ROOM_TYPES).map(([id, t]) => <option key={id} value={id}>{t.label}</option>)}</select></td>
          <td><NumInput value={room.area} onChange={v => setRoom(room.id, { area: v ?? 0 })}/></td>
          <td><NumInput value={room.height} onChange={v => setRoom(room.id, { height: v ?? 2.5 })}/></td>
          <td className="center"><input type="checkbox" checked={room.supply} onChange={e => setRoom(room.id, { supply: e.target.checked })} aria-label={`${room.name} indblæsning`}/></td>
          <td className="center"><input type="checkbox" checked={room.extract} onChange={e => setRoom(room.id, { extract: e.target.checked })} aria-label={`${room.name} udsugning`}/></td>
          <td><button type="button" className="icon-button" aria-label={`Slet ${room.name}`} onClick={() => removeRoom(room.id)}><Trash2 size={15}/></button></td>
        </tr>)}</tbody>
      </table></div>
      <div className="balancing-add">
        <span>Tilføj rum:</span>
        {(Object.keys(ROOM_TYPES) as RoomType[]).map(type => <button key={type} type="button" className="secondary-action" onClick={() => addRoom(type)}><Plus size={14}/>{ROOM_TYPES[type].label}</button>)}
      </div>
      <div className="balancing-totals">
        <span>Areal <strong>{fmt(result.area)} m²</strong></span>
        <span>Volumen <strong>{fmt(result.volume, 0)} m³</strong></span>
        <span>Rum <strong>{project.rooms.length}</strong></span>
      </div>
    </article>}

    {step === "design" && <article className="surface panel-card balancing-card">
      <div className="pro-card-head compact"><div><h2>Beregnet luftmængde</h2><p>Udsugning giver hvert vådrum sit minimum. Indblæsningen balanceres mod udsugningen og fordeles efter areal.</p></div><Calculator size={20}/></div>
      <div className="balancing-summary">
        <div><span>Indblæsning i alt</span><strong>{fmt(result.supplyTotal)} l/s</strong><small>{fmt(result.supplyTotal * LS_TO_M3H, 0)} m³/h · {result.supplyTotal > result.areaRequirement + 0.05 ? `balanceret, ${fmt(result.extractExcess, 0)} % mere udsugning` : "0,3 l/s pr. m²"}</small></div>
        <div><span>Udsugning i alt</span><strong>{fmt(result.extractTotal)} l/s</strong><small>{fmt(result.extractTotal * LS_TO_M3H, 0)} m³/h · vådrum mindst {fmt(result.wetRequirement, 0)} l/s</small></div>
        <div><span>Luftskifte</span><strong>{fmt(result.airChanges, 2)} /h</strong><small>Volumen {fmt(result.volume, 0)} m³</small></div>
        <div className="is-accent"><span>Foreslået grundtrin</span><strong>{recommended ? `Trin ${recommended}` : "—"}</strong><small>{recommended && plan.levels?.[String(recommended)] ? `ca. ${plan.levels[String(recommended)].supply_m3h} / ${plan.levels[String(recommended)].extract_m3h} m³/h${plan.levels[String(recommended)].measured ? " (målt)" : " (beregnet)"}` : "Tilføj rum først"}</small></div>
      </div>
      {result.warnings.length > 0 && <ul className="balancing-warnings">{result.warnings.map(w => <li key={w}>{w}</li>)}</ul>}
      <div className="settings-table-wrap"><table className="settings-table">
        <thead><tr><th>Rum</th><th>Type</th><th>m²</th><th>Indblæsning l/s</th><th>m³/h</th><th>Udsugning l/s</th><th>m³/h</th></tr></thead>
        <tbody>{result.rooms.map(r => <tr key={r.room.id}>
          <td><strong>{r.room.name}</strong></td><td>{ROOM_TYPES[r.room.type].label}</td><td>{fmt(r.room.area)}</td>
          <td>{r.room.supply ? fmt(r.designSupply) : "—"}</td><td>{r.room.supply ? fmt(r.designSupply * LS_TO_M3H, 0) : ""}</td>
          <td>{r.room.extract ? fmt(r.designExtract) : "—"}</td><td>{r.room.extract ? fmt(r.designExtract * LS_TO_M3H, 0) : ""}</td>
        </tr>)}</tbody>
      </table></div>
      <div className="diag-actions">
        <button type="button" className="secondary-action" disabled={busy || !project.rooms.length} onClick={applySizing}><House size={14}/>Overfør til Hus og luftmængde</button>
        <button type="button" className="primary-action" onClick={() => setStep("measure")}><Gauge size={14}/>Videre til måling</button>
      </div>
      <p className="settings-help">Overførsel sætter boligareal, gennemsnitlig loftshøjde, antal bad og toilet/bryggers under Indstillinger → Hus og luftmængde, så controllerens grundtrin følger samme beregning.</p>
    </article>}

    {step === "measure" && <article className="surface panel-card balancing-card">
      <div className="pro-card-head compact"><div><h2>Måling ved ventilerne</h2><p>Kør anlægget fast på grundtrinnet, mål hver ventil med flowmåleren og skriv l/s ind.</p></div><Gauge size={20}/></div>
      <div className="balancing-measure-bar">
        <label>Mål ved trin<select value={level ?? ""} onChange={e => setProject(p => ({ ...p, measure_level: e.target.value ? Number(e.target.value) : null }))}>
          {[1, 2, 3, 4, 5, 6].map(l => <option key={l} value={l}>Trin {l}{l === recommended ? " (foreslået)" : ""}</option>)}
        </select></label>
        <span className="balancing-profile">{profile ? `Indblæsning ${profile.supply} % · udsugning ${profile.extract} %` : ""}</span>
        {measuring
          ? <button type="button" className="secondary-action" disabled={busy} onClick={stopMeasuring}><Undo2 size={14}/>Afslut måling</button>
          : <button type="button" className="primary-action" disabled={busy || !level} onClick={startMeasuring}><Gauge size={14}/>Kør fast på trin {level ?? "—"}</button>}
        <span className={`balancing-mode${measuring ? " on" : ""}`}>{measuring ? `Kører manuelt på trin ${level}` : `Anlægget: ${String(controller.mode ?? "—").replace("_", " ")} · trin ${String(controller.effective_level ?? "—")}`}</span>
      </div>
      <div className="settings-table-wrap"><table className="settings-table balancing-measure">
        <thead><tr><th>Rum</th><th>Ind krav</th><th>Ind målt l/s</th><th>Ventil</th><th>Status</th><th>Ud krav</th><th>Ud målt l/s</th><th>Ventil</th><th>Status</th><th>Note</th></tr></thead>
        <tbody>{result.rooms.filter(r => r.room.supply || r.room.extract).map(r => <tr key={r.room.id}>
          <td><strong>{r.room.name}</strong></td>
          {r.room.supply ? <>
            <td>{fmt(r.designSupply)}</td>
            <td><NumInput value={r.room.measured_supply} placeholder="l/s" onChange={v => setRoom(r.room.id, { measured_supply: v })}/></td>
            <td><input className="balancing-valve" value={r.room.valve_supply} maxLength={40} placeholder="fx 4 omg." onChange={e => setRoom(r.room.id, { valve_supply: e.target.value })}/></td>
            <td><span className={`balancing-status ${r.supplyStatus}`}>{STATUS_TEXT[r.supplyStatus]}{r.supplyDeviation !== null && ` ${r.supplyDeviation > 0 ? "+" : ""}${fmt(r.supplyDeviation, 0)} %`}</span></td>
          </> : <td colSpan={4} className="muted">Ingen indblæsning</td>}
          {r.room.extract ? <>
            <td>{fmt(r.designExtract)}</td>
            <td><NumInput value={r.room.measured_extract} placeholder="l/s" onChange={v => setRoom(r.room.id, { measured_extract: v })}/></td>
            <td><input className="balancing-valve" value={r.room.valve_extract} maxLength={40} placeholder="fx 3 omg." onChange={e => setRoom(r.room.id, { valve_extract: e.target.value })}/></td>
            <td><span className={`balancing-status ${r.extractStatus}`}>{STATUS_TEXT[r.extractStatus]}{r.extractDeviation !== null && ` ${r.extractDeviation > 0 ? "+" : ""}${fmt(r.extractDeviation, 0)} %`}</span></td>
          </> : <td colSpan={4} className="muted">Ingen udsugning</td>}
          <td><input className="balancing-note" value={r.room.note} maxLength={120} onChange={e => setRoom(r.room.id, { note: e.target.value })}/></td>
        </tr>)}</tbody>
      </table></div>
      <div className="balancing-summary">
        <div><span>Målt indblæsning</span><strong>{fmt(result.measuredSupply)} l/s</strong><small>krav {fmt(result.supplyTotal)} l/s</small></div>
        <div><span>Målt udsugning</span><strong>{fmt(result.measuredExtract)} l/s</strong><small>krav {fmt(result.extractTotal)} l/s</small></div>
        <div><span>Balance</span><strong>{result.measuredSupply && result.measuredExtract ? `${fmt(((result.measuredExtract - result.measuredSupply) / result.measuredSupply) * 100, 0)} %` : "—"}</strong><small>udsugning over indblæsning</small></div>
        <div className={`is-verdict v-${result.verdict.replace(/\s+/g, "-").toLowerCase()}`}><span>Resultat</span><strong>{result.verdict}</strong><small>±10 % OK · ±20 % justér</small></div>
      </div>
      <div className="diag-actions">
        <button type="button" className="secondary-action" disabled={busy || result.measuredSupply === null || result.measuredExtract === null || !profile} onClick={storeMeasuredTotals}><ClipboardList size={14}/>Gem målte totaler for trin {level ?? "—"}</button>
        <button type="button" className="primary-action" onClick={() => setStep("report")}><FileText size={14}/>Videre til rapport</button>
      </div>
      <p className="settings-help">Justér ventilerne, til hvert rum er inden for ±10 %. De målte totaler kan gemmes som målt luftmængde, så husberegningen og luftbalancen bruger de rigtige tal i stedet for skønnet.</p>
    </article>}

    {step === "report" && <>
      <article className="surface panel-card balancing-card no-print">
        <div className="pro-card-head compact"><div><h2>Rapportoplysninger</h2><p>Kommer med på rapporten.</p></div><FileText size={20}/></div>
        <div className="settings-grid">
          <label>Anlæg / sted<input value={project.meta.site} maxLength={120} placeholder="Fx Familien Hansen" onChange={e => setMeta({ site: e.target.value })}/></label>
          <label>Adresse<input value={project.meta.address} maxLength={120} onChange={e => setMeta({ address: e.target.value })}/></label>
          <label>Ejer<input value={project.meta.owner} maxLength={120} onChange={e => setMeta({ owner: e.target.value })}/></label>
          <label>Tekniker<input value={project.meta.technician} maxLength={120} onChange={e => setMeta({ technician: e.target.value })}/></label>
          <label>Firma<input value={project.meta.company} maxLength={120} onChange={e => setMeta({ company: e.target.value })}/></label>
          <label>Måleinstrument<input value={project.meta.instrument} maxLength={120} placeholder="Fx flowmåler, model og kalibreringsdato" onChange={e => setMeta({ instrument: e.target.value })}/></label>
          <label className="balancing-notes">Bemærkninger<textarea value={project.meta.notes} maxLength={2000} rows={3} onChange={e => setMeta({ notes: e.target.value })}/></label>
        </div>
        <div className="diag-actions">
          <button type="button" className="primary-action" onClick={() => window.print()}><Printer size={14}/>Udskriv / gem som PDF</button>
          <button type="button" className="secondary-action" disabled={busy || !csrf} onClick={() => void saveReport()}><Save size={14}/>Gem rapport på Pi'en</button>
        </div>
      </article>
      {!openReport && <BalancingReport report={currentReport}/>}
      {openReport && <><div className="balancing-open-report no-print"><span>Gemt rapport fra {new Date((openReport.created_at ?? 0) * 1000).toLocaleString("da-DK")}</span><button type="button" className="secondary-action" onClick={() => setOpenReport(null)}>Tilbage til den aktuelle</button></div><BalancingReport report={openReport}/></>}
      {reports.length > 0 && <article className="surface panel-card balancing-card no-print">
        <div className="pro-card-head compact"><div><h2>Gemte rapporter</h2><p>Gemt på Pi'en, nyeste først.</p></div><ClipboardList size={20}/></div>
        <div className="settings-table-wrap"><table className="settings-table">
          <thead><tr><th>Dato</th><th>Anlæg</th><th>Trin</th><th>Resultat</th><th>Af</th><th/></tr></thead>
          <tbody>{reports.map(r => <tr key={r.id}>
            <td>{new Date(r.created_at * 1000).toLocaleString("da-DK", { dateStyle: "short", timeStyle: "short" })}</td>
            <td>{r.site || "—"}</td><td>{r.level ?? "—"}</td><td>{r.verdict || "—"}</td><td>{r.created_by || "—"}</td>
            <td className="balancing-report-actions"><button type="button" className="secondary-action" onClick={() => void showReport(r.id)}>Vis</button><button type="button" className="icon-button" aria-label="Slet rapport" onClick={() => void deleteReport(r.id)}><Trash2 size={14}/></button></td>
          </tr>)}</tbody>
        </table></div>
      </article>}
    </>}

    {dirty && <div className="settings-savebar no-print">
      <span>Indreguleringen har ændringer, der ikke er gemt.</span>
      <div className="diag-actions">
        <button type="button" className="secondary-action" disabled={busy} onClick={() => setProject(saved)}><Undo2 size={14}/>Fortryd</button>
        <button type="button" className="primary-action" disabled={busy || !csrf} onClick={() => void save()}><Save size={14}/>Gem</button>
      </div>
    </div>}
  </section>;
}
