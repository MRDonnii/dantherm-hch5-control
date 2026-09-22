from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    if old not in content:
        raise RuntimeError(f"marker not found in {path}: {old[:100]!r}")
    write(path, content.replace(old, new, 1))


# ---------------------------------------------------------------------------
# Controller policy: bathroom-specific RH and deterministic night arbitration.
# ---------------------------------------------------------------------------
replace_once(
    "gateway/controller_core.py",
    '        "night_level": 2,\n',
    '        "night_level": 2,\n'
    '        "night_air_quality_max_level": 4,\n'
    '        "bathroom_rh_setpoint": 65.0,\n'
    '        "bathroom_rh_hysteresis": 5.0,\n'
    '        "bathroom_max_level": 4,\n',
)
replace_once(
    "gateway/controller_core.py",
    '("ha_requested_level", 3), ("night_level", 2),\n            ("vacation_level", 1), ("quick_boost_level", 6), ("cooling_level", 4),',
    '("ha_requested_level", 3), ("night_level", 2),\n'
    '            ("night_air_quality_max_level", 4), ("bathroom_max_level", 4),\n'
    '            ("vacation_level", 1), ("quick_boost_level", 6), ("cooling_level", 4),',
)
replace_once(
    "gateway/controller_core.py",
    '        for key, default, low, high in (\n            ("cooling_room_setpoint", 23.0, 18.0, 30.0),',
    '        for key, default, low, high in (\n'
    '            ("bathroom_rh_setpoint", 65.0, 35.0, 90.0),\n'
    '            ("bathroom_rh_hysteresis", 5.0, 1.0, 20.0),\n'
    '            ("cooling_room_setpoint", 23.0, 18.0, 30.0),',
)
replace_once(
    "gateway/controller_core.py",
    '                "schedule", "night_enabled", "night_start", "night_end", "night_level",\n',
    '                "schedule", "night_enabled", "night_start", "night_end", "night_level",\n'
    '                "night_air_quality_max_level", "bathroom_rh_setpoint",\n'
    '                "bathroom_rh_hysteresis", "bathroom_max_level",\n',
)
replace_once(
    "gateway/controller_core.py",
    '            for key in ("manual_level", "local_normal_level", "local_min_level", "local_max_level", "night_level", "vacation_level", "quick_boost_level", "cooling_level"):',
    '            for key in ("manual_level", "local_normal_level", "local_min_level", "local_max_level", "night_level", "night_air_quality_max_level", "bathroom_max_level", "vacation_level", "quick_boost_level", "cooling_level"):',
)
replace_once(
    "gateway/controller_core.py",
    '                ("rh_setpoint", 25.0, 80.0), ("rh_hysteresis", 1.0, 10.0),\n                ("auto_step_rh", 2.0, 20.0),',
    '                ("rh_setpoint", 25.0, 80.0), ("rh_hysteresis", 1.0, 10.0),\n'
    '                ("bathroom_rh_setpoint", 35.0, 90.0), ("bathroom_rh_hysteresis", 1.0, 20.0),\n'
    '                ("auto_step_rh", 2.0, 20.0),',
)
old_night = '''            if d.get("night_enabled") and _time_window_active(now, str(d["night_start"]), str(d["night_end"])):
                flags["night_active"] = True
                rh, co2 = self.measurements.get("rh"), self.measurements.get("co2")
                urgent_air = (
                    isinstance(rh, (int, float)) and rh > float(d["rh_setpoint"]) + float(d["rh_hysteresis"]) or
                    isinstance(co2, (int, float)) and co2 > int(d["co2_setpoint"]) + int(d["co2_hysteresis"])
                )
                if not urgent_air:
                    level = min(level, int(d["night_level"]))
                    source = "night"
                    reason = f"Natsænkning {d['night_start']}–{d['night_end']}"
                else:
                    reason = f"{reason}; nat men luftkvalitet har prioritet"
'''
new_night = '''            if d.get("night_enabled") and _time_window_active(now, str(d["night_start"]), str(d["night_end"])):
                flags["night_active"] = True
                rh, co2 = self.measurements.get("rh"), self.measurements.get("co2")
                local_urgent = (
                    isinstance(rh, (int, float)) and rh > float(d["rh_setpoint"]) + float(d["rh_hysteresis"]) or
                    isinstance(co2, (int, float)) and co2 > int(d["co2_setpoint"]) + int(d["co2_hysteresis"])
                )
                # Night mode is a final policy layer, not a competing writer. HA Smart
                # demand may lift the night level for air quality, but only to a
                # configurable ceiling. This prevents a humid bathroom from repeatedly
                # forcing full boost while night mode simultaneously tries to reduce it.
                ha_urgent = source == "ha_smart" and level > int(d["night_level"])
                if local_urgent or ha_urgent:
                    night_cap = max(int(d["night_level"]), int(d["night_air_quality_max_level"]))
                    if level > night_cap:
                        level = night_cap
                    source = "night_air_quality"
                    reason = f"{reason}; nat: luftkvalitet begrænset til trin {night_cap}"
                else:
                    level = min(level, int(d["night_level"]))
                    source = "night"
                    reason = f"Natsænkning {d['night_start']}–{d['night_end']}"
'''
replace_once("gateway/controller_core.py", old_night, new_night)

