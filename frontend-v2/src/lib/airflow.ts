// Live copy of gateway/advanced_control.py airflow_plan() and the air balance,
// so the house calculation follows the form while typing instead of only
// after saving.
const BR18_AREA_LS_PER_M2 = 0.3;
const BR18_KITCHEN_LS = 20;
const BR18_BATHROOM_LS = 15;
const BR18_UTILITY_LS = 10;
const LS_TO_M3H = 3.6;
// HCH5 fan speed: about 557 rpm at 0 % plus 24 rpm per % (see advanced_control.py).
// Airflow follows speed (fan law); the controller replaces this with the learned curve.
const DEFAULT_FAN_RPM_AT_0 = 557;
const DEFAULT_FAN_RPM_PER_PERCENT = 24;
// Air balance limits (advanced_control.py / validate_profile).
const DUCT_RATIO_MIN = 0.7;
const DUCT_RATIO_MAX = 1.5;
const SUPPLY_PERCENT_MIN = 10;
const MAX_PERCENT_GAP = 35;

export type FanCurve = { rpm_at_0: number; rpm_per_percent: number; learned: boolean; samples: number };

export function fanCurve(data: Record<string, unknown>): FanCurve {
  const learned = data.fan_curve as { rpm_at_0?: unknown; rpm_per_percent?: unknown; samples?: unknown } | null | undefined;
  const at0 = Number(learned?.rpm_at_0);
  const perPercent = Number(learned?.rpm_per_percent);
  if (learned && Number.isFinite(at0) && Number.isFinite(perPercent) && at0 >= 0 && at0 <= 1500 && perPercent >= 5 && perPercent <= 60) {
    return { rpm_at_0: at0, rpm_per_percent: perPercent, learned: true, samples: Number(learned.samples) || 0 };
  }
  return { rpm_at_0: DEFAULT_FAN_RPM_AT_0, rpm_per_percent: DEFAULT_FAN_RPM_PER_PERCENT, learned: false, samples: 0 };
}

export const rpmAtPercent = (percent: number, curve: FanCurve) => curve.rpm_at_0 + curve.rpm_per_percent * percent;
export const percentAtRpm = (rpm: number, curve: FanCurve) => (rpm - curve.rpm_at_0) / curve.rpm_per_percent;

export function airflowAtPercent(percent: number, maxFlow: number, curve: FanCurve): number {
  return maxFlow * rpmAtPercent(percent, curve) / rpmAtPercent(100, curve);
}

export type AirflowProfiles = Record<string, { supply?: unknown; extract?: unknown; name?: unknown }>;
export type MeasuredEntry = { supply?: number; extract?: number; supply_percent?: number; extract_percent?: number };
export type MeasuredAirflow = Record<string, MeasuredEntry | undefined>;
export type PlanLevel = { supply_m3h: number; extract_m3h: number; estimate_supply_m3h: number; estimate_extract_m3h: number; air_changes_per_hour: number | null; measured: boolean; meets_requirement: boolean; meets_reduced: boolean };
export type AirflowPlan = {
  volume_m3: number; supply_required_m3h: number; extract_required_m3h: number;
  required_air_changes_per_hour: number | null; base_level: number; min_level: number;
  reachable: boolean; estimated: boolean; fan_curve: FanCurve; duct_ratio: number; duct_ratio_source: RatioSource;
  levels: Record<string, PlanLevel>;
};
export type RatioSource = "measured" | "learned" | "fixed";
export type SideConstants = { supply: number; extract: number; ratio: number; source: RatioSource; measured: ("supply" | "extract")[] };
export type BalancedLevel = { extract: number; supply: number; supply_exact: number; extract_m3h: number; supply_m3h: number; excess_percent: number; reached: boolean };

const num = (value: unknown, fallback: number) => { const x = Number(value); return Number.isFinite(x) ? x : fallback; };
const round2 = (value: number) => Math.round(value * 100) / 100;
const round1 = (value: number) => Math.round(value * 10) / 10;
const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));

