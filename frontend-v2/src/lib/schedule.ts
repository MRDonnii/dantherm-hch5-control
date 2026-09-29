export type PeriodMode = "set" | "min";
export interface Period { start: string; end: string; level: number; mode: PeriodMode; label: string }
export type WeekPeriods = Record<string, Period[]>;

export const DAY_NAMES = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"];
export const DAY_SHORT = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"];
export const WEEKDAYS = [0, 1, 2, 3, 4];
export const WEEKEND = [5, 6];
export const MAX_PERIODS_PER_DAY = 8;
export const SNAP_MINUTES = 15;
export const LABEL_SUGGESTIONS = ["Hjemme", "Ude", "Madlavning", "Gæster", "Nat", "Morgen"];

export function toMinutes(value: string): number {
  const [hour, minute] = value.split(":").map(Number);
  return (hour || 0) * 60 + (minute || 0);
}

/** 0..1440 → "HH:MM"; 1440 is written as "00:00" (midnight, end of day). */
export function toTime(minutes: number): string {
  const value = ((Math.round(minutes) % 1440) + 1440) % 1440;
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
}

export function snap(minutes: number, step = SNAP_MINUTES): number {
  return Math.round(minutes / step) * step;
}

export function emptyWeek(): WeekPeriods {
  return Object.fromEntries([0, 1, 2, 3, 4, 5, 6].map(day => [String(day), []]));
}

export function cloneWeek(week: WeekPeriods | null | undefined): WeekPeriods {
  const result = emptyWeek();
  for (const day of Object.keys(result)) {
    result[day] = (week?.[day] ?? []).map(period => ({
      start: String(period.start), end: String(period.end), level: Number(period.level) || 3,
      mode: period.mode === "min" ? "min" : "set", label: String(period.label ?? ""),
    }));
  }
  return result;
}

export function sortDay(periods: Period[]): Period[] {
  return [...periods].sort((a, b) => toMinutes(a.start) - toMinutes(b.start));
}

/** Minutes a period covers, treating an end at or before the start as past midnight. */
export function span(period: Period): [number, number] {
  const start = toMinutes(period.start);
  let end = toMinutes(period.end);
  if (end <= start) end += 1440;
  return [start, end];
}

export function wrapsMidnight(period: Period): boolean {
  return toMinutes(period.end) <= toMinutes(period.start) && period.end !== "00:00";
}

export interface Segment { day: number; index: number; from: number; to: number; continued: boolean; period: Period }

/** What to draw on each day's 24-hour track, including the part of yesterday's period after midnight. */
export function segments(week: WeekPeriods): Segment[][] {
  const rows: Segment[][] = [[], [], [], [], [], [], []];
  for (let day = 0; day < 7; day += 1) {
    (week[String(day)] ?? []).forEach((period, index) => {
      const [from, to] = span(period);
      rows[day].push({ day, index, from, to: Math.min(to, 1440), continued: false, period });
      if (to > 1440) rows[(day + 1) % 7].push({ day, index, from: 0, to: to - 1440, continued: true, period });
    });
  }
  return rows;
}

export function overlaps(week: WeekPeriods, day: number, index: number): boolean {
  const own = segments(week)[day].filter(s => s.day === day && s.index === index);
  return segments(week).some((row, rowDay) => row.some(other =>
    !(other.day === day && other.index === index) &&
    own.some(mine => rowDay === day && mine.from < other.to && other.from < mine.to)));
}

export function sameWeek(a: WeekPeriods, b: WeekPeriods): boolean {
  return JSON.stringify(cloneWeek(a)) === JSON.stringify(cloneWeek(b));
}

export const TEMPLATES: { id: string; name: string; description: string; build: () => WeekPeriods }[] = [
  {
    id: "away",
    name: "Arbejdsdage ude",
    description: "Hverdage 08–16 lavt (trin 1), madlavning 17–19 mindst trin 4.",
    build: () => {
      const week = emptyWeek();
      for (const day of WEEKDAYS) week[String(day)] = [
        { start: "08:00", end: "16:00", level: 1, mode: "set", label: "Ude" },
        { start: "17:00", end: "19:00", level: 4, mode: "min", label: "Madlavning" },
      ];
      for (const day of WEEKEND) week[String(day)] = [{ start: "17:00", end: "19:00", level: 4, mode: "min", label: "Madlavning" }];
      return week;
    },
  },
  {
    id: "home",
    name: "Hjemmearbejde",
    description: "Hverdage 08–16 mindst trin 3, madlavning 17–19 mindst trin 4.",
    build: () => {
      const week = emptyWeek();
      for (const day of [...WEEKDAYS, ...WEEKEND]) week[String(day)] = [
        ...(WEEKDAYS.includes(day) ? [{ start: "08:00", end: "16:00", level: 3, mode: "min" as const, label: "Hjemme" }] : []),
        { start: "17:00", end: "19:00", level: 4, mode: "min", label: "Madlavning" },
      ];
      return week;
    },
  },
  { id: "clear", name: "Ryd ugen", description: "Fjerner alle perioder.", build: emptyWeek },
];

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const minutes = Math.max(0, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} t ${minutes % 60 ? `${minutes % 60} min` : ""}`.trim();
  return `${Math.floor(hours / 24)} dage`;
}

/** Epoch seconds or numeric string → value for <input type="datetime-local">. */
export function toLocalInput(value: unknown): string {
  const number = typeof value === "number" ? value : Number(value);
  if (!value || !Number.isFinite(number)) return "";
  const d = new Date(number * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? String(Math.floor(time / 1000)) : null;
}