# ---------------------------------------------------------------------------
# Runtime: bathroom room policy + canonical T2 before external afterheater.
# ---------------------------------------------------------------------------
replace_once(
    "gateway/controller_runtime.py",
    '            values: dict[str, object] = {\n                "enabled": enabled,\n                "control": control,\n                "priority": priority,\n                "source": source.strip(),\n            }\n',
    '            room_type = str(raw_values.get("room_type", "auto")).strip().lower()\n'
    '            if room_type not in {"auto", "normal", "bathroom"}:\n'
    '                raise ControllerError(f"Ugyldig room_type for {name}")\n'
    '            values: dict[str, object] = {\n'
    '                "enabled": enabled,\n'
    '                "control": control,\n'
    '                "priority": priority,\n'
    '                "source": source.strip(),\n'
    '                "room_type": room_type,\n'
    '            }\n'
    '            if "rh_setpoint" in raw_values and raw_values.get("rh_setpoint") is not None:\n'
    '                values["rh_setpoint"] = self._measurement(raw_values, "rh_setpoint", 35, 90)\n'
    '            if "rh_hysteresis" in raw_values and raw_values.get("rh_hysteresis") is not None:\n'
    '                values["rh_hysteresis"] = self._measurement(raw_values, "rh_hysteresis", 1, 20)\n'
    '            if "max_level" in raw_values and raw_values.get("max_level") is not None:\n'
    '                try:\n'
    '                    max_level = int(raw_values["max_level"])\n'
    '                except (TypeError, ValueError) as error:\n'
    '                    raise ControllerError(f"max_level for {name} skal være 1..6") from error\n'
    '                if not 1 <= max_level <= 6:\n'
    '                    raise ControllerError(f"max_level for {name} skal være 1..6")\n'
    '                values["max_level"] = max_level\n',
)
content = read("gateway/controller_runtime.py")
pattern = re.compile(r"    def _derive_smart_decision\(.*?\n    def _derive_smart_demand", re.S)
replacement = '''    @staticmethod
    def _is_bathroom(name: str, values: dict[str, object]) -> bool:
        room_type = str(values.get("room_type", "auto")).lower()
        if room_type == "bathroom":
            return True
        if room_type == "normal":
            return False
        folded = name.casefold()
        return any(marker in folded for marker in ("bad", "bath", "shower", "brus"))

    def _derive_smart_decision(
        self, now: float | None = None
    ) -> tuple[int, str, str, str | None, str | None]:
        now = time.time() if now is None else now
        d = self.config.data
        rooms = self._rooms_with_unit_sensors()
        normal = int(d["local_normal_level"])
        candidates: list[tuple[int, int, float, str, str, str]] = []
        for name, values in rooms.items():
            if not values.get("enabled", True) or not values.get("control", True):
                continue
            priority = str(values.get("priority", "auto"))
            bathroom = self._is_bathroom(name, values)

            co2 = values.get("co2")
            if isinstance(co2, (int, float)):
                raw = self._metric_level(
                    float(co2), float(d["co2_setpoint"]), float(d["auto_step_co2"]),
                    float(d["co2_hysteresis"]), normal,
                )
                adjusted = self._priority_level(raw, priority)
                candidates.append((adjusted, raw, float(co2), name, "co2", f"CO2 {name} {float(co2):.0f} ({priority})"))

            humidity = values.get("humidity")
            if isinstance(humidity, (int, float)):
                rh_setpoint = float(values.get("rh_setpoint") or (d["bathroom_rh_setpoint"] if bathroom else d["rh_setpoint"]))
                rh_hysteresis = float(values.get("rh_hysteresis") or (d["bathroom_rh_hysteresis"] if bathroom else d["rh_hysteresis"]))
                raw = self._metric_level(
                    float(humidity), rh_setpoint, float(d["auto_step_rh"]), rh_hysteresis, normal,
                )
                adjusted = self._priority_level(raw, priority)
                if bathroom:
                    adjusted = min(adjusted, int(values.get("max_level") or d["bathroom_max_level"]))
                label = "Badeværelse RH" if bathroom else "RH"
                candidates.append((adjusted, raw, float(humidity), name, "humidity", f"{label} {name} {float(humidity):.1f}% / {rh_setpoint:.0f}% ({priority})"))

        for name, history in self._room_rh_history.items():
            values = rooms.get(name, {})
            if not values.get("enabled", True) or not values.get("control", True):
                continue
            fresh = [(ts, value) for ts, value in history if now - ts <= 600]
            if len(fresh) >= 2:
                rise = fresh[-1][1] - fresh[0][1]
                if rise >= 7.0:
                    raw = min(6, normal + 3 + int((rise - 7.0) // 5.0))
                    priority = str(values.get("priority", "auto"))
                    adjusted = self._priority_level(raw, priority)
                    if self._is_bathroom(name, values):
                        adjusted = min(adjusted, int(values.get("max_level") or d["bathroom_max_level"]))
                    candidates.append((
                        adjusted, raw, rise, name, "rh_rise",
                        f"RH rise {name} +{rise:.1f}%/10m ({priority})",
                    ))

        if not candidates:
            return normal, "normal", "No enabled control measurements", None, None
        adjusted, _raw, _value, room, metric, reason = max(candidates)
        adjusted = min(int(d["local_max_level"]), max(int(d["local_min_level"]), adjusted))
        demand = "low" if adjusted <= 2 else "normal" if adjusted == 3 else "high" if adjusted <= 5 else "boost"
        return adjusted, demand, reason, room, metric

    def _derive_smart_demand'''
content2, count = pattern.subn(replacement, content, count=1)
if count != 1:
    raise RuntimeError("could not replace _derive_smart_decision")