/** Duct ratio k_supply/k_extract in use: learned once trusted (auto), else the fixed value. */
export function ductRatio(data: Record<string, unknown>): { ratio: number; source: "learned" | "fixed" } {
  if ((data.balance_ratio_mode ?? "auto") === "auto") {
    // The controller sets ratio_in_use only once two nights agree.
    const learned = data.balance_learned as { ratio_in_use?: unknown } | null | undefined;
    const ratio = learned?.ratio_in_use === null || learned?.ratio_in_use === undefined ? Number.NaN : Number(learned.ratio_in_use);
    if (Number.isFinite(ratio) && ratio >= DUCT_RATIO_MIN && ratio <= DUCT_RATIO_MAX) return { ratio, source: "learned" };
  }
  return { ratio: clamp(num(data.balance_duct_ratio, 1) || 1, DUCT_RATIO_MIN, DUCT_RATIO_MAX), source: "fixed" };
}

function measuredPoints(data: Record<string, unknown>, stored: AirflowProfiles | undefined) {
  const curve = fanCurve(data);
  const points: Record<"supply" | "extract", [number, number][]> = { supply: [], extract: [] };
  for (const [level, entry] of Object.entries((data.airflow_measured ?? {}) as MeasuredAirflow)) {
    if (!entry) continue;
    const profile = stored?.[level] ?? {};
    for (const side of ["supply", "extract"] as const) {
      const flow = Number(entry[side]);
      const percent = Number(entry[`${side}_percent`] ?? profile[side]);
      if (flow && Number.isFinite(flow) && Number.isFinite(percent)) points[side].push([rpmAtPercent(percent, curve), flow]);
    }
  }
  return points;
}

function fitThroughOrigin(points: [number, number][]): number | null {
  const square = points.reduce((sum, [rpm]) => sum + rpm * rpm, 0);
  return square ? points.reduce((sum, [rpm, flow]) => sum + rpm * flow, 0) / square : null;
}

/** m3/h per rpm on each side (advanced_control.side_constants). */
export function sideConstants(data: Record<string, unknown>, stored: AirflowProfiles | undefined): SideConstants {
  const curve = fanCurve(data);
  const { ratio, source } = ductRatio(data);
  const points = measuredPoints(data, stored);
  const supply = fitThroughOrigin(points.supply);
  const extract = fitThroughOrigin(points.extract);
  if (supply && extract) return { supply, extract, ratio: supply / extract, source: "measured", measured: ["supply", "extract"] };
  if (extract) return { supply: extract * ratio, extract, ratio, source, measured: ["extract"] };
  if (supply) return { supply, extract: supply / ratio, ratio, source, measured: ["supply"] };
  const mean = num(data.airflow_max_m3h, 375) / rpmAtPercent(100, curve);
  const root = Math.sqrt(ratio);
  return { supply: mean * root, extract: mean / root, ratio, source, measured: [] };
}

/** Supply percentage per level that puts extract airflow the wanted share above supply. */
export function balancedProfiles(data: Record<string, unknown>, profiles: AirflowProfiles | undefined): Record<string, BalancedLevel> | null {
  if (!profiles) return null;
  const curve = fanCurve(data);
  const k = sideConstants(data, (data.profiles as AirflowProfiles | undefined) ?? profiles);
  const target = 1 + num(data.balance_extract_excess_percent, 5) / 100;
  const result: Record<string, BalancedLevel> = {};
  let previous = SUPPLY_PERCENT_MIN - 1;
  for (let level = 1; level <= 6; level++) {
    const profile = profiles[String(level)];
    if (!profile) return null;
    const extract = Math.round(num(profile.extract, 0));
    const extractFlow = k.extract * rpmAtPercent(extract, curve);
    const exact = percentAtRpm(extractFlow / target / k.supply, curve);
    const low = Math.max(SUPPLY_PERCENT_MIN, extract - MAX_PERCENT_GAP, previous + 1);
    const high = extract - 1;
    const ratioAt = (percent: number) => extractFlow / (k.supply * rpmAtPercent(percent, curve));
    const candidates = [...new Set([Math.floor(exact), Math.ceil(exact)].map(value => Math.min(high, Math.max(low, value))))].sort((a, b) => a - b);
    const supply = candidates.reduce((best, percent) => Math.abs(ratioAt(percent) - target) < Math.abs(ratioAt(best) - target) ? percent : best, candidates[0]);
    previous = supply;
    result[String(level)] = {
      extract, supply, supply_exact: round1(exact),
      extract_m3h: Math.round(extractFlow), supply_m3h: Math.round(k.supply * rpmAtPercent(supply, curve)),
      excess_percent: round1((ratioAt(supply) - 1) * 100), reached: low - 0.5 <= exact && exact <= high + 0.5,
    };
  }
  return result;
}

