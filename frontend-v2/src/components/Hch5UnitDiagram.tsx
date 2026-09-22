import type { CSSProperties } from "react";

type Num = number | null;

export interface Hch5UnitDiagramProps {
  outdoor: Num;
  extract: Num;
  exhaust: Num;
  beforeHeater: Num;
  afterHeater: Num;
  room: Num;
  frost: Num;
  flowWater: Num;
  returnWater: Num;
  supplyRpm: Num;
  extractRpm: Num;
  supplyPercent: Num;
  extractPercent: Num;
  bypassActual: boolean;
  bypassRequest: string;
  heating: boolean;
  recovery: number | null;
}

function fmt(value: Num, suffix = "°C") {
  if (value === null) return "—";
  return `${value.toLocaleString("da-DK", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}${suffix}`;
}

function int(value: Num) {
  return value === null ? "—" : Math.round(value).toLocaleString("da-DK");
}

// Both normal-mode paths are anchored through the exchanger's exact
// rotation center (550 295) so they cross it as a clean X, matching the
// physical cross-flow through the heat exchanger.
const NORMAL_SUPPLY = "M76 182 H260 C305 182 332 196 360 222 L550 295 L740 368 C768 379 795 391 838 400 H1018";
const NORMAL_EXTRACT = "M1018 182 H840 C795 182 768 196 740 222 L550 295 L360 368 C332 379 305 391 262 400 H76";
const BYPASS_SUPPLY = "M76 182 H267 C310 182 337 201 337 239 V333 C337 373 366 400 410 400 H1018";
const BYPASS_EXTRACT = "M1018 182 H816 C774 182 746 202 746 240 V318 C746 353 718 374 678 374 H407 C362 374 333 386 303 400 H76";

function Fan({ x, y, rpm, label }: { x: number; y: number; rpm: Num; label: string }) {
  const speed = rpm && rpm > 0 ? Math.max(3.2, 4.6 - rpm / 2200) : 0;
  return (
    <g className={`hch-fan${speed ? " running" : " stopped"}`} transform={`translate(${x} ${y})`}>
      <circle className="hch-fan-ring" r="42" />
      <circle className="hch-fan-hub" r="11" />
      <g className="hch-fan-rotor" style={{ "--fan-speed": speed ? `${speed}s` : "0s" } as CSSProperties}>
        <path d="M0-31c23 0 32 14 18 28C9 6 0 5 0-31Z" />
        <path d="M27 13c-11 21-29 20-34 1 7-12 15-13 34-1Z" />
        <path d="M-27 13c-11-21 0-36 19-29 8 12 4 20-19 29Z" />
      </g>
      <text className="hch-part-label" x="0" y="62" textAnchor="middle">{label}</text>
    </g>
  );
}

function Filter({ x, y, label }: { x: number; y: number; label: string }) {
  return (
    <g className="hch-filter" transform={`translate(${x} ${y})`}>
      <rect x="-22" y="-58" width="44" height="116" rx="5" />
      {[-14, -7, 0, 7, 14].map(offset => <path key={offset} d={`M${offset - 8} -49 L${offset + 8} 49`} />)}
      <text className="hch-part-label" x="0" y="78" textAnchor="middle">{label}</text>
    </g>
  );
}

function TempBadge({ x, y, title, value, align = "start", tone = "neutral" }: {
  x: number; y: number; title: string; value: string; align?: "start" | "end"; tone?: string;
}) {
  const width = 118;
  const left = align === "end" ? x - width : x;
  return (
    <g className={`hch-temp-badge tone-${tone}`} transform={`translate(${left} ${y})`}>
      <rect width={width} height="62" rx="13" />
      <text className="hch-temp-title" x="13" y="22">{title}</text>
      <text className="hch-temp-value" x="13" y="47">{value}</text>
    </g>
  );
}

function SensorPin({ x, y, label, value }: { x: number; y: number; label: string; value: string }) {
  return (
    <g className="hch-sensor-pin" transform={`translate(${x} ${y})`}>
      <circle r="5" />
      <line x1="0" y1="0" x2="0" y2="-23" />
      <rect x="-42" y="-57" width="84" height="30" rx="8" />
      <text x="0" y="-45" textAnchor="middle">{label}</text>
      <text className="pin-value" x="0" y="-34" textAnchor="middle">{value}</text>
    </g>
  );
}