write("gateway/controller_runtime.py", content2)
replace_once(
    "gateway/controller_runtime.py",
    '        writes_allowed = self.master.writes_allowed()\n',
    '        writes_allowed = self.master.writes_allowed()\n'
    '        sample_at = self._first(self.gateway_state, "temperature_sample_monotonic")\n'
    '        sample_age = None\n'
    '        if isinstance(sample_at, (int, float)):\n'
    '            sample_age = max(0.0, time.monotonic() - float(sample_at))\n'
    '        before_heater = self._first(self.gateway_state, "supply_temperature", "supply_temp")\n'
    '        if sample_age is not None and sample_age > 45:\n'
    '            before_heater = None\n'
    '        before_source = (\n'
    '            str(self.gateway_state.get("temperature_source") or "canonical_t2")\n'
    '            if self.gateway_state.get("supply_temperature") is not None\n'
    '            else "unit_t2_legacy"\n'
    '        )\n',
)
replace_once(
    "gateway/controller_runtime.py",
    '            "actual_supply_before_heater_temperature": self._first(self.gateway_state, "supply_temp"),\n',
    '            "actual_supply_before_heater_temperature": before_heater,\n'
    '            "actual_supply_before_heater_temperature_source": before_source,\n'
    '            "actual_supply_before_heater_age_seconds": round(sample_age, 1) if sample_age is not None else None,\n',
)
replace_once(
    "gateway/controller_runtime.py",
    '            "smart_max_rh_room": max_rh[1],\n',
    '            "smart_max_rh_room": max_rh[1],\n'
    '            "bathroom_policy": {\n'
    '                "rh_setpoint": self.config.data.get("bathroom_rh_setpoint"),\n'
    '                "rh_hysteresis": self.config.data.get("bathroom_rh_hysteresis"),\n'
    '                "max_level": self.config.data.get("bathroom_max_level"),\n'
    '                "night_air_quality_max_level": self.config.data.get("night_air_quality_max_level"),\n'
    '            },\n',
)

# ---------------------------------------------------------------------------
# Overview data mapping: prefer canonical T2 and never present stale legacy data.
# ---------------------------------------------------------------------------
replace_once(
    "frontend-v2/src/pages/OverviewPage.tsx",
    '  const beforeHeater = first(controller, "actual_supply_before_heater_temperature") ?? first(unit, "supply_temp");\n',
    '  const beforeHeater = first(controller, "actual_supply_before_heater_temperature") ?? first(unit, "supply_temperature", "supply_temp");\n',
)

# ---------------------------------------------------------------------------
# Professional unit SVG with larger, inward ports and external afterheater.
# ---------------------------------------------------------------------------
write("frontend-v2/src/components/Hch5UnitDiagram.tsx", r'''import type { CSSProperties } from "react";

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
''')

write("frontend-v2/src/components/Hch5UnitDiagram.test.tsx", r'''import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Hch5UnitDiagram, type Hch5UnitDiagramProps } from "./Hch5UnitDiagram";
const baseProps:Hch5UnitDiagramProps={outdoor:4.2,extract:22.1,exhaust:8.4,beforeHeater:18.5,afterHeater:21,room:21.7,frost:7,flowWater:34,returnWater:28,supplyRpm:1180,extractRpm:1120,supplyPercent:42,extractPercent:40,bypassActual:false,bypassRequest:"auto",heating:true,recovery:82};
describe("Hch5UnitDiagram",()=>{
  it("crosses both normal air paths through exchanger centre",()=>{const m=renderToStaticMarkup(<Hch5UnitDiagram {...baseProps}/>);expect(m.match(/L550 295/g)?.length).toBeGreaterThanOrEqual(6);expect(m).toContain("is-recovery");});
  it("reroutes only supply in bypass and keeps the external coil",()=>{const m=renderToStaticMarkup(<Hch5UnitDiagram {...baseProps} bypassActual/>);expect(m).toContain("Q356 205 356 178 V143");expect(m).toContain("M1260 205 H776");expect(m).toContain("Ekstern eftervarme · HAC1");expect(m).toContain("is-bypass");});
  it("uses larger inward duct collars and shows T2 before external coil",()=>{const m=renderToStaticMarkup(<Hch5UnitDiagram {...baseProps}/>);expect(m).toContain('rx="43"');expect(m).toContain("T2 før flade");expect(m).toContain("Kun setpunkt styres");});
  it("stops airflow animation with stopped fans",()=>{const m=renderToStaticMarkup(<Hch5UnitDiagram {...baseProps} supplyRpm={0} extractRpm={0}/>);expect(m.match(/--flow-speed:0s/g)?.length).toBe(8);});
});
''')

