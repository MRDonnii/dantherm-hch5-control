import type { ReactNode } from "react";

export interface InfoRow {
  label: string;
  value: ReactNode;
  tone?: "ok" | "warn" | "bad" | "neutral";
}

export function InfoList({ rows }: { rows: InfoRow[] }) {
  return (
    <dl className="info-list">
      {rows.map(row => (
        <div key={row.label} className={`info-row${row.tone ? ` tone-${row.tone}` : ""}`}>
          <dt>{row.label}</dt>
          <dd>{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}
