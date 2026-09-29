import { LS_TO_M3H, ROOM_TYPES, TOLERANCE_OK, TOLERANCE_WARN, fmt, type Meta, type Result, type RoomType, type Status } from "../lib/balancing";

export interface ReportRoom {
  name: string; type: RoomType; area: number; height: number; supply: boolean; extract: boolean;
  designSupply: number; designExtract: number; measured_supply: number | null; measured_extract: number | null;
  valve_supply: string; valve_extract: string; supplyDeviation: number | null; extractDeviation: number | null;
  supplyStatus: Status; extractStatus: Status; note: string;
}
export interface Report {
  id?: string;
  created_at?: number;
  created_by?: string | null;
  meta: Meta;
  level: number | null;
  profile: { supply: number; extract: number } | null;
  unit: { version?: string; outdoor?: number | null; extract?: number | null };
  summary: Omit<Result, "rooms" | "warnings">;
  rooms: ReportRoom[];
  warnings: string[];
  verdict: Result["verdict"];
}

export function buildReport(result: Result, meta: Meta, level: number | null, profile: Report["profile"], unit: Report["unit"]): Report {
  const { rooms, warnings, ...summary } = result;
  return {
    meta, level, profile, unit, summary, warnings, verdict: result.verdict,
    rooms: rooms.map(r => ({
      name: r.room.name, type: r.room.type, area: r.room.area, height: r.room.height, supply: r.room.supply, extract: r.room.extract,
      designSupply: r.designSupply, designExtract: r.designExtract, measured_supply: r.room.measured_supply, measured_extract: r.room.measured_extract,
      valve_supply: r.room.valve_supply, valve_extract: r.room.valve_extract, supplyDeviation: r.supplyDeviation, extractDeviation: r.extractDeviation,
      supplyStatus: r.supplyStatus, extractStatus: r.extractStatus, note: r.room.note,
    })),
  };
}

const pct = (value: number | null) => value === null ? "—" : `${value > 0 ? "+" : ""}${fmt(value, 0)} %`;

function Cell({ on, design, measured, valve, dev, status }: { on: boolean; design: number; measured: number | null; valve: string; dev: number | null; status: Status }) {
  if (!on) return <><td className="muted">—</td><td/><td/><td/></>;
  return <>
    <td>{fmt(design)}</td>
    <td>{fmt(measured)}</td>
    <td>{valve || "—"}</td>
    <td className={`dev ${status}`}>{pct(dev)}</td>
  </>;
}