# ---------------------------------------------------------------------------
# Management pages: Home Assistant, diagnostics and settings.
# ---------------------------------------------------------------------------
write("frontend-v2/src/pages/HomeAssistantPage.tsx", r'''import { useCallback, useEffect, useState } from "react";
import { Activity, Home, Radio, ShieldCheck, Wifi } from "lucide-react";
import { InfoList } from "../components/InfoList";
import { requestJson } from "../lib/api";
import "../styles/panels.css";
import "../styles/management.css";
type Data=Record<string,unknown>;
function text(v:unknown,f="—"){return v===null||v===undefined||v===""?f:String(v)}
function age(v:unknown){const n=Number(v);return Number.isFinite(n)?`${n.toLocaleString("da-DK",{maximumFractionDigits:1})} sek`:"—"}
function bool(v:unknown){return v===true?"Ja":v===false?"Nej":"—"}
export function HomeAssistantPage(){const[state,setState]=useState<Data>({});const[controller,setController]=useState<Data>({});const[online,setOnline]=useState(false);
 const refresh=useCallback(async()=>{const[a,b]=await Promise.allSettled([requestJson<Data>("/state.json",{timeoutMs:3500}),requestJson<Data>("/api/controller/state",{timeoutMs:3500})]);if(a.status==="fulfilled")setState(a.value);if(b.status==="fulfilled")setController(b.value);setOnline(a.status==="fulfilled"&&b.status==="fulfilled")},[]);
 useEffect(()=>{void refresh();const t=setInterval(()=>void refresh(),5000);return()=>clearInterval(t)},[refresh]);
 const rooms=(controller.smart_ha_rooms&&typeof controller.smart_ha_rooms==="object"?controller.smart_ha_rooms:{}) as Record<string,Data>;const roomEntries=Object.entries(rooms);const smartFresh=controller.smart_inputs_online===true;const master=text(controller.active_master).toLowerCase();
 return <section className="dashboard-overview page-enter"><header className="overview-heading-row"><div><span className="eyebrow">HOME ASSISTANT</span><h1>Integration og smart-data</h1><p>HA er klient. HCH5 Control fortsætter lokalt, også når Home Assistant er offline.</p></div><div className="overview-status-pills"><div><span className={`status-led ${online?"":"warn"}`}/><small>Integration</small><strong>{online?"Forbundet":"Afventer"}</strong></div><div><Radio size={18}/><small>Smart inputs</small><strong>{smartFresh?"Friske":"Stale / mangler"}</strong></div><div><ShieldCheck size={18}/><small>Master</small><strong>{master==="pi"?"Raspberry Pi":master==="hcp4"?"HCP4":"Unknown"}</strong></div></div></header>
 <div className="panel-grid"><article className="surface panel-card"><div className="pro-card-head compact"><div><h2>Forbindelse</h2><p>Controller API og leased HA-inputs</p></div><Wifi size={20}/></div><InfoList rows={[{label:"Controller API",value:online?"Online":"Offline",tone:online?"ok":"bad"},{label:"Integration domain",value:"hch_passivelink"},{label:"Sidst input",value:age(controller.smart_inputs_age_seconds),tone:smartFresh?"ok":"warn"},{label:"Lease",value:controller.smart_inputs_valid_for_seconds?`${text(controller.smart_inputs_valid_for_seconds)} sek`:"—"},{label:"Aktive HA-rum",value:String(roomEntries.length)},{label:"Hardware writes",value:controller.hardware_writes_allowed===true?"Allowed":"Blocked",tone:controller.hardware_writes_allowed===true?"ok":"neutral"}]}/></article>
 <article className="surface panel-card"><div className="pro-card-head compact"><div><h2>Passive data</h2><p>Sensorlaget er uafhængigt af master-skift</p></div><Activity size={20}/></div><InfoList rows={[{label:"RS485",value:controller.rs485_healthy===true?"Healthy":"Afventer",tone:controller.rs485_healthy===true?"ok":"warn"},{label:"Bus traffic",value:bool(state.bus_traffic),tone:state.bus_traffic===true?"ok":"warn"},{label:"Raw mirror",value:"Port 4196"},{label:"Canonical state",value:state.available===true||state.bus_traffic===true?"Aktiv":"Afventer",tone:state.available===true||state.bus_traffic===true?"ok":"warn"},{label:"Master",value:text(controller.active_master)},{label:"Entities ved master-skift",value:"Bevares"}]}/></article>
 <article className="surface panel-card panel-span-2"><div className="pro-card-head compact"><div><h2>Rum fra Home Assistant</h2><p>Værdi, type, prioritet og freshness. Badeværelser bruger separat RH-politik.</p></div><Home size={20}/></div>{roomEntries.length===0?<div className="panel-empty">Ingen friske HA-rum modtaget endnu.</div>:<div className="room-grid">{roomEntries.map(([name,room])=><div className="room-card" key={name}><div><strong>{name}</strong><span>{text(room.room_type,"auto")} · {text(room.priority,"auto")}</span></div><dl><dt>Temperatur</dt><dd>{room.temperature!==undefined?`${text(room.temperature)} °C`:"—"}</dd><dt>RH</dt><dd>{room.humidity!==undefined?`${text(room.humidity)} %`:"—"}</dd><dt>CO₂</dt><dd>{room.co2!==undefined?`${text(room.co2)} ppm`:"—"}</dd><dt>Kontrol</dt><dd>{room.control===false?"Kun visning":"Aktiv"}</dd></dl></div>)}</div>}</article>
 <article className="surface panel-card panel-span-2"><div className="pro-card-head compact"><div><h2>Fallback og sikkerhed</h2><p>Home Assistant kan aldrig omgå lokal arbitration.</p></div><ShieldCheck size={20}/></div><div className="policy-strip"><div><span>HA online</span><strong>Smart inputs → lokal controller</strong></div><div><span>HA offline</span><strong>Local Auto fallback</strong></div><div><span>HCP4 master</span><strong>0 hardware writes · sensorer fortsætter</strong></div></div></article></div></section>}
''')