/** The level profiles the unit runs: balanced supply when the balance is on. */
export function effectiveProfiles(data: Record<string, unknown>, profiles: AirflowProfiles | undefined): AirflowProfiles | undefined {
  if (!profiles || data.balance_enabled !== true) return profiles;
  const balanced = balancedProfiles(data, profiles);
  if (!balanced) return profiles;
  return Object.fromEntries(Object.entries(profiles).map(([level, values]) => [level, { ...values, supply: balanced[level]?.supply ?? values.supply }]));
}

export function airflowPlan(data: Record<string, unknown>, profiles: AirflowProfiles | undefined): AirflowPlan | null {
  if (!profiles) return null;
  const stored = (data.profiles as AirflowProfiles | undefined) ?? profiles;
  const running = effectiveProfiles(data, profiles) ?? profiles;
  const area = num(data.house_area_m2, 150);
  const height = num(data.ceiling_height_m, 2.5);
  const bathrooms = num(data.house_bathrooms, 1);
  const utility = num(data.house_utility_rooms, 1);
  const reduced = num(data.sizing_reduced_percent, 50) / 100;
  const measured = (data.airflow_measured ?? {}) as MeasuredAirflow;
  const curve = fanCurve(data);
  const k = sideConstants(data, stored);

  const volume = area * height;
  const areaLs = area * BR18_AREA_LS_PER_M2;
  const wetLs = BR18_KITCHEN_LS + bathrooms * BR18_BATHROOM_LS + utility * BR18_UTILITY_LS;
  const supplyRequired = areaLs * LS_TO_M3H;
  const extractRequired = Math.max(areaLs, wetLs) * LS_TO_M3H;

  const levels: Record<string, PlanLevel> = {};
  let base: number | null = null;
  let min: number | null = null;
  for (let level = 1; level <= 6; level++) {
    const profile = running[String(level)];
    if (!profile) return null;
    const entry = measured[String(level)] ?? {};
    const storedProfile = stored[String(level)] ?? {};
    const flows = { supply: 0, extract: 0 };
    const estimates = { supply: 0, extract: 0 };
    let usedMeasured = false;
    for (const side of ["supply", "extract"] as const) {
      const percent = Math.round(num(profile[side], 0));
      estimates[side] = k[side] * rpmAtPercent(percent, curve);
      const value = Number(entry[side]);
      const at = Number(entry[`${side}_percent`] ?? storedProfile[side]);
      if (value && Number.isFinite(value) && Math.round(at) === percent) { flows[side] = value; usedMeasured = true; }
      else flows[side] = estimates[side];
    }
    const meets = flows.supply >= supplyRequired && flows.extract >= extractRequired;
    const meetsReduced = flows.supply >= supplyRequired * reduced && flows.extract >= extractRequired * reduced;
    if (meets && base === null) base = level;
    if (meetsReduced && min === null) min = level;
    levels[String(level)] = {
      supply_m3h: Math.round(flows.supply), extract_m3h: Math.round(flows.extract),
      estimate_supply_m3h: Math.round(estimates.supply), estimate_extract_m3h: Math.round(estimates.extract),
      air_changes_per_hour: volume ? round2(flows.supply / volume) : null,
      measured: usedMeasured, meets_requirement: meets, meets_reduced: meetsReduced,
    };
  }
  const reachable = base !== null;
  const baseLevel = base ?? 6;
  return {
    volume_m3: Math.round(volume), supply_required_m3h: Math.round(supplyRequired), extract_required_m3h: Math.round(extractRequired),
    required_air_changes_per_hour: volume ? round2(supplyRequired / volume) : null,
    base_level: baseLevel, min_level: Math.min(min ?? baseLevel, baseLevel), reachable,
    estimated: !Object.values(levels).every(row => row.measured), fan_curve: curve,
    duct_ratio: Math.round(k.ratio * 1000) / 1000, duct_ratio_source: k.source, levels,
  };
}
