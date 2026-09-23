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
  /** RS485 traffic is flowing; animates data pulses along the Modbus cable. */
  busActive?: boolean;
}

function fmt(value: Num, suffix = "°C") {
  if (value === null) return "—";
  return `${value.toLocaleString("da-DK", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}${suffix}`;
}
function int(value: Num) { return value === null ? "—" : Math.round(value).toLocaleString("da-DK"); }

// Oriented like the real HCH5 (see the port sticker on its core): outdoor
// air enters P1 top right and exhaust leaves P4 bottom right, where both fan
// motors sit; extract enters P3 top left and supply leaves P2 bottom left
// towards the external HAC1 coil. The core is an elongated hexagonal
// counter-flow exchanger: each stream enters one slanted end face and leaves
// the opposite one, so the two paths cross at its centre (520 262).
const NORMAL_SUPPLY = "M1247 205 H884 C850 205 812 210 770 212 Q715 212 660 216 L520 262 L380 308 Q342 322 322 345 Q308 365 278 365 H-238";
const NORMAL_EXTRACT = "M-238 205 H322 Q352 205 380 216 L520 262 L660 308 Q720 328 800 330 C842 331 852 365 884 365 H1247";
// The bypass damper sits on the lower (extract) fan motor, so in bypass the
// extract air leaves the core out and runs along the bottom channel beneath
// it, through the damper and the extract fan to exhaust. Supply always
// crosses the core.
const BYPASS_EXTRACT = "M-238 205 H268 Q294 205 294 231 V364 Q294 388 318 388 H772 Q800 388 800 360 V330 C842 331 852 365 884 365 H1247";
const CORE_POINTS = "420,178 620,178 700,262 620,346 420,346 340,262";

// Backward-curved impeller blade, drawn once and rotated around the hub.
const FAN_BLADE = "M-3.5 -12.5C2 -20 6 -27 15 -31C16.5 -27.5 14 -20.5 5 -12Z";
const FAN_BLADE_ANGLES = [0, 51.43, 102.86, 154.29, 205.71, 257.14, 308.57];

function Fan({ x, y, rpm, label, labelRight = false }: { x: number; y: number; rpm: Num; label: string; labelRight?: boolean }) {
  // One revolution per 0.9-2.4 s reads as a spinning impeller without the
  // blades strobing; the blur disc makes a running fan look like it moves.
  const speed = rpm && rpm > 0 ? Math.max(0.9, 2.4 - rpm / 1000) : 0;
  return <g className={`hch-fan${speed ? " running" : " stopped"}`} transform={`translate(${x} ${y})`}>
    <circle className="hch-fan-ring" r="42"/><circle className="hch-fan-shroud" r="36"/>
    <circle className="hch-fan-blur" r="33"/>
    <g className="hch-fan-rotor" style={{ "--fan-speed": speed ? `${speed}s` : "0s" } as CSSProperties}>
      {FAN_BLADE_ANGLES.map(angle => <path key={angle} d={FAN_BLADE} transform={`rotate(${angle})`}/>)}
    </g>
    <circle className="hch-fan-hub" r="11"/><circle className="hch-fan-cap" r="4"/>
    {labelRight
      ? <text className="hch-part-label" x="50" y="4">{label}</text>
      : <text className="hch-part-label" x="0" y="62" textAnchor="middle">{label}</text>}
  </g>;
}
function Filter({ x, y, label, angle = 0 }: { x: number; y: number; label: string; angle?: number }) {
  // The real filter cassettes stand slanted in the top corners.
  return <g className="hch-filter" transform={`translate(${x} ${y})`}>
    <g transform={`rotate(${angle})`}><rect x="-20" y="-52" width="40" height="104" rx="5"/>{[-13,-6,1,8].map(o => <path key={o} d={`M${o-6} -43 L${o+6} 43`}/>)}</g>
    <text className="hch-part-label" x="0" y="76" textAnchor="middle">{label}</text>
  </g>;
}
// Temperature "ports": semi-transparent duct-cap plates centred exactly on
// the flow centreline, so the fog visibly enters one side and continues out
// the other while the reading itself stays fully legible above the flow.
function TempPort({ cx, cy, title, value, tone = "neutral" }: { cx: number; cy: number; title: string; value: string; tone?: string }) {
  const width = 132, height = 66;
  return (
    <g className={`hch-temp-port tone-${tone}`} transform={`translate(${cx} ${cy})`}>
      <rect className="hch-temp-port-plate" x={-width / 2} y={-height / 2} width={width} height={height} rx="16" />
      <text className="hch-temp-port-title" x="0" y={-8} textAnchor="middle">{title}</text>
      <text className="hch-temp-port-value" x="0" y={17} textAnchor="middle">{value}</text>
    </g>
  );
}
function SensorPin({ x, y, label, value }: { x:number;y:number;label:string;value:string }) {
  return <g className="hch-sensor-pin" transform={`translate(${x} ${y})`}><circle r="5"/><line x1="0" y1="0" x2="0" y2="-23"/><rect x="-45" y="-57" width="90" height="30" rx="8"/><text x="0" y="-45" textAnchor="middle">{label}</text><text className="pin-value" x="0" y="-34" textAnchor="middle">{value}</text></g>;
}
// Duct stubs leave the cabinet sideways like on the real unit: a short
// horizontal pipe whose open end is seen edge-on as a narrow ellipse, not a
// round opening pointing at the viewer.
function DuctCollar({ x, y, side }: { x:number;y:number;side:"left"|"right" }) {
  const length = 44, radius = 36;
  const end = side === "left" ? x - length : x + length;
  return <g className="hch-duct-collar">
    <rect className="hch-duct-pipe" x={Math.min(x, end)} y={y - radius} width={length} height={radius * 2}/>
    <ellipse className="hch-duct-rim" cx={end} cy={y} rx="11" ry={radius}/>
    <ellipse className="hch-duct-inner" cx={end} cy={y} rx="6" ry={radius - 7}/>
  </g>;
}