write("frontend-v2/src/pages/DiagnosticsPage.tsx", r'''import { useCallback, useEffect, useState } from "react";
import { Activity, Download, RefreshCw, Server, ShieldAlert, Wrench } from "lucide-react";
import { InfoList } from "../components/InfoList";
import { postJson, requestJson } from "../lib/api";
import "../styles/panels.css";import "../styles/management.css";
type Data=Record<string,unknown>;type Auth={csrf?:string|null};
function text(v:unknown,f="—"){return v===null||v===undefined||v===""?f:String(v)}function num(v:unknown){const n=Number(v);return Number.isFinite(n)?n:null}function age(v:unknown){const n=num(v);return n===null?"—":`${n.toLocaleString("da-DK",{maximumFractionDigits:1})} sek`}
export function DiagnosticsPage(){const[state,setState]=useState<Data>({});const[controller,setController]=useState<Data>({});const[csrf,setCsrf]=useState("");const[selfTest,setSelfTest]=useState<string[]>([]);const[busy,setBusy]=useState(false);const refresh=useCallback(async()=>{const[a,b,c]=await Promise.allSettled([requestJson<Data>("/state.json",{timeoutMs:4000}),requestJson<Data>("/api/controller/state",{timeoutMs:4000}),requestJson<Auth>("/api/auth/status",{timeoutMs:4000})]);if(a.status==="fulfilled")setState(a.value);if(b.status==="fulfilled")setController(b.value);if(c.status==="fulfilled")setCsrf(c.value.csrf??"")},[]);useEffect(()=>{void refresh();const t=setInterval(()=>void refresh(),5000);return()=>clearInterval(t)},[refresh]);
 const runTest=async()=>{setBusy(true);const[a,b,c]=await Promise.allSettled([requestJson<Data>("/state.json"),requestJson<Data>("/api/controller/state"),requestJson<Auth>("/api/auth/status")]);const lines=[`WebUI/API: ${a.status==="fulfilled"?"PASS":"FAIL"}`,`Controller runtime: ${b.status==="fulfilled"?"PASS":"FAIL"}`,`Auth: ${c.status==="fulfilled"?"PASS":"FAIL"}`,`RS485: ${b.status==="fulfilled"&&b.value.rs485_healthy===true?"PASS":"CHECK"}`,`Raw mirror: ${state.bus_traffic===true?"PASS (bus data active)":"CHECK"}`,`Gateway service: ${state.service_gateway_activestate==="active"?"PASS":"CHECK"}`,`Admin service: ${state.service_admin_activestate==="active"||state.admin_service_activestate==="active"?"PASS":"CHECK"}`];setSelfTest(lines);setBusy(false)};
 const restart=async()=>{if(!csrf||!window.confirm("Genstart gateway-servicen? Ventilationens lokale sikkerhedslogik bevares, men WebUI kan være væk kortvarigt."))return;await postJson("/api/admin/action",{action:"restart_service",target:"gateway"},csrf);};
 return <section className="dashboard-overview page-enter"><header className="overview-heading-row"><div><span className="eyebrow">DIAGNOSTIK</span><h1>Fejlsøgning og helbred</h1><p>Read-only status for controller, RS485, sensorer og services.</p></div><div className="overview-status-pills"><div><span className={`status-led ${controller.rs485_healthy===true?"":"warn"}`}/><small>RS485</small><strong>{controller.rs485_healthy===true?"Healthy":"Check"}</strong></div><div><ShieldAlert size={18}/><small>Write gate</small><strong>{controller.hardware_writes_allowed===true?"Allowed":"Blocked"}</strong></div></div></header>
 <div className="panel-grid"><article className="surface panel-card"><div className="pro-card-head compact"><div><h2>Master arbitration</h2><p>HCP4 vinder altid</p></div><Activity size={20}/></div><InfoList rows={[{label:"Active master",value:text(controller.active_master)},{label:"Hardware writes",value:controller.hardware_writes_allowed===true?"Allowed":"Blocked",tone:controller.hardware_writes_allowed===true?"ok":"neutral"},{label:"Control state",value:text(controller.hardware_control_state)},{label:"Bus age",value:age(controller.bus_last_frame_age??state.bus_last_frame_age)},{label:"Effective source",value:text(controller.effective_source)},{label:"Reason",value:text(controller.effective_reason)}]}/></article>
 <article className="surface panel-card"><div className="pro-card-head compact"><div><h2>RS485 / data</h2><p>19200 · 8E1</p></div><Wrench size={20}/></div><InfoList rows={[{label:"Bus healthy",value:controller.rs485_healthy===true?"Ja":"Nej",tone:controller.rs485_healthy===true?"ok":"warn"},{label:"Traffic",value:state.bus_traffic===true?"Aktiv":"Afventer"},{label:"Frame rate",value:text(state.bus_frame_rate)},{label:"T2 source",value:text(controller.actual_supply_before_heater_temperature_source)},{label:"T2 age",value:age(controller.actual_supply_before_heater_age_seconds)},{label:"Last controller error",value:text(controller.last_error,"Ingen"),tone:controller.last_error?"bad":"ok"}]}/></article>
 <article className="surface panel-card"><div className="pro-card-head compact"><div><h2>Services</h2><p>Systemd og porte</p></div><Server size={20}/></div><InfoList rows={[{label:"Gateway",value:text(state.service_gateway_activestate),tone:state.service_gateway_activestate==="active"?"ok":"warn"},{label:"Admin",value:text(state.service_admin_activestate??state.admin_service_activestate)},{label:"1-Wire",value:text(state.service_onewire_activestate)},{label:"Gateway PID",value:text(state.service_gateway_mainpid??state.service_gateway_pid)},{label:"8080",value:"WebUI/API"},{label:"4196",value:"Read-only RS485 mirror"}]}/></article>
 <article className="surface panel-card"><div className="pro-card-head compact"><div><h2>Sikker systemtest</h2><p>Kun reads — ingen Modbus writes</p></div><RefreshCw size={20}/></div><div className="diag-actions"><button className="primary-action" disabled={busy} onClick={()=>void runTest()}>{busy?"Tester…":"Kør systemtest"}</button><a className="secondary-action" href="/api/diagnostics/report"><Download size={15}/> Download rapport</a><button className="danger-outline" onClick={()=>void restart()}>Genstart gateway</button></div>{selfTest.length>0&&<pre className="self-test-output">{selfTest.join("\n")}</pre>}</article></div></section>}
''')

