import { describe, expect, it } from "vitest";
import { balancedProfiles } from "./airflow";
import { danthermLadder, fanSettingsError, levelList, stepCount } from "./fanSteps";

describe("Dantherm fan steps", () => {
  it("derives steps 1, 2 and 4 from step 3 like the HCP4 panel", () => {
    const steps = danthermLadder({ supply: 46, extract: 91, offset: 25, max_supply: 90, max_extract: 100 });
    expect(Object.fromEntries(Object.entries(steps).map(([level, p]) => [level, [p.supply, p.extract]])))
      .toEqual({ 1: [1, 41], 2: [21, 66], 3: [46, 91], 4: [90, 100] });
  });

  it("balances every step the same way as the controller", () => {
    const data = { fan_curve: { rpm_at_0: 557, rpm_per_percent: 24 }, balance_ratio_mode: "fixed", balance_duct_ratio: 1.14, balance_extract_excess_percent: 5 };
    const balanced = balancedProfiles(data, danthermLadder({ supply: 55, extract: 70, offset: 25, max_supply: 100, max_extract: 100 }))!;
    expect(Object.values(balanced).map(row => [row.supply, row.extract])).toEqual([[13, 20], [34, 45], [55, 70], [80, 100]]);
  });

  it("knows the step count, also for controllers from before the choice", () => {
    expect(levelList({ fan_step_count: 4 })).toEqual([1, 2, 3, 4]);
    expect(stepCount({})).toBe(6);
    expect(stepCount({ max_level: 4 })).toBe(4);
  });

  it("uses the service manual ranges", () => {
    const ok = { supply: 55, extract: 70, offset: 25, max_supply: 100, max_extract: 100 };
    expect(fanSettingsError(ok, "da")).toBeNull();
    expect(fanSettingsError({ ...ok, extract: 45 }, "da")).toMatch(/46\.\.91/);
    expect(fanSettingsError({ ...ok, offset: 31 }, "da")).toMatch(/10\.\.30/);
    expect(fanSettingsError({ ...ok, max_supply: 50 }, "da")).toMatch(/trin 4/);
  });
});