export function BalancingReport({ report }: { report: Report }) {
  const s = report.summary;
  const date = new Date((report.created_at ?? Date.now() / 1000) * 1000);
  const m = report.meta;
  return <article className="balancing-report">
    <header className="report-head">
      <div>
        <span>Indreguleringsrapport · ventilation</span>
        <h2>{m.site || "Ventilationsanlæg"}</h2>
        <p>{[m.address, m.owner && `Ejer: ${m.owner}`].filter(Boolean).join(" · ") || "Adresse ikke udfyldt"}</p>
      </div>
      <div className={`report-verdict v-${report.verdict.replace(/\s+/g, "-").toLowerCase()}`}>{report.verdict}</div>
    </header>

    <dl className="report-facts">
      <div><dt>Dato</dt><dd>{date.toLocaleDateString("da-DK", { day: "2-digit", month: "long", year: "numeric" })}</dd></div>
      <div><dt>Tekniker</dt><dd>{m.technician || report.created_by || "—"}{m.company ? ` · ${m.company}` : ""}</dd></div>
      <div><dt>Anlæg</dt><dd>Dantherm HCH5 · HCH5 Control {report.unit.version ?? ""}</dd></div>
      <div><dt>Måleinstrument</dt><dd>{m.instrument || "—"}</dd></div>
      <div><dt>Målt ved trin</dt><dd>{report.level ?? "—"}{report.profile ? ` · indblæsning ${report.profile.supply} % / udsugning ${report.profile.extract} %` : ""}</dd></div>
      <div><dt>Temperatur ved måling</dt><dd>ude {fmt(report.unit.outdoor ?? null)} °C · udsugning {fmt(report.unit.extract ?? null)} °C</dd></div>
    </dl>

    <section className="report-summary">
      <div><span>Opvarmet areal</span><strong>{fmt(s.area)} m²</strong><small>Volumen {fmt(s.volume, 0)} m³</small></div>
      <div><span>Krav indblæsning</span><strong>{fmt(s.supplyTotal)} l/s</strong><small>{fmt(s.supplyTotal * LS_TO_M3H, 0)} m³/h · min. {fmt(s.areaRequirement)} l/s (0,3 l/s pr. m²)</small></div>
      <div><span>Krav udsugning</span><strong>{fmt(s.extractTotal)} l/s</strong><small>{fmt(s.extractTotal * LS_TO_M3H, 0)} m³/h · vådrum {fmt(s.wetRequirement, 0)} l/s</small></div>
      <div><span>Målt indblæsning</span><strong>{fmt(s.measuredSupply)} l/s</strong><small>{s.measuredSupply !== null ? `${fmt(s.measuredSupply * LS_TO_M3H, 0)} m³/h · ${pct(s.measuredSupply !== null ? ((s.measuredSupply - s.supplyTotal) / s.supplyTotal) * 100 : null)}` : "Ikke målt"}</small></div>
      <div><span>Målt udsugning</span><strong>{fmt(s.measuredExtract)} l/s</strong><small>{s.measuredExtract !== null ? `${fmt(s.measuredExtract * LS_TO_M3H, 0)} m³/h · ${pct(((s.measuredExtract - s.extractTotal) / s.extractTotal) * 100)}` : "Ikke målt"}</small></div>
      <div><span>Luftskifte</span><strong>{fmt(s.measuredAirChanges ?? s.airChanges, 2)} /h</strong><small>{s.measuredAirChanges !== null ? "Målt indblæsning" : "Beregnet"}</small></div>
    </section>

    <table className="report-table">
      <thead>
        <tr><th rowSpan={2}>Rum</th><th rowSpan={2}>Type</th><th rowSpan={2}>m²</th><th colSpan={4}>Indblæsning (l/s)</th><th colSpan={4}>Udsugning (l/s)</th></tr>
        <tr><th>Krav</th><th>Målt</th><th>Ventil</th><th>Afv.</th><th>Krav</th><th>Målt</th><th>Ventil</th><th>Afv.</th></tr>
      </thead>
      <tbody>{report.rooms.map((r, i) => <tr key={i}>
        <td><strong>{r.name}</strong>{r.note && <small>{r.note}</small>}</td>
        <td>{ROOM_TYPES[r.type]?.label ?? r.type}</td>
        <td>{fmt(r.area)}</td>
        <Cell on={r.supply} design={r.designSupply} measured={r.measured_supply} valve={r.valve_supply} dev={r.supplyDeviation} status={r.supplyStatus}/>
        <Cell on={r.extract} design={r.designExtract} measured={r.measured_extract} valve={r.valve_extract} dev={r.extractDeviation} status={r.extractStatus}/>
      </tr>)}</tbody>
      <tfoot><tr>
        <td colSpan={3}><strong>I alt</strong></td>
        <td>{fmt(s.supplyTotal)}</td><td>{fmt(s.measuredSupply)}</td><td/><td/>
        <td>{fmt(s.extractTotal)}</td><td>{fmt(s.measuredExtract)}</td><td/><td/>
      </tr></tfoot>
    </table>

    {report.warnings.length > 0 && <ul className="report-warnings">{report.warnings.map(w => <li key={w}>{w}</li>)}</ul>}
    {m.notes && <section className="report-notes"><h3>Bemærkninger</h3><p>{m.notes}</p></section>}

    <p className="report-basis">Krav efter BR18 §447: udeluft mindst 0,3 l/s pr. m² opvarmet etageareal; udsugning mindst 20 l/s fra køkken, 15 l/s fra bad og 10 l/s fra separat toilet og bryggers. Indblæsningen er balanceret mod udsugningen med {fmt(s.extractExcess ?? 0, 0)} % mere udsugning end indblæsning. Afvigelse inden for ±{TOLERANCE_OK} % er godkendt, ±{TOLERANCE_WARN} % giver en bemærkning.</p>

    <footer className="report-signatures">
      <div><span/>Tekniker{m.technician ? `: ${m.technician}` : ""}</div>
      <div><span/>Ejer{m.owner ? `: ${m.owner}` : ""}</div>
    </footer>
  </article>;
}
