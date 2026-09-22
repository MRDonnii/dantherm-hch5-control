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
function int(value: Num) { return value === null ? "—" : Math.round(value).toLocaleString("da-DK"); }

// Duct centres are deliberately pulled towards the middle of the cabinet.
// Normal paths meet the exchanger faces with short, rounded duct elbows.
const NORMAL_SUPPLY = "M-45 205 H328 Q350 205 369 222 L550 295 L729 350 Q750 365 776 365 H1260";
const NORMAL_EXTRACT = "M1260 205 H776 Q750 205 730 222 L550 295 L370 350 Q350 365 325 365 H-45";
// Only supply bypasses the core. Extract continues through the exchanger.
const BYPASS_SUPPLY = "M-45 205 H326 Q356 205 356 178 V143 Q356 118 382 118 H714 Q744 118 744 145 V326 Q744 365 782 365 H1260";

function Fan({ x, y, rpm, label }: { x: number; y: number; rpm: Num; label: string }) {
  const speed = rpm && rpm > 0 ? Math.max(4.5, 6.5 - rpm / 2200) : 0;
  return <g className={`hch-fan${speed ? " running" : " stopped"}`} transform={`translate(${x} ${y})`}>
    <circle className="hch-fan-ring" r="42"/><circle className="hch-fan-hub" r="12"/>
    <g className="hch-fan-rotor" style={{ "--fan-speed": speed ? `${speed}s` : "0s" } as CSSProperties}>
      <path d="M0-30c22 0 31 14 18 28C9 6 1 4 0-30Z"/><path d="M27 13c-11 20-28 20-34 2 7-13 15-14 34-2Z"/><path d="M-27 13c-11-20 0-35 19-29 8 12 4 20-19 29Z"/>
    </g><text className="hch-part-label" x="0" y="62" textAnchor="middle">{label}</text>
  </g>;
}
function Filter({ x, y, label }: { x: number; y: number; label: string }) {
  return <g className="hch-filter" transform={`translate(${x} ${y})`}>
    <rect x="-24" y="-60" width="48" height="120" rx="5"/>{[-16,-8,0,8,16].map(o => <path key={o} d={`M${o-8} -50 L${o+8} 50`}/>)}
    <text className="hch-part-label" x="0" y="80" textAnchor="middle">{label}</text>
  </g>;
}
function TempBadge({ x, y, title, value, align = "start", tone = "neutral" }: { x:number;y:number;title:string;value:string;align?:"start"|"end";tone?:string }) {
  const width=118; const left=align==="end"?x-width:x;
  return <g className={`hch-temp-badge tone-${tone}`} transform={`translate(${left} ${y})`}><rect width={width} height="62" rx="13"/><text className="hch-temp-title" x="13" y="22">{title}</text><text className="hch-temp-value" x="13" y="47">{value}</text></g>;
}
function SensorPin({ x, y, label, value }: { x:number;y:number;label:string;value:string }) {
  return <g className="hch-sensor-pin" transform={`translate(${x} ${y})`}><circle r="5"/><line x1="0" y1="0" x2="0" y2="-23"/><rect x="-45" y="-57" width="90" height="30" rx="8"/><text x="0" y="-45" textAnchor="middle">{label}</text><text className="pin-value" x="0" y="-34" textAnchor="middle">{value}</text></g>;
}
function DuctCollar({ x, y, side }: { x:number;y:number;side:"left"|"right" }) {
  const start = side === "left" ? x - 64 : x + 64;
  const end = side === "left" ? x - 20 : x + 20;
  return <g className="hch-duct-collar"><ellipse cx={x} cy={y} rx="43" ry="38"/><ellipse className="hch-duct-inner" cx={x} cy={y} rx="32" ry="28"/><path d={`M${start} ${y} H${end}`}/></g>;
}