write("frontend-v2/src/pages/SettingsPage.tsx", r'''import { useCallback, useEffect, useState } from "react";
import { Moon, Save, ShieldCheck, SlidersHorizontal, Wind } from "lucide-react";
import { postJson, requestJson } from "../lib/api";
import "../styles/panels.css";import "../styles/management.css";
type Data=Record<string,unknown>;type Auth={csrf?:string|null;enabled?:boolean;username?:string|null};
function n(v:unknown,f:number){const x=Number(v);return Number.isFinite(x)?x:f}function s(v:unknown,f=""){return v===null||v===undefined?f:String(v)}
export function SettingsPage(){const[controller,setController]=useState<Data>({});const[auth,setAuth]=useState<Auth>({});const[csrf,setCsrf]=useState("");const[form,setForm]=useState<Data>({});const[busy,setBusy]=useState(false);const[notice,setNotice]=useState("");const[theme,setTheme]=useState(()=>localStorage.getItem("hch5-v2-theme")??"dark");const[collapsed,setCollapsed]=useState(()=>localStorage.getItem("hch5-v2-sidebar")==="1");const[motion,setMotion]=useState(()=>localStorage.getItem("hch5-v2-motion")??"normal");
 const refresh=useCallback(async()=>{const[c,a]=await Promise.all([requestJson<Data>("/api/controller/state"),requestJson<Auth>("/api/auth/status")]);setController(c);setForm(c);setAuth(a);setCsrf(a.csrf??"")},[]);useEffect(()=>{void refresh()},[refresh]);
 const set=(key:string,value:unknown)=>setForm(v=>({...v,[key]:value}));const save=async()=>{if(!csrf)return;setBusy(true);setNotice("Gemmer…");const keys=["local_normal_level","rh_setpoint","rh_hysteresis","co2_setpoint","co2_hysteresis","night_enabled","night_start","night_end","night_level","night_air_quality_max_level","bathroom_rh_setpoint","bathroom_rh_hysteresis","bathroom_max_level","afterheat_setpoint","cooling_enabled","cooling_room_setpoint","cooling_hysteresis","cooling_outdoor_min","cooling_min_delta","cooling_level","ha_timeout_seconds"] ;const patch:Object=Object.fromEntries(keys.map(k=>[k,form[k]]));try{const next=await postJson<Data>("/api/controller/config",patch as Data,csrf);setController(next);setForm(next);setNotice("Indstillinger gemt.")}catch(e){setNotice(`Fejl: ${e instanceof Error?e.message:"ukendt fejl"}`)}finally{setBusy(false)}};
 const uiSave=()=>{localStorage.setItem("hch5-v2-theme",theme);localStorage.setItem("hch5-v2-sidebar",collapsed?"1":"0");localStorage.setItem("hch5-v2-motion",motion);document.documentElement.dataset.motion=motion;window.dispatchEvent(new Event("hch5-ui-preferences"));setNotice("UI-indstillinger gemt.")};
 return <section className="dashboard-overview page-enter"><header className="overview-heading-row"><div><span className="eyebrow">INDSTILLINGER</span><h1>Controller og brugerflade</h1><p>Én samlet config — ingen parallelle eller skjulte hardwareindstillinger.</p></div></header><div className="panel-grid">
 <article className="surface panel-card"><div className="pro-card-head compact"><div><h2>Brugerflade</h2><p>Tema, sidebar og bevægelse</p></div><Moon size={20}/></div><div className="settings-grid"><label>Tema<select value={theme} onChange={e=>setTheme(e.target.value)}><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></label><label>Sidebar<select value={collapsed?"collapsed":"expanded"} onChange={e=>setCollapsed(e.target.value==="collapsed")}><option value="expanded">Expanded</option><option value="collapsed">Collapsed</option></select></label><label>Animation<select value={motion} onChange={e=>setMotion(e.target.value)}><option value="normal">Normal</option><option value="reduced">Reduced</option></select></label><button className="secondary-action" onClick={uiSave}>Gem UI</button></div></article>
 <article className="surface panel-card"><div className="pro-card-head compact"><div><h2>Natdrift</h2><p>Én resolver — nat og luftkvalitet kæmper ikke</p></div><Wind size={20}/></div><div className="settings-grid"><label className="check-row"><input type="checkbox" checked={form.night_enabled===true} onChange={e=>set("night_enabled",e.target.checked)}/> Natsænkning aktiv</label><label>Start<input type="time" value={s(form.night_start,"22:00")} onChange={e=>set("night_start",e.target.value)}/></label><label>Slut<input type="time" value={s(form.night_end,"06:00")} onChange={e=>set("night_end",e.target.value)}/></label><label>Normal nat-trin<input type="number" min="1" max="6" value={n(form.night_level,2)} onChange={e=>set("night_level",Number(e.target.value))}/></label><label>Maks. ved luftkvalitet<input type="number" min="1" max="6" value={n(form.night_air_quality_max_level,4)} onChange={e=>set("night_air_quality_max_level",Number(e.target.value))}/></label></div></article>
 <article className="surface panel-card"><div className="pro-card-head compact"><div><h2>Badeværelse</h2><p>Separat RH-politik så høj fugt ikke giver ukontrolleret fuld boost</p></div><SlidersHorizontal size={20}/></div><div className="settings-grid"><label>RH start<input type="number" min="35" max="90" step="1" value={n(form.bathroom_rh_setpoint,65)} onChange={e=>set("bathroom_rh_setpoint",Number(e.target.value))}/><span>%</span></label><label>Hysterese<input type="number" min="1" max="20" step="1" value={n(form.bathroom_rh_hysteresis,5)} onChange={e=>set("bathroom_rh_hysteresis",Number(e.target.value))}/><span>%</span></label><label>Maks. trin<input type="number" min="1" max="6" value={n(form.bathroom_max_level,4)} onChange={e=>set("bathroom_max_level",Number(e.target.value))}/></label><p className="settings-help">Rum med room_type=bathroom — eller navne som Badeværelse/Bath/Shower — bruger disse værdier. HA kan senere overskrive pr. rum.</p></div></article>
 <article className="surface panel-card"><div className="pro-card-head compact"><div><h2>Generel luftkvalitet</h2><p>Local/Smart Auto</p></div><Wind size={20}/></div><div className="settings-grid"><label>RH setpunkt<input type="number" min="25" max="80" value={n(form.rh_setpoint,50)} onChange={e=>set("rh_setpoint",Number(e.target.value))}/><span>%</span></label><label>RH hysterese<input type="number" min="1" max="10" value={n(form.rh_hysteresis,3)} onChange={e=>set("rh_hysteresis",Number(e.target.value))}/><span>%</span></label><label>CO₂ setpunkt<input type="number" min="500" max="2000" step="50" value={n(form.co2_setpoint,800)} onChange={e=>set("co2_setpoint",Number(e.target.value))}/><span>ppm</span></label><label>Normaltrin<input type="number" min="1" max="6" value={n(form.local_normal_level,3)} onChange={e=>set("local_normal_level",Number(e.target.value))}/></label></div></article>
 <article className="surface panel-card"><div className="pro-card-head compact"><div><h2>Eftervarme</h2><p>HAC1 regulerer selv ventil/aktuator og frostsikring</p></div><ShieldCheck size={20}/></div><div className="settings-grid"><label>Indblæsnings-setpunkt<input type="number" min="18" max="30" value={n(form.afterheat_setpoint,20)} onChange={e=>set("afterheat_setpoint",Number(e.target.value))}/><span>°C</span></label><p className="settings-help">HCH5 Control sender kun temperatur-setpunkt. Der skrives aldrig direkte til varmefladens aktuator.</p></div></article>
 <article className="surface panel-card"><div className="pro-card-head compact"><div><h2>Sikkerhed og session</h2><p>WebUI-auth</p></div><ShieldCheck size={20}/></div><div className="settings-summary"><span>Bruger<strong>{auth.username??"—"}</strong></span><span>Login<strong>{auth.enabled===false?"Deaktiveret":"Aktiveret"}</strong></span><span>Master<strong>{s(controller.active_master,"—")}</strong></span><span>Writes<strong>{controller.hardware_writes_allowed===true?"Allowed":"Blocked"}</strong></span></div></article>
 </div><div className="settings-savebar"><span>{notice||"Ændringer gemmes først når du trykker Gem controller."}</span><button className="primary-action" disabled={busy||!csrf} onClick={()=>void save()}><Save size={15}/>{busy?"Gemmer…":"Gem controller"}</button></div></section>}
''')