export function Hch5UnitDiagram(props: Hch5UnitDiagramProps) {
  const {
    outdoor, extract, exhaust, beforeHeater, afterHeater, room, frost, flowWater, returnWater,
    supplyRpm, extractRpm, supplyPercent, extractPercent, bypassActual, bypassRequest, heating, recovery,
  } = props;
  const supplyPath = bypassActual ? BYPASS_SUPPLY : NORMAL_SUPPLY;
  const extractPath = bypassActual ? BYPASS_EXTRACT : NORMAL_EXTRACT;
  const supplySpeed = supplyRpm && supplyRpm > 0 ? Math.max(5, 7.5 - supplyRpm / 1400) : 0;
  const extractSpeed = extractRpm && extractRpm > 0 ? Math.max(5, 7.5 - extractRpm / 1400) : 0;

  return (
    <div className={`hch5-visual${bypassActual ? " is-bypass" : " is-recovery"}`}>
      <svg viewBox="0 0 1100 560" role="img" aria-label="Detaljeret HCH5 luftstrøm med varmeveksler, filtre, bypass og eftervarme">
        <defs>
          <linearGradient id="metalFace" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor="#52636e" /><stop offset=".38" stopColor="#263741" /><stop offset="1" stopColor="#14232d" />
          </linearGradient>
          <linearGradient id="metalTop" x1="0" x2="1">
            <stop offset="0" stopColor="#75838b" /><stop offset=".48" stopColor="#3c4d57" /><stop offset="1" stopColor="#25343d" />
          </linearGradient>
          <linearGradient id="metalEdge" x1="0" x2="1">
            <stop offset="0" stopColor="#a0abb1" /><stop offset=".5" stopColor="#4c5d67" /><stop offset="1" stopColor="#1b2a33" />
          </linearGradient>
          <linearGradient id="exchangerMetal" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor="#819099" /><stop offset=".55" stopColor="#45565f" /><stop offset="1" stopColor="#24343d" />
          </linearGradient>
          <linearGradient id="supplyFlow" x1="0" x2="1"><stop offset="0" stopColor="#46bfff"/><stop offset=".55" stopColor="#69d6bd"/><stop offset="1" stopColor="#55e39b"/></linearGradient>
          <linearGradient id="extractFlow" x1="1" x2="0"><stop offset="0" stopColor="#ff6969"/><stop offset=".48" stopColor="#ffae55"/><stop offset="1" stopColor="#ff923f"/></linearGradient>
          <filter id="airGlow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="1.6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
          <filter id="fogBlur" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="13" /></filter>
          <filter id="fogBlurSoft" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="22" /></filter>
          <filter id="unitShadow" x="-20%" y="-30%" width="150%" height="180%"><feDropShadow dx="0" dy="18" stdDeviation="18" floodColor="#000" floodOpacity=".42"/></filter>
          <pattern id="filterMesh" width="8" height="8" patternUnits="userSpaceOnUse"><path d="M0 8 L8 0 M-2 2 L2 -2 M6 10 L10 6" stroke="#9db0ba" strokeWidth="1" opacity=".55"/></pattern>
          <marker id="arrowSupply" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0 0 L8 3 L0 6Z" fill="#5fe0a0"/></marker>
          <marker id="arrowExtract" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0 0 L8 3 L0 6Z" fill="#ff8e46"/></marker>
          <linearGradient id="fogFadeGradient" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0" stopColor="#fff" stopOpacity="0" />
            <stop offset=".09" stopColor="#fff" stopOpacity="1" />
            <stop offset=".91" stopColor="#fff" stopOpacity="1" />
            <stop offset="1" stopColor="#fff" stopOpacity="0" />
          </linearGradient>
          <mask id="fogFadeMask"><rect x="0" y="0" width="1100" height="560" fill="url(#fogFadeGradient)" /></mask>
        </defs>

        <ellipse className="hch-floor-shadow" cx="550" cy="487" rx="365" ry="35" />

        <g filter="url(#unitShadow)">
          <polygon className="hch-top-panel" points="188,122 256,78 877,78 931,122" fill="url(#metalTop)" />
          <rect className="hch-cabinet" x="188" y="122" width="743" height="326" rx="7" fill="url(#metalFace)" />
          <polygon className="hch-side-panel" points="931,122 963,140 963,421 931,448" fill="url(#metalEdge)" />
          <rect className="hch-inner" x="210" y="141" width="699" height="286" rx="4" />
          <path className="hch-frame" d="M247 141V427 M410 141V427 M706 141V427 M864 141V427 M210 277H909" />

          <Filter x={254} y={194} label="Filter · udeluft" />
          <Filter x={851} y={194} label="Filter · udsugning" />

          <Fan x={349} y={201} rpm={supplyRpm} label="Tilluft" />
          <Fan x={755} y={201} rpm={extractRpm} label="Fraluft" />

          <g className={`hch-exchanger${bypassActual ? " bypassed" : ""}`} transform="translate(550 295) rotate(45)">
            <rect x="-100" y="-100" width="200" height="200" rx="14" fill="url(#exchangerMetal)" />
            {[-66,-44,-22,0,22,44,66].map(offset => <path key={offset} d={`M-76 ${offset} H76`} />)}
          </g>
          <text className="hch-exchanger-title" x="550" y="292" textAnchor="middle">Varmeveksler</text>
          <text className="hch-recovery" x="550" y="318" textAnchor="middle">{bypassActual ? "BYPASS" : recovery === null ? "—" : `${recovery}%`}</text>

          <g className={`hch-bypass ${bypassActual ? "open" : "closed"}`} transform="translate(550 142)">
            <rect x="-72" y="-17" width="144" height="34" rx="8" />
            <path className="bypass-rail" d="M-48 0 H48" />
            <rect className="bypass-blade" x="-30" y="-5" width="60" height="10" rx="4" transform={bypassActual ? "rotate(0)" : "rotate(62)"} />
            <text x="0" y="-28" textAnchor="middle">Bypass · {bypassActual ? "åben" : "lukket"}</text>
          </g>

          <g className={`hch-coil${heating ? " active" : ""}`} transform="translate(787 362)">
            <rect x="-33" y="-66" width="66" height="132" rx="8" />
            {[-21,-10,1,12,23].map(offset => <path key={offset} className="coil-pipe" d={`M${offset} -52 C${offset-10} -32 ${offset+10} -10 ${offset} 10 C${offset-10} 30 ${offset+10} 44 ${offset} 55`} />)}
            <circle className="water-port" cx="-21" cy="-73" r="5"/><circle className="water-port" cx="21" cy="73" r="5"/>
            <text className="hch-part-label" x="0" y="87" textAnchor="middle">Eftervarme · vandflade</text>
          </g>

          <rect className="hch-service-box" x="263" y="306" width="104" height="83" rx="9" />
          <path className="service-lines" d="M277 323 H350 M277 338 H336 M277 353 H345 M277 368 H326" />
          <text className="hch-part-label" x="315" y="405" textAnchor="middle">Elektronik</text>
        </g>

        <g className="hch-port hch-port-outdoor"><rect x="135" y="152" width="74" height="60" rx="18"/><path d="M135 182 H82" markerEnd="url(#arrowSupply)" /></g>
        <g className="hch-port hch-port-exhaust"><rect x="135" y="370" width="74" height="60" rx="18"/><path d="M135 400 H82" markerEnd="url(#arrowExtract)" /></g>
        <g className="hch-port hch-port-extract"><rect x="912" y="152" width="74" height="60" rx="18"/><path d="M1028 182 H986" markerEnd="url(#arrowExtract)" /></g>
        <g className="hch-port hch-port-supply"><rect x="912" y="370" width="74" height="60" rx="18"/><path d="M986 400 H1028" markerEnd="url(#arrowSupply)" /></g>

        <g className="hch-fog-group" filter="url(#fogBlur)" mask="url(#fogFadeMask)">
          <path className="hch-fog hch-fog-supply hch-fog-a" d={supplyPath} style={{ "--flow-speed": supplySpeed ? `${supplySpeed}s` : "0s" } as CSSProperties}/>
          <path className="hch-fog hch-fog-supply hch-fog-b" d={supplyPath} style={{ "--flow-speed": supplySpeed ? `${supplySpeed * 1.35}s` : "0s" } as CSSProperties}/>
          <path className="hch-fog hch-fog-extract hch-fog-a" d={extractPath} style={{ "--flow-speed": extractSpeed ? `${extractSpeed}s` : "0s" } as CSSProperties}/>
          <path className="hch-fog hch-fog-extract hch-fog-b" d={extractPath} style={{ "--flow-speed": extractSpeed ? `${extractSpeed * 1.35}s` : "0s" } as CSSProperties}/>
        </g>
        <g className="hch-fog-group soft" filter="url(#fogBlurSoft)" mask="url(#fogFadeMask)">
          <path className="hch-fog-wash hch-fog-supply" d={supplyPath} style={{ "--flow-speed": supplySpeed ? `${supplySpeed * 1.7}s` : "0s" } as CSSProperties}/>
          <path className="hch-fog-wash hch-fog-extract" d={extractPath} style={{ "--flow-speed": extractSpeed ? `${extractSpeed * 1.7}s` : "0s" } as CSSProperties}/>
        </g>
        <path className="hch-airflow-guide hch-supply-flow" d={supplyPath} style={{ "--flow-speed": supplySpeed ? `${supplySpeed}s` : "0s" } as CSSProperties}/>
        <path className="hch-airflow-guide hch-extract-flow" d={extractPath} style={{ "--flow-speed": extractSpeed ? `${extractSpeed}s` : "0s" } as CSSProperties}/>

        <TempBadge x={10} y={115} title="Udeluft · T1" value={fmt(outdoor)} tone="cold" />
        <TempBadge x={10} y={426} title="Afkast · T4" value={fmt(exhaust)} tone="warm" />
        <TempBadge x={1090} y={115} title="Udsugning · T3" value={fmt(extract)} align="end" tone="warm" />
        <TempBadge x={1090} y={426} title="Indblæsning · T2AH" value={fmt(afterHeater)} align="end" tone="green" />

        <SensorPin x={705} y={371} label="T2 før flade" value={fmt(beforeHeater, "°")} />
        <SensorPin x={846} y={371} label="T2AH" value={fmt(afterHeater, "°")} />
        <SensorPin x={786} y={301} label="Frost" value={fmt(frost, "°")} />
        <SensorPin x={612} y={119} label="T5 rum" value={fmt(room, "°")} />

        <g className="hch-water-callout" transform="translate(690 474)">
          <rect width="218" height="55" rx="12" />
          <text x="14" y="21">Eftervarmevand</text>
          <text className="water-value" x="14" y="41">Fremløb {fmt(flowWater)} · Retur {fmt(returnWater)}</text>
        </g>

        <g className="hch-bypass-callout" transform="translate(467 18)">
          <rect width="166" height="53" rx="12" />
          <text x="83" y="20" textAnchor="middle">Bypass-spjæld</text>
          <text className="bypass-state" x="83" y="40" textAnchor="middle">{bypassActual ? "Åben" : "Lukket"} · ønske {bypassRequest === "on" ? "On" : "Auto"}</text>
        </g>
      </svg>

      <div className="unit-readback-row">
        <div className="unit-readback"><span className="readback-icon fan"/><div><small>Tilluft ventilator</small><strong>{int(supplyRpm)} RPM</strong><em>{int(supplyPercent)}%</em></div></div>
        <div className="unit-readback"><span className="readback-icon fan"/><div><small>Fraluft ventilator</small><strong>{int(extractRpm)} RPM</strong><em>{int(extractPercent)}%</em></div></div>
        <div className="unit-readback"><span className={`readback-icon damper ${bypassActual ? "active" : ""}`}/><div><small>Bypass-spjæld</small><strong>{bypassActual ? "Åbent" : "Lukket"}</strong><em>Ønske: {bypassRequest === "on" ? "On" : "Auto"}</em></div></div>
        <div className="unit-readback"><span className={`readback-icon heater ${heating ? "active" : ""}`}/><div><small>Eftervarme</small><strong>{heating ? "Aktiv" : "Ikke aktiv"}</strong><em>Styres automatisk efter setpunkt</em></div></div>
      </div>
    </div>
  );
}