export function Hch5UnitDiagram(props:Hch5UnitDiagramProps) {
  const {outdoor,extract,exhaust,beforeHeater,afterHeater,room,frost,flowWater,returnWater,supplyRpm,extractRpm,supplyPercent,extractPercent,bypassActual,bypassRequest,heating,recovery}=props;
  const supplyPath=bypassActual?BYPASS_SUPPLY:NORMAL_SUPPLY; const extractPath=NORMAL_EXTRACT;
  const supplySpeed=supplyRpm&&supplyRpm>0?Math.max(8,11-supplyRpm/1400):0; const extractSpeed=extractRpm&&extractRpm>0?Math.max(8,11-extractRpm/1400):0;
  return <div className={`hch5-visual${bypassActual?" is-bypass":" is-recovery"}`}>
    <svg viewBox="-70 -8 1370 590" role="img" aria-label="HCH5 luftstrøm med intern bypass og ekstern eftervarme">
      <defs>
        <linearGradient id="metalFace" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stopColor="#596b76"/><stop offset=".4" stopColor="#263843"/><stop offset="1" stopColor="#14242e"/></linearGradient>
        <linearGradient id="metalTop" x1="0" x2="1"><stop offset="0" stopColor="#7b8991"/><stop offset=".48" stopColor="#40515b"/><stop offset="1" stopColor="#263640"/></linearGradient>
        <linearGradient id="exchangerMetal" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stopColor="#8e9aa1"/><stop offset=".55" stopColor="#455760"/><stop offset="1" stopColor="#25353e"/></linearGradient>
        <linearGradient id="supplyFlow" x1="0" x2="1"><stop offset="0" stopColor="#4abfff"/><stop offset=".55" stopColor="#6bd2bc"/><stop offset="1" stopColor="#59dfa1"/></linearGradient>
        <linearGradient id="extractFlow" x1="1" x2="0"><stop offset="0" stopColor="#ff7171"/><stop offset=".5" stopColor="#ffae5a"/><stop offset="1" stopColor="#ff9345"/></linearGradient>
        <filter id="fogBlur" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="11"/></filter>
        <filter id="fogBlurSoft" x="-120%" y="-120%" width="340%" height="340%"><feGaussianBlur stdDeviation="20"/></filter>
        <filter id="unitShadow" x="-30%" y="-40%" width="170%" height="190%"><feDropShadow dx="0" dy="18" stdDeviation="18" floodColor="#000" floodOpacity=".42"/></filter>
        <pattern id="filterMesh" width="8" height="8" patternUnits="userSpaceOnUse"><path d="M0 8L8 0M-2 2L2-2M6 10L10 6" stroke="#aab9c1" strokeWidth="1" opacity=".6"/></pattern>
        <linearGradient id="fogFadeGradient" x1="0" x2="1"><stop offset="0" stopColor="#fff" stopOpacity="0"/><stop offset=".035" stopColor="#fff" stopOpacity="1"/><stop offset=".965" stopColor="#fff" stopOpacity="1"/><stop offset="1" stopColor="#fff" stopOpacity="0"/></linearGradient>
        <mask id="fogFadeMask"><rect x="-70" y="-8" width="1370" height="590" fill="url(#fogFadeGradient)"/></mask>
      </defs>
      <ellipse className="hch-floor-shadow" cx="552" cy="483" rx="380" ry="32"/>
      <g filter="url(#unitShadow)">
        <polygon className="hch-top-panel" points="188,132 252,88 870,88 924,132" fill="url(#metalTop)"/>
        <rect className="hch-cabinet" x="188" y="132" width="736" height="302" rx="8" fill="url(#metalFace)"/>
        <polygon className="hch-side-panel" points="924,132 955,150 955,407 924,434" fill="#253640"/>
        <rect className="hch-inner" x="211" y="151" width="692" height="263" rx="5"/>
        <path className="hch-frame" d="M257 151V414M410 151V414M696 151V414M851 151V414M211 283H903"/>
        <Filter x={260} y={207} label="Filter · udeluft"/><Filter x={845} y={207} label="Filter · udsugning"/>
        <Fan x={350} y={210} rpm={supplyRpm} label="Tilluft"/><Fan x={752} y={210} rpm={extractRpm} label="Fraluft"/>
        <g className={`hch-exchanger${bypassActual?" bypassed":""}`} transform="translate(550 295) rotate(45)"><rect x="-91" y="-91" width="182" height="182" rx="13" fill="url(#exchangerMetal)"/>{[-60,-40,-20,0,20,40,60].map(o=><path key={o} d={`M-69 ${o}H69`}/>)}</g>
        <text className="hch-exchanger-title" x="550" y="291" textAnchor="middle">Varmeveksler</text><text className="hch-recovery" x="550" y="317" textAnchor="middle">{bypassActual?"BYPASS":recovery===null?"—":`${recovery}%`}</text>
        <g className={`hch-bypass ${bypassActual?"open":"closed"}`} transform="translate(550 145)"><rect x="-72" y="-17" width="144" height="34" rx="8"/><path className="bypass-rail" d="M-48 0H48"/><rect className="bypass-blade" x="-30" y="-5" width="60" height="10" rx="4" transform={bypassActual?"rotate(0)":"rotate(62)"}/><text x="0" y="-28" textAnchor="middle">Bypass · {bypassActual?"åben":"lukket"}</text></g>
        <rect className="hch-service-box" x="269" y="310" width="100" height="72" rx="9"/><path className="service-lines" d="M282 325H354M282 339H341M282 353H350M282 367H331"/><text className="hch-part-label" x="319" y="400" textAnchor="middle">Elektronik</text>
      </g>
      <DuctCollar x={188} y={205} side="left"/><DuctCollar x={188} y={365} side="left"/><DuctCollar x={924} y={205} side="right"/><DuctCollar x={924} y={365} side="right"/>
      <g className={`hch-external-coil${heating?" active":""}`} transform="translate(1055 365)"><rect className="coil-case" x="-48" y="-68" width="96" height="136" rx="12"/><rect className="coil-duct" x="-61" y="-48" width="122" height="96" rx="20"/>{[-27,-14,-1,12,25].map(o=><path key={o} className="coil-pipe" d={`M${o} -42C${o-12}-24 ${o+12}-8 ${o}10C${o-12}27 ${o+12}36 ${o}43`}/>) }<circle className="water-port" cx="-34" cy="-75" r="5"/><circle className="water-port" cx="34" cy="75" r="5"/><text className="hch-part-label" x="0" y="91" textAnchor="middle">Ekstern eftervarme · HAC1</text></g>
      <g className="hch-fog-group" filter="url(#fogBlur)" mask="url(#fogFadeMask)"><path className="hch-fog hch-fog-supply hch-fog-a" d={supplyPath} style={{"--flow-speed":supplySpeed?`${supplySpeed}s`:"0s"} as CSSProperties}/><path className="hch-fog hch-fog-supply hch-fog-b" d={supplyPath} style={{"--flow-speed":supplySpeed?`${supplySpeed*1.35}s`:"0s"} as CSSProperties}/><path className="hch-fog hch-fog-extract hch-fog-a" d={extractPath} style={{"--flow-speed":extractSpeed?`${extractSpeed}s`:"0s"} as CSSProperties}/><path className="hch-fog hch-fog-extract hch-fog-b" d={extractPath} style={{"--flow-speed":extractSpeed?`${extractSpeed*1.35}s`:"0s"} as CSSProperties}/></g>
      <g className="hch-fog-group soft" filter="url(#fogBlurSoft)" mask="url(#fogFadeMask)"><path className="hch-fog-wash hch-fog-supply" d={supplyPath} style={{"--flow-speed":supplySpeed?`${supplySpeed*1.7}s`:"0s"} as CSSProperties}/><path className="hch-fog-wash hch-fog-extract" d={extractPath} style={{"--flow-speed":extractSpeed?`${extractSpeed*1.7}s`:"0s"} as CSSProperties}/></g>
      <path className="hch-airflow-guide hch-supply-flow" d={supplyPath} style={{"--flow-speed":supplySpeed?`${supplySpeed}s`:"0s"} as CSSProperties}/><path className="hch-airflow-guide hch-extract-flow" d={extractPath} style={{"--flow-speed":extractSpeed?`${extractSpeed}s`:"0s"} as CSSProperties}/>
      <TempBadge x={8} y={125} title="Udeluft · T1" value={fmt(outdoor)} tone="cold"/><TempBadge x={8} y={408} title="Afkast · T4" value={fmt(exhaust)} tone="warm"/><TempBadge x={1284} y={125} title="Udsugning · T3" value={fmt(extract)} align="end" tone="warm"/><TempBadge x={1284} y={408} title="Indblæsning · T2AH" value={fmt(afterHeater)} align="end" tone="green"/>
      <SensorPin x={968} y={365} label="T2 før flade" value={fmt(beforeHeater,"°")}/><SensorPin x={1142} y={365} label="T2AH" value={fmt(afterHeater,"°")}/><SensorPin x={1055} y={292} label="Frost" value={fmt(frost,"°")}/><SensorPin x={610} y={126} label="T5 rum" value={fmt(room,"°")}/>
      <g className="hch-water-callout" transform="translate(940 480)"><rect width="245" height="55" rx="12"/><text x="14" y="21">Eftervarmevand · ekstern flade</text><text className="water-value" x="14" y="41">Fremløb {fmt(flowWater)} · Retur {fmt(returnWater)}</text></g>
      <g className="hch-bypass-callout" transform="translate(467 20)"><rect width="166" height="53" rx="12"/><text x="83" y="20" textAnchor="middle">Bypass-spjæld</text><text className="bypass-state" x="83" y="40" textAnchor="middle">{bypassActual?"Åben":"Lukket"} · ønske {bypassRequest.toLowerCase()==="on"?"On":"Auto"}</text></g>
    </svg>
    <div className="unit-readback-row"><div className="unit-readback"><span className="readback-icon fan"/><div><small>Tilluft ventilator</small><strong>{int(supplyRpm)} RPM</strong><em>{int(supplyPercent)}%</em></div></div><div className="unit-readback"><span className="readback-icon fan"/><div><small>Fraluft ventilator</small><strong>{int(extractRpm)} RPM</strong><em>{int(extractPercent)}%</em></div></div><div className="unit-readback"><span className={`readback-icon damper ${bypassActual?"active":""}`}/><div><small>Bypass-spjæld</small><strong>{bypassActual?"Åbent":"Lukket"}</strong><em>Ønske: {bypassRequest.toLowerCase()==="on"?"On":"Auto"}</em></div></div><div className="unit-readback"><span className={`readback-icon heater ${heating?"active":""}`}/><div><small>Ekstern eftervarme</small><strong>{heating?"Aktiv":"Ikke aktiv"}</strong><em>Kun setpunkt styres</em></div></div></div>
  </div>;
}
