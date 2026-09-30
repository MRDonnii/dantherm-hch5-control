// Live copy of gateway/fan_steps.py: Dantherm's four steps from one
// commissioning, or the free six-step table.
import type { AirflowProfiles } from "./airflow";

export const NOMINAL_RANGE = [46, 91] as const;
export const OFFSET_RANGE = [10, 30] as const;
export const OFFSET_DEFAULT = 25;
export const MAX_LEVEL_HOURS = 4;
export const LEVEL_NAMES: Record<number, { da: string; en: string }> = {
  1: { da: "Lav", en: "Low" },
  2: { da: "Reduceret", en: "Reduced" },
  3: { da: "Nominel", en: "Nominal" },
  4: { da: "Maksimum", en: "Maximum" },
};

export type FanSettings = { supply: number; extract: number; offset: number; max_supply: number; max_extract: number };
export const DEFAULT_FAN_SETTINGS: FanSettings = { supply: 64, extract: 64, offset: OFFSET_DEFAULT, max_supply: 100, max_extract: 100 };

const num = (value: unknown, fallback: number) => { const x = Number(value); return Number.isFinite(x) ? x : fallback; };

/** 4 or 6; controllers from before the choice ran six steps. */
export function stepCount(data: Record<string, unknown>): 4 | 6 {
  if (data.fan_step_count === 4 || data.fan_step_count === 6) return data.fan_step_count;
  return data.max_level === 4 ? 4 : 6;
}

/** The step numbers the controller runs. */
export function levelList(data: Record<string, unknown>): number[] {
  return Array.from({ length: stepCount(data) }, (_, index) => index + 1);
}

export function fanSettings(data: Record<string, unknown>): FanSettings {
  const raw = (data.fan_settings ?? {}) as Partial<Record<keyof FanSettings, unknown>>;
  return {
    supply: num(raw.supply, DEFAULT_FAN_SETTINGS.supply), extract: num(raw.extract, DEFAULT_FAN_SETTINGS.extract),
    offset: num(raw.offset, DEFAULT_FAN_SETTINGS.offset),
    max_supply: num(raw.max_supply, DEFAULT_FAN_SETTINGS.max_supply), max_extract: num(raw.max_extract, DEFAULT_FAN_SETTINGS.max_extract),
  };
}

/** Gear per step for both fans, as the HCP4 panel derives them. */
export function danthermLadder(settings: FanSettings): AirflowProfiles {
  const result: AirflowProfiles = {};
  for (const level of [1, 2, 3, 4]) {
    const gear = (side: "supply" | "extract") => level === 4 ? settings[`max_${side}`] : Math.max(1, settings[side] - (3 - level) * settings.offset);
    result[String(level)] = { supply: gear("supply"), extract: gear("extract"), name: LEVEL_NAMES[level].da };
  }
  return result;
}

/** Problems with a commissioning, in the words the controller uses. */
export function fanSettingsError(settings: FanSettings, lang: "da" | "en"): string | null {
  const [low, high] = NOMINAL_RANGE;
  const whole = Object.values(settings).every(value => Number.isInteger(value));
  if (!whole) return lang === "da" ? "Ventilatorgear skal være hele tal" : "Fan gears must be whole numbers";
  if (settings.offset < OFFSET_RANGE[0] || settings.offset > OFFSET_RANGE[1]) return lang === "da" ? `Gearafstanden skal være ${OFFSET_RANGE[0]}..${OFFSET_RANGE[1]} gear` : `The offset must be ${OFFSET_RANGE[0]}..${OFFSET_RANGE[1]} gears`;
  for (const side of ["extract", "supply"] as const) {
    const label = side === "supply" ? (lang === "da" ? "Indblæsning" : "Supply") : (lang === "da" ? "Udsugning" : "Extract");
    if (settings[side] < low || settings[side] > high) return lang === "da" ? `${label} på trin 3 skal være gear ${low}..${high}` : `${label} at step 3 must be gear ${low}..${high}`;
    if (settings[`max_${side}`] < settings[side] || settings[`max_${side}`] > 100) return lang === "da" ? `${label} på trin 4 skal være fra trin 3 op til gear 100` : `${label} at step 4 must be from step 3 up to gear 100`;
  }
  return null;
}

/** Steps before the air balance: the Dantherm ladder or the six-step table. */
export function baseProfiles(data: Record<string, unknown>): AirflowProfiles | undefined {
  if (stepCount(data) === 4) return danthermLadder(fanSettings(data));
  return (data.six_step_profiles ?? data.profiles) as AirflowProfiles | undefined;
}