// Wiring view: the unit's control board, the HAC1 afterheat controller and
// the Raspberry Pi share one RS485/Modbus RTU cable (unit = slave 1, HAC1 =
// slave 0x40, Pi = gateway). HAC1 wires its own T2AH and frost sensors and
// the water valve actuator.
function Rs485Wiring({ active }: { active: boolean }) {
  const bus = "M251 406 V496 M119 496 H600";
  return <g className={`hch-wiring${active ? " active" : ""}`}>
    <path className="hch-signal-wire" d="M2 476 V420 H-30 V371"/>
    <path className="hch-signal-wire" d="M112 476 V292 H63"/>
    <path className="hch-signal-wire" d="M23 476 V446"/>
    <path className="hch-bus-cable" d={bus}/><path className="hch-bus-core" d={bus}/>
    <rect className="hch-cable-gland" x="243" y="428" width="16" height="12" rx="3"/>
    <circle className="hch-bus-joint" cx="251" cy="496" r="4"/>
    <text className="hch-bus-label" x="425" y="487" textAnchor="middle">RS485 · Modbus RTU</text>
    <g className="hch-device hch-hac1-box"><rect className="device-body" x="-5" y="476" width="124" height="40" rx="9"/><text x="57" y="493" textAnchor="middle">HAC1 styring</text><text className="device-sub" x="57" y="507" textAnchor="middle">Modbus-slave 0x40</text></g>
    <g className="hch-device hch-pi">
      <rect className="pi-board" x="600" y="474" width="140" height="60" rx="7"/>
      {[0,1,2,3,4,5,6,7,8,9].map(i => <rect key={i} className="pi-gpio" x={622 + i * 9} y="478" width="5" height="5" rx="1"/>)}
      <rect className="pi-chip" x="610" y="492" width="24" height="24" rx="3"/>
      <text x="690" y="505" textAnchor="middle">Raspberry Pi</text><text className="device-sub" x="690" y="519" textAnchor="middle">Gateway · RS485</text>
    </g>
  </g>;
}