write("frontend-v2/src/styles/management.css", r'''.panel-span-2{grid-column:1/-1}.room-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin-top:12px}.room-card{padding:12px;border:1px solid var(--border);border-radius:11px;background:var(--surface-soft)}.room-card>div{display:flex;justify-content:space-between;gap:10px}.room-card strong{font-size:11px}.room-card span{font-size:8px;color:var(--muted)}.room-card dl{display:grid;grid-template-columns:1fr auto;gap:7px 12px;margin:12px 0 0;font-size:9px}.room-card dt{color:var(--muted)}.room-card dd{margin:0;font-weight:750}.policy-strip{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}.policy-strip>div{display:grid;gap:4px;padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--surface-soft)}.policy-strip span{font-size:8px;color:var(--muted)}.policy-strip strong{font-size:10px}.diag-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:13px}.primary-action,.secondary-action,.danger-outline{min-height:38px;display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:0 13px;border-radius:9px;border:1px solid var(--border-strong);font-size:9px;font-weight:800;text-decoration:none;cursor:pointer}.primary-action{background:var(--blue);border-color:var(--blue);color:#06131c}.secondary-action{background:var(--surface-soft);color:var(--text)}.danger-outline{background:transparent;border-color:color-mix(in srgb,var(--red) 50%,var(--border));color:var(--red)}.self-test-output{margin:12px 0 0;padding:12px;border:1px solid var(--border);border-radius:10px;background:#07131b;color:#b8d1de;font:10px/1.7 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap}.settings-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 12px;margin-top:14px}.settings-grid label{position:relative;display:grid;gap:6px;color:var(--muted);font-size:8.5px;font-weight:750}.settings-grid input,.settings-grid select{width:100%;min-height:38px;padding:7px 10px;border:1px solid var(--border);border-radius:9px;background:var(--surface-soft);color:var(--text);outline:none}.settings-grid label>span{position:absolute;right:10px;bottom:11px;color:var(--muted);font-size:8px}.settings-grid .check-row{grid-template-columns:auto 1fr;align-items:center;justify-content:start}.settings-grid .check-row input{width:16px;min-height:16px}.settings-help{grid-column:1/-1;margin:0;color:var(--muted);font-size:8.5px;line-height:1.55}.settings-summary{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:14px}.settings-summary span{display:grid;gap:3px;padding:10px;border:1px solid var(--border);border-radius:9px;color:var(--muted);font-size:8px}.settings-summary strong{color:var(--text);font-size:10px}.settings-savebar{position:sticky;bottom:14px;z-index:8;display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:14px;padding:11px 13px;border:1px solid var(--border-strong);border-radius:12px;background:color-mix(in srgb,var(--surface) 92%,transparent);backdrop-filter:blur(16px);box-shadow:var(--shadow-md)}.settings-savebar span{font-size:9px;color:var(--muted)}@media(max-width:920px){.room-grid{grid-template-columns:1fr 1fr}.policy-strip{grid-template-columns:1fr}.settings-grid{grid-template-columns:1fr}}@media(max-width:620px){.room-grid{grid-template-columns:1fr}.panel-span-2{grid-column:auto}.settings-savebar{align-items:stretch;flex-direction:column}}
''')

# App routing: replace placeholders with real pages.
write("frontend-v2/src/App.tsx", r'''import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { DiagnosticsPage } from "./pages/DiagnosticsPage";
import { HistoryPage } from "./pages/HistoryPage";
import { HomeAssistantPage } from "./pages/HomeAssistantPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SystemPage } from "./pages/SystemPage";
import { TechniquePage } from "./pages/TechniquePage";
import { UpdatesPage } from "./pages/UpdatesPage";
export function App(){return <AppShell><Routes><Route path="/" element={<Navigate to="/overview" replace/>}/><Route path="/overview" element={<OverviewPage/>}/><Route path="/history" element={<HistoryPage/>}/><Route path="/technique" element={<TechniquePage/>}/><Route path="/system" element={<SystemPage/>}/><Route path="/home-assistant" element={<HomeAssistantPage/>}/><Route path="/diagnostics" element={<DiagnosticsPage/>}/><Route path="/updates" element={<UpdatesPage/>}/><Route path="/settings" element={<SettingsPage/>}/><Route path="*" element={<Navigate to="/overview" replace/>}/></Routes></AppShell>}
''')

