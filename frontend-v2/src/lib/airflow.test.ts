import { describe, expect, it } from "vitest";
import { airflowPlan, balancedProfiles, ductRatio, sideConstants } from "./airflow";

const profiles = { "1": { supply: 13, extract: 25 }, "2": { supply: 28, extract: 40 }, "3": { supply: 43, extract: 55 }, "4": { supply: 58, extract: 70 }, "5": { supply: 73, extract: 85 }, "6": { supply: 88, extract: 100 } };
const house = { house_area_m2: 150, ceiling_height_m: 2.5, house_bathrooms: 1, house_utility_rooms: 1, airflow_max_m3h: 375, sizing_reduced_percent: 50 };

describe("airflowPlan", () => {
  it("matches the controller for the default house", () => {
    const plan = airflowPlan(house, profiles)!;
    expect(plan.volume_m3).toBe(375);
    expect(plan.supply_required_m3h).toBe(162);
    expect(plan.base_level).toBe(3);
    expect(plan.min_level).toBe(1);
    expect(plan.levels["2"].supply_m3h).toBe(156);
    expect(plan.levels["3"].supply_m3h).toBe(202);
    expect(plan.fan_curve.learned).toBe(false);
  });
  it("uses the fan curve learned by the controller", () => {
    const plan = airflowPlan({ ...house, fan_curve: { rpm_at_0: 0, rpm_per_percent: 30, samples: 5 } }, profiles)!;
    expect(plan.fan_curve.learned).toBe(true);
    expect(plan.levels["3"].supply_m3h).toBe(161);
    expect(plan.base_level).toBe(4);
  });
  it("follows the house size while typing", () => {
    expect(airflowPlan({ ...house, house_area_m2: 110 }, profiles)!.base_level).toBe(2);
    expect(airflowPlan({ ...house, house_area_m2: 250 }, profiles)!.base_level).toBe(5);
  });
  it("uses measured airflow and lets it correct the estimate on the other levels", () => {
    const plan = airflowPlan({ ...house, airflow_measured: { "3": { supply: 170, extract: 210 } } }, profiles)!;
    expect(plan.levels["3"].supply_m3h).toBe(170);
    expect(plan.levels["3"].measured).toBe(true);
    // One measured point per side fixes the airflow per rpm: level 2 scales with it.
    expect(plan.levels["2"].supply_m3h).toBe(131);
    expect(plan.levels["2"].measured).toBe(false);
    expect(plan.base_level).toBe(3);
  });
});

describe("air balance", () => {
  const curve = { rpm_at_0: 557, rpm_per_percent: 24, samples: 6 };
  const ladder = { "1": { supply: 13, extract: 25 }, "2": { supply: 28, extract: 40 }, "3": { supply: 43, extract: 55 }, "4": { supply: 58, extract: 70 }, "5": { supply: 73, extract: 85 }, "6": { supply: 88, extract: 100 } };

  it("matches the controller ladder for the reference house", () => {
    const data = { ...house, house_area_m2: 180, ceiling_height_m: 2.3, fan_curve: curve, balance_enabled: true, balance_ratio_mode: "fixed", balance_duct_ratio: 1.14, profiles: ladder };
    const balanced = balancedProfiles(data, ladder)!;
    expect(Object.values(balanced).map(row => row.supply)).toEqual([17, 30, 42, 55, 67, 80]);
    for (const row of Object.values(balanced)) expect(Math.abs(row.excess_percent - 5)).toBeLessThanOrEqual(1.5);
    expect(airflowPlan(data, ladder)!.base_level).toBe(3);
  });

  it("keeps the old plan with alike ducts and no balance", () => {
    const plan = airflowPlan({ ...house, profiles }, profiles)!;
    expect(plan.levels["3"].supply_m3h).toBe(202);
    expect(plan.duct_ratio).toBe(1);
    expect(plan.duct_ratio_source).toBe("fixed");
  });

  it("uses the learned ratio once the controller trusts it", () => {
    const learned = (inUse: number | null) => ({ ...house, profiles, balance_learned: { confidence: "low", ratio: 1.15, ratio_in_use: inUse } });
    expect(ductRatio(learned(null)).source).toBe("fixed");
    expect(ductRatio(learned(1.15))).toEqual({ ratio: 1.15, source: "learned" });
    expect(ductRatio({ ...learned(1.15), balance_ratio_mode: "fixed", balance_duct_ratio: 1.05 })).toEqual({ ratio: 1.05, source: "fixed" });
  });

  it("fits both sides from measured airflow at the stamped percentage", () => {
    const data = { ...house, profiles, airflow_measured: { "3": { supply: 230, supply_percent: 43, extract: 205, extract_percent: 55 } } };
    const k = sideConstants(data, profiles);
    expect(k.source).toBe("measured");
    expect(k.ratio).toBeCloseTo((230 / (557 + 24 * 43)) / (205 / (557 + 24 * 55)), 4);
    const plan = airflowPlan({ ...data, balance_enabled: true }, profiles)!;
    expect(plan.levels["3"].extract_m3h).toBe(205);
    expect(plan.levels["3"].measured).toBe(true);
  });
});
