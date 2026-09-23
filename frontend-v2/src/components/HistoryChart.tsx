import { useEffect, useRef, useState } from "react";
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
  const padding = { top: 10, right: 10, bottom: 22, left: 10 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  const points = series.map(item => ({
    ...item,
    values: samples.map(sample => (typeof sample[item.key] === "number" ? (sample[item.key] as number) : null)),
  }));

  const finite = points.flatMap(item => item.values.filter((value): value is number => value !== null));
  const hasData = samples.length > 1 && finite.length > 1;
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
  const xFor = (index: number) => padding.left + (index / (samples.length - 1)) * plotWidth;

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

  return (
    <div ref={container} className="history-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Historikgraf">
        <line className="history-grid-line" x1={padding.left} x2={width - padding.right} y1={yFor(max)} y2={yFor(max)} />
        <line className="history-grid-line" x1={padding.left} x2={width - padding.right} y1={yFor(min)} y2={yFor(min)} />
        {paths.map(item => (
          <path key={item.key} d={item.d} fill="none" stroke={COLORS[item.color]} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        ))}
        <text className="history-axis-label" x={padding.left} y={yFor(max) - 4}>{formatValue(max, unit)}</text>
        <text className="history-axis-label" x={padding.left} y={yFor(min) + 12}>{formatValue(min, unit)}</text>
      </svg>
      <div className="history-chart-legend">
        {series.map(item => <span key={item.key} className="history-legend-item"><i style={{ background: COLORS[item.color] }} />{item.label}</span>)}
        {typeof first === "number" && typeof last === "number" && (
          <span className="history-chart-range">{formatClock(first)} – {formatClock(last)}</span>
        )}
      </div>
    </div>
  );
}