# AppShell learns reduced motion and reacts to Settings page changes.
replace_once(
    "frontend-v2/src/components/AppShell.tsx",
    '  useEffect(() => {\n    document.documentElement.dataset.theme = effectiveTheme;\n    try { localStorage.setItem("hch5-v2-theme", theme); } catch {}\n  }, [theme, effectiveTheme]);\n',
    '  useEffect(() => {\n    document.documentElement.dataset.theme = effectiveTheme;\n    try { localStorage.setItem("hch5-v2-theme", theme); } catch {}\n  }, [theme, effectiveTheme]);\n\n'
    '  useEffect(() => {\n'
    '    const syncPreferences = () => {\n'
    '      setTheme(readTheme());\n'
    '      setCollapsed(readStored("hch5-v2-sidebar", "0") === "1");\n'
    '      document.documentElement.dataset.motion = readStored("hch5-v2-motion", "normal");\n'
    '    };\n'
    '    syncPreferences();\n'
    '    window.addEventListener("hch5-ui-preferences", syncPreferences);\n'
    '    return () => window.removeEventListener("hch5-ui-preferences", syncPreferences);\n'
    '  }, []);\n',
)

# Calm airflow, realistic collars, external coil and reduced-motion support.
with (ROOT / "frontend-v2/src/styles/overview.css").open("a", encoding="utf-8") as handle:
    handle.write(r'''

/* beta.22: calm airflow + professional external afterheater */
.hch-duct-collar ellipse:first-child{fill:url(#metalFace);stroke:#8ba0ad;stroke-width:2.4}.hch-duct-collar .hch-duct-inner{fill:#07131a;stroke:#3b5260;stroke-width:2}.hch-duct-collar path{stroke:#526b79;stroke-width:3;opacity:.65}.hch-external-coil .coil-case{fill:#172a35;stroke:#607987;stroke-width:2}.hch-external-coil .coil-duct{fill:#0a1821;stroke:#3f5a69;stroke-width:2}.hch-external-coil .coil-pipe{fill:none;stroke:#80614a;stroke-width:3}.hch-external-coil.active .coil-pipe{stroke:#f1a15c;filter:drop-shadow(0 0 5px rgb(241 161 92 / 35%))}.hch5-visual .hch-fog{stroke-dasharray:72 110;stroke-width:13;opacity:.18;animation-duration:var(--flow-speed);animation-timing-function:linear}.hch5-visual .hch-fog-b{stroke-dasharray:44 150;opacity:.12}.hch5-visual .hch-fog-wash{stroke-width:24;opacity:.055;stroke-dasharray:120 190;animation-duration:var(--flow-speed)}.hch5-visual .hch-airflow-guide{stroke-width:2.3;stroke-dasharray:18 46;opacity:.34;animation-duration:calc(var(--flow-speed) * 1.15)}@keyframes hch-fog-flow{to{stroke-dashoffset:-182}}@keyframes hch-guide-flow{to{stroke-dashoffset:-128}}:root[data-motion="reduced"] .hch-fog,:root[data-motion="reduced"] .hch-fog-wash,:root[data-motion="reduced"] .hch-airflow-guide,:root[data-motion="reduced"] .hch-fan-rotor{animation:none!important}:root[data-motion="reduced"] .hch-fog,:root[data-motion="reduced"] .hch-fog-wash{opacity:.08}
''')

# Regression tests for new policy and T2 mapping.
write("tests/test_beta22_policy.py", r'''import sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"gateway"))
from controller_core import ControllerEngine,ControllerState,HardwareAdapter
from controller_runtime import ControllerRuntime

def test_bathroom_policy_and_night_air_quality_cap(tmp_path):
    state=ControllerState(tmp_path/"controller.json")
    state.configure({"mode":"smart_auto","bathroom_rh_setpoint":65,"bathroom_rh_hysteresis":5,"bathroom_max_level":4,"night_air_quality_max_level":4,"night_enabled":True,"night_start":"00:00","night_end":"23:59","night_level":2})
    runtime=ControllerRuntime(gateway_state={"bus_traffic":False},hardware=HardwareAdapter(),state_path=tmp_path/"runtime.json")
    runtime.config=state;runtime.engine=ControllerEngine(state,HardwareAdapter())
    runtime.room_inputs({"source":"home_assistant","valid_for_s":180,"rooms":{"Badeværelse":{"humidity":78,"temperature":22,"priority":"auto","control":True,"enabled":True,"room_type":"bathroom"}}})
    level,*_=runtime._derive_smart_decision()
    assert level<=4
    state.heartbeat("boost",requested_level=6,valid_for_s=180,reason="Badeværelse RH")
    resolved=runtime.engine.resolve()
    assert resolved["effective_level"]<=4
    assert resolved["night_active"] is True

def test_t2_prefers_canonical_temperature_and_stales(tmp_path):
    gateway={"supply_temperature":18.4,"supply_temp":21.5,"temperature_sample_monotonic":time.monotonic(),"bus_traffic":False}
    runtime=ControllerRuntime(gateway_state=gateway,hardware=HardwareAdapter(),state_path=tmp_path/"controller.json")
    snap=runtime.snapshot();assert snap["actual_supply_before_heater_temperature"]==18.4;assert snap["actual_supply_before_heater_temperature_source"]=="canonical_t2"
    gateway["temperature_sample_monotonic"]=time.monotonic()-60
    assert runtime.snapshot()["actual_supply_before_heater_temperature"] is None

def test_afterheat_ui_contract_is_setpoint_only():
    source=(ROOT/"frontend-v2/src/pages/OverviewPage.tsx").read_text()
    settings=(ROOT/"frontend-v2/src/pages/SettingsPage.tsx").read_text()
    assert "afterheat_setpoint" in source and "afterheat_valve" not in source
    assert "afterheat_setpoint" in settings and "actuator_position" not in settings
''')

# Version bump.
write("VERSION", "1.2.0-beta.22\n")

# Remove this one-shot patcher after CI applies it; the workflow removes itself too.
print("beta.22 migration applied")