export function Hch5UnitDiagram(props:Hch5UnitDiagramProps) {
  const {outdoor,extract,exhaust,beforeHeater,afterHeater,room,frost,flowWater,returnWater,supplyRpm,extractRpm,supplyPercent,extractPercent,bypassActual,bypassRequest,heating,recovery,busActive=false}=props;
  const supplyPath=NORMAL_SUPPLY; const extractPath=bypassActual?BYPASS_EXTRACT:NORMAL_EXTRACT;
  const supplySpeed=supplyRpm&&supplyRpm>0?Math.max(8,11-supplyRpm/1400):0; const extractSpeed=extractRpm&&extractRpm>0?Math.max(8,11-extractRpm/1400):0;
  return <div className={`hch5-visual${bypassActual?" is-bypass":" is-recovery"}`}>
    <svg viewBox="-278 -8 1550 590" role="img" aria-label="HCH5 luftstrøm med intern bypass og ekstern eftervarme">
      <defs>
        <linearGradient id="metalFace" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stopColor="#596b76"/><stop offset=".4" stopColor="#263843"/><stop offset="1" stopColor="#14242e"/></linearGradient>
        <linearGradient id="metalTop" x1="1" x2="0"><stop offset="0" stopColor="#7b8991"/><stop offset=".48" stopColor="#40515b"/><stop offset="1" stopColor="#263640"/></linearGradient>
        <linearGradient id="exchangerMetal" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stopColor="#8e9aa1"/><stop offset=".55" stopColor="#455760"/><stop offset="1" stopColor="#25353e"/></linearGradient>
        {/* Supply runs right to left (outdoor blue to supply green), extract left to right. */}
        <linearGradient id="supplyFlow" x1="1" x2="0"><stop offset="0" stopColor="#4abfff"/><stop offset=".55" stopColor="#6bd2bc"/><stop offset="1" stopColor="#59dfa1"/></linearGradient>
        <linearGradient id="extractFlow" x1="0" x2="1"><stop offset="0" stopColor="#ff7171"/><stop offset=".5" stopColor="#ffae5a"/><stop offset="1" stopColor="#ff9345"/></linearGradient>
        <filter id="fogBlur" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="11"/></filter>
        <filter id="fogBlurSoft" x="-120%" y="-120%" width="340%" height="340%"><feGaussianBlur stdDeviation="20"/></filter>
        <filter id="unitShadow" x="-30%" y="-40%" width="170%" height="190%"><feDropShadow dx="0" dy="18" stdDeviation="18" floodColor="#000" floodOpacity=".42"/></filter>
        <pattern id="filterMesh" width="8" height="8" patternUnits="userSpaceOnUse"><path d="M0 8L8 0M-2 2L2-2M6 10L10 6" stroke="#aab9c1" strokeWidth="1" opacity=".6"/></pattern>
        <linearGradient id="fogFadeGradient" x1="0" x2="1"><stop offset="0" stopColor="#fff" stopOpacity="0"/><stop offset=".035" stopColor="#fff" stopOpacity="1"/><stop offset=".965" stopColor="#fff" stopOpacity="1"/><stop offset="1" stopColor="#fff" stopOpacity="0"/></linearGradient>
        {/* userSpaceOnUse: the default mask region is only 120% of the fog
            group's geometric height, which cut the wide blurred bands off
            flat at the top and bottom. */}
        <mask id="fogFadeMask" maskUnits="userSpaceOnUse" x="-278" y="-8" width="1550" height="590"><rect x="-278" y="-8" width="1550" height="590" fill="url(#fogFadeGradient)"/></mask>
        <clipPath id="coreClip"><polygon points={CORE_POINTS}/></clipPath>
        <linearGradient id="ductPipe" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#7b8991"/><stop offset=".45" stopColor="#40515b"/><stop offset="1" stopColor="#1a2a33"/></linearGradient>
        <radialGradient id="fanHub" cx=".38" cy=".35" r=".75"><stop offset="0" stopColor="#c9d8e0"/><stop offset=".5" stopColor="#5f7a8a"/><stop offset="1" stopColor="#1d303b"/></radialGradient>
        <radialGradient id="fanBlur"><stop offset=".3" stopColor="#68bcf0" stopOpacity="0"/><stop offset=".78" stopColor="#68bcf0" stopOpacity=".32"/><stop offset="1" stopColor="#a8ddff" stopOpacity=".08"/></radialGradient>
      </defs>
      <ellipse className="hch-floor-shadow" cx="560" cy="483" rx="380" ry="32"/>
      <g filter="url(#unitShadow)">
        <polygon className="hch-top-panel" points="188,132 242,88 860,88 924,132" fill="url(#metalTop)"/>
        <rect className="hch-cabinet" x="188" y="132" width="736" height="302" rx="8" fill="url(#metalFace)"/>
        <polygon className="hch-side-panel" points="188,132 157,150 157,407 188,434" fill="#253640"/>
        <rect className="hch-inner" x="211" y="151" width="692" height="263" rx="5"/>
        <Filter x={262} y={206} angle={24} label="Filter · udsugning"/><Filter x={866} y={204} angle={-24} label="Filter · udeluft"/>
        <rect className={`hch-bypass-channel${bypassActual?" open":""}`} x="300" y="371" width="482" height="34" rx="12"/>
        <text className="hch-channel-label" x="541" y="393" textAnchor="middle">Bypass-kanal</text>
        <g className={`hch-exchanger${bypassActual?" bypassed":""}`}>
          <polygon points={CORE_POINTS} fill="url(#exchangerMetal)"/>
          <g clipPath="url(#coreClip)">{[196,214,232,250,268,286,304,322].map(o=><path key={o} d={`M340 ${o}H700`}/>)}</g>
        </g>
        <text className="hch-exchanger-title" x="520" y="258" textAnchor="middle">Varmeveksler</text><text className="hch-recovery" x="520" y="284" textAnchor="middle">{bypassActual?"BYPASS":recovery===null?"—":`${recovery}%`}</text>
        {[["P3",378,196],["P1",662,196],["P2",378,336],["P4",662,336]].map(([port,x,y])=><text key={port} className="hch-core-port" x={x} y={y} textAnchor="middle">{port}</text>)}
        <Fan x={770} y={212} rpm={supplyRpm} label="Tilluft"/><Fan x={800} y={330} rpm={extractRpm} label="Fraluft" labelRight/>
        {/* Bypass damper sits on the lower (extract) fan motor, orange actuator at the bottom. */}
        <g className={`hch-bypass ${bypassActual?"open":"closed"}`} transform="translate(800 386)">
          <rect className="damper-frame" x="-17" y="-12" width="34" height="24" rx="5"/>
          <rect className="bypass-blade" x="-12" y="-3" width="24" height="6" rx="3" transform={bypassActual?"rotate(0)":"rotate(90)"}/>
          <rect className="bypass-actuator" x="-15" y="13" width="30" height="11" rx="4"/>
        </g>
        <rect className="hch-service-box" x="216" y="378" width="70" height="28" rx="7"/><text className="hch-part-label" x="251" y="396" textAnchor="middle">Styring</text>
      </g>
      <DuctCollar x={924} y={205} side="right"/><DuctCollar x={924} y={365} side="right"/><DuctCollar x={164} y={205} side="left"/><DuctCollar x={164} y={365} side="left"/>
      <g className={`hch-external-coil${heating?" active":""}`} transform="translate(57 365)"><rect className="coil-case" x="-48" y="-68" width="96" height="136" rx="12"/><rect className="coil-duct" x="-61" y="-48" width="122" height="96" rx="20"/>{[-27,-14,-1,12,25].map(o=><path key={o} className="coil-pipe" d={`M${o} -42C${o-12}-24 ${o+12}-8 ${o}10C${o-12}27 ${o+12}36 ${o}43`}/>) }<circle className="water-port" cx="34" cy="-75" r="5"/><circle className="water-port" cx="-34" cy="75" r="5"/><text className="hch-part-label" x="0" y="91" textAnchor="middle">Ekstern eftervarme · HAC1</text></g>
      <Rs485Wiring active={busActive}/>
      <g className="hch-fog-group" filter="url(#fogBlur)" mask="url(#fogFadeMask)"><path className="hch-fog hch-fog-supply hch-fog-a" d={supplyPath} style={{"--flow-speed":supplySpeed?`${supplySpeed}s`:"0s"} as CSSProperties}/><path className="hch-fog hch-fog-supply hch-fog-b" d={supplyPath} style={{"--flow-speed":supplySpeed?`${supplySpeed*1.35}s`:"0s"} as CSSProperties}/><path className="hch-fog hch-fog-extract hch-fog-a" d={extractPath} style={{"--flow-speed":extractSpeed?`${extractSpeed}s`:"0s"} as CSSProperties}/><path className="hch-fog hch-fog-extract hch-fog-b" d={extractPath} style={{"--flow-speed":extractSpeed?`${extractSpeed*1.35}s`:"0s"} as CSSProperties}/></g>
      <g className="hch-fog-group soft" filter="url(#fogBlurSoft)" mask="url(#fogFadeMask)"><path className="hch-fog-wash hch-fog-supply" d={supplyPath} style={{"--flow-speed":supplySpeed?`${supplySpeed*1.7}s`:"0s"} as CSSProperties}/><path className="hch-fog-wash hch-fog-extract" d={extractPath} style={{"--flow-speed":extractSpeed?`${extractSpeed*1.7}s`:"0s"} as CSSProperties}/></g>
      <path className="hch-airflow-guide hch-supply-flow" d={supplyPath} style={{"--flow-speed":supplySpeed?`${supplySpeed}s`:"0s"} as CSSProperties}/><path className="hch-airflow-guide hch-extract-flow" d={extractPath} style={{"--flow-speed":extractSpeed?`${extractSpeed}s`:"0s"} as CSSProperties}/>
      <TempPort cx={1202} cy={205} title="Udeluft · T1" value={fmt(outdoor)} tone="cold"/>
      <TempPort cx={1202} cy={365} title="Afkast · T4" value={fmt(exhaust)} tone="warm"/>
      <TempPort cx={-193} cy={205} title="Udsugning · T3" value={fmt(extract)} tone="warm"/>
      <TempPort cx={-193} cy={365} title="Indblæsning · T2AH" value={fmt(afterHeater)} tone="green"/>
      <SensorPin x={144} y={365} label="T2 før flade" value={fmt(beforeHeater,"°")}/><SensorPin x={-30} y={365} label="T2AH" value={fmt(afterHeater,"°")}/><SensorPin x={57} y={292} label="Frost" value={fmt(frost,"°")}/><SensorPin x={502} y={126} label="T5 rum" value={fmt(room,"°")}/>
      <g className="hch-water-callout" transform="translate(-258 476)"><rect width="245" height="55" rx="12"/><text x="14" y="21">Eftervarmevand · ekstern flade</text><text className="water-value" x="14" y="41">Fremløb {fmt(flowWater)} · Retur {fmt(returnWater)}</text></g>
      <g className="hch-bypass-callout" transform="translate(772 446)"><rect width="166" height="53" rx="12"/><text x="83" y="20" textAnchor="middle">Bypass-spjæld</text><text className="bypass-state" x="83" y="40" textAnchor="middle">{bypassActual?"Åben":"Lukket"} · ønske {bypassRequest.toLowerCase()==="on"?"On":"Auto"}</text></g>
    </svg>
    <div className="unit-readback-row"><div className="unit-readback"><span className="readback-icon fan"/><div><small>Tilluft ventilator</small><strong>{int(supplyRpm)} RPM</strong><em>{int(supplyPercent)}%</em></div></div><div className="unit-readback"><span className="readback-icon fan"/><div><small>Fraluft ventilator</small><strong>{int(extractRpm)} RPM</strong><em>{int(extractPercent)}%</em></div></div><div className="unit-readback"><span className={`readback-icon damper ${bypassActual?"active":""}`}/><div><small>Bypass-spjæld</small><strong>{bypassActual?"Åbent":"Lukket"}</strong><em>Ønske: {bypassRequest.toLowerCase()==="on"?"On":"Auto"}</em></div></div><div className="unit-readback"><span className={`readback-icon heater ${heating?"active":""}`}/><div><small>Ekstern eftervarme</small><strong>{heating?"Aktiv":"Ikke aktiv"}</strong><em>Kun setpunkt styres</em></div></div></div>
  </div>;
}
