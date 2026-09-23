import { useEffect, useRef, useState, type PointerEvent } from "react";
type Sample = Record<string, number | null>;

export interface HistorySeries {
  key: string;
  label: string;
  color: "blue" | "orange" | "green" | "red";
}

export interface HistoryChartProps {
  samples: Sample[];
  series: HistorySeries[];
  unit?: string;
  height?: number;
}

const COLORS: Record<HistorySeries["color"], string> = {
  blue: "var(--blue)",
  orange: "var(--orange)",
  green: "var(--green)",
  red: "var(--red)",
};

function formatValue(value: number, unit: string) {
  return `${value.toLocaleString("da-DK", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}${unit}`;
}

function formatClock(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString("da-DK", { hour: "2-digit", minute: "2-digit" });
}

export function HistoryChart({ samples, series, unit = "", height = 200 }: HistoryChartProps) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(960);
  const [hovered, setHovered] = useState<number | null>(null);
  const padding = { top: 10, right: 10, bottom: 22, left: 10 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  const points = series.map(item => ({
    ...item,
    values: samples.map(sample => (typeof sample[item.key] === "number" ? (sample[item.key] as number) : null)),
  }));

  const finite = points.flatMap(item => item.values.filter((value): value is number => value !== null));
  const hasData = samples.length > 0 && finite.length > 0;
  useEffect(() => {
    const target = container.current;
    if (!target) return;
    const update = () => setWidth(Math.max(240, Math.round(target.getBoundingClientRect().width)));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasData]);

  if (!hasData) {
    return (
      <div ref={container} className="history-chart-empty" style={{ height }}>
        <span>Ingen data i den valgte periode</span>
      </div>
    );
  }

  const min = Math.min(...finite);
  const max = Math.max(...finite);
  const span = max - min || 1;
  const yFor = (value: number) => padding.top + plotHeight - ((value - min) / span) * plotHeight;
  const xFor = (index: number) => padding.left + (samples.length === 1 ? 0.5 : index / (samples.length - 1)) * plotWidth;

  const paths = points.map(item => {
    let d = "";
    let drawing = false;
    item.values.forEach((value, index) => {
      if (value === null) { drawing = false; return; }
      const command = drawing ? "L" : "M";
      d += `${command}${xFor(index).toFixed(1)} ${yFor(value).toFixed(1)} `;
      drawing = true;
    });
    return { ...item, d };
  });

  const first = samples[0]?.ts;
  const last = samples[samples.length - 1]?.ts;
  const active = hovered !== null && hovered < samples.length ? hovered : null;
  const activeValues = active === null ? [] : points.flatMap(item => {
    const value = item.values[active];
    return value === null ? [] : [{ ...item, value }];
  });
  const onPointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - bounds.left) * width / bounds.width;
    setHovered(Math.max(0, Math.min(samples.length - 1, Math.round((x - padding.left) / plotWidth * (samples.length - 1)))));
  };

  return (
    <div ref={container} className="history-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Historikgraf" onPointerMove={onPointerMove} onPointerLeave={() => setHovered(null)}>
        <line className="history-grid-line" x1={padding.left} x2={width - padding.right} y1={yFor(max)} y2={yFor(max)} />
        <line className="history-grid-line" x1={padding.left} x2={width - padding.right} y1={yFor(min)} y2={yFor(min)} />
        {paths.map(item => (
          <path key={item.key} d={item.d} fill="none" stroke={COLORS[item.color]} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        ))}
        {samples.length === 1 && points.map(item => item.values[0] === null ? null : <circle key={item.key} cx={xFor(0)} cy={yFor(item.values[0])} r="4" fill={COLORS[item.color]}/>)}
        {active !== null && <g className="history-hover-markers"><line x1={xFor(active)} x2={xFor(active)} y1={padding.top} y2={height - padding.bottom}/>{activeValues.map(item => <circle key={item.key} cx={xFor(active)} cy={yFor(item.value)} r="5" fill={COLORS[item.color]}/>)}</g>}
        <text className="history-axis-label" x={padding.left} y={yFor(max) - 4}>{formatValue(max, unit)}</text>
        <text className="history-axis-label" x={padding.left} y={yFor(min) + 12}>{formatValue(min, unit)}</text>
      </svg>
      {active !== null && activeValues.length > 0 && <div className="history-hover-detail" role="status"><strong>{typeof samples[active].ts === "number" ? new Date(samples[active].ts * 1000).toLocaleString("da-DK", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : `Punkt ${active + 1}`}</strong>{activeValues.map(item => <span key={item.key}><i style={{ background: COLORS[item.color] }}/>{item.label}: {formatValue(item.value, unit)}</span>)}</div>}
      <div className="history-chart-legend">
        {series.map(item => <span key={item.key} className="history-legend-item"><i style={{ background: COLORS[item.color] }} />{item.label}</span>)}
        {typeof first === "number" && typeof last === "number" && (
          <span className="history-chart-range">{formatClock(first)} – {formatClock(last)}</span>
        )}
      </div>
    </div>
  );
}
