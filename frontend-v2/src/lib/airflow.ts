// Live copy of gateway/advanced_control.py airflow_plan(), so the house
// calculation follows the form while typing instead of only after saving.
const BR18_AREA_LS_PER_M2 = 0.3;
const BR18_KITCHEN_LS = 20;
const BR18_BATHROOM_LS = 15;
const BR18_UTILITY_LS = 10;
const LS_TO_M3H = 3.6;

export type AirflowProfiles = Record<string, { supply?: unknown; extract?: unknown }>;
export type MeasuredAirflow = Record<string, { supply?: number; extract?: number } | undefined>;
export type PlanLevel = { supply_m3h: number; extract_m3h: number; estimate_supply_m3h: number; estimate_extract_m3h: number; air_changes_per_hour: number | null; measured: boolean; meets_requirement: boolean; meets_reduced: boolean };
export type AirflowPlan = {
  volume_m3: number; supply_required_m3h: number; extract_required_m3h: number;
  required_air_changes_per_hour: number | null; base_level: number; min_level: number;
  reachable: boolean; estimated: boolean; levels: Record<string, PlanLevel>;
};

const num = (value: unknown, fallback: number) => { const x = Number(value); return Number.isFinite(x) ? x : fallback; };
const round2 = (value: number) => Math.round(value * 100) / 100;

export function airflowPlan(data: Record<string, unknown>, profiles: AirflowProfiles | undefined): AirflowPlan | null {
  if (!profiles) return null;
  const area = num(data.house_area_m2, 150);
  const height = num(data.ceiling_height_m, 2.5);
  const bathrooms = num(data.house_bathrooms, 1);
  const utility = num(data.house_utility_rooms, 1);
  const maxFlow = num(data.airflow_max_m3h, 375);
  const reduced = num(data.sizing_reduced_percent, 50) / 100;
  const measured = (data.airflow_measured ?? {}) as MeasuredAirflow;

  const volume = area * height;
  const areaLs = area * BR18_AREA_LS_PER_M2;
  const wetLs = BR18_KITCHEN_LS + bathrooms * BR18_BATHROOM_LS + utility * BR18_UTILITY_LS;
  const supplyRequired = areaLs * LS_TO_M3H;
  const extractRequired = Math.max(areaLs, wetLs) * LS_TO_M3H;

  const levels: Record<string, PlanLevel> = {};
  let base: number | null = null;
  let min: number | null = null;
  for (let level = 1; level <= 6; level++) {
    const profile = profiles[String(level)];
    if (!profile) return null;
    const entry = measured[String(level)] ?? {};
    const estimateSupply = maxFlow * num(profile.supply, 0) / 100;
    const estimateExtract = maxFlow * num(profile.extract, 0) / 100;
    const supply = entry.supply ? Number(entry.supply) : estimateSupply;
    const extract = entry.extract ? Number(entry.extract) : estimateExtract;
    const meets = supply >= supplyRequired && extract >= extractRequired;
    const meetsReduced = supply >= supplyRequired * reduced && extract >= extractRequired * reduced;
    if (meets && base === null) base = level;
    if (meetsReduced && min === null) min = level;
    levels[String(level)] = {
      supply_m3h: Math.round(supply), extract_m3h: Math.round(extract),
      estimate_supply_m3h: Math.round(estimateSupply), estimate_extract_m3h: Math.round(estimateExtract),
      air_changes_per_hour: volume ? round2(supply / volume) : null,
      measured: Boolean(entry.supply || entry.extract), meets_requirement: meets, meets_reduced: meetsReduced,
    };
  }
  const reachable = base !== null;
  const baseLevel = base ?? 6;
  return {
    volume_m3: Math.round(volume), supply_required_m3h: Math.round(supplyRequired), extract_required_m3h: Math.round(extractRequired),
    required_air_changes_per_hour: volume ? round2(supplyRequired / volume) : null,
    base_level: baseLevel, min_level: Math.min(min ?? baseLevel, baseLevel), reachable,
    estimated: !Object.values(levels).every(row => row.measured), levels,
  };
}
