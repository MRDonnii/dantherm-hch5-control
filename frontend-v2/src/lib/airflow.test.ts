import { describe, expect, it } from "vitest";
import { airflowPlan } from "./airflow";

const profiles = { "1": { supply: 13, extract: 25 }, "2": { supply: 28, extract: 40 }, "3": { supply: 43, extract: 55 }, "4": { supply: 58, extract: 70 }, "5": { supply: 73, extract: 85 }, "6": { supply: 88, extract: 100 } };
const house = { house_area_m2: 150, ceiling_height_m: 2.5, house_bathrooms: 1, house_utility_rooms: 1, airflow_max_m3h: 375, sizing_reduced_percent: 50 };

describe("airflowPlan", () => {
  it("matches the controller for the default house", () => {
    const plan = airflowPlan(house, profiles)!;
    expect(plan.volume_m3).toBe(375);
    expect(plan.supply_required_m3h).toBe(162);
    expect(plan.base_level).toBe(4);
    expect(plan.min_level).toBe(2);
    expect(plan.levels["3"].supply_m3h).toBe(161);
  });
  it("follows the house size while typing", () => {
    expect(airflowPlan({ ...house, house_area_m2: 110 }, profiles)!.base_level).toBe(3);
    expect(airflowPlan({ ...house, house_area_m2: 250 }, profiles)!.base_level).toBe(5);
  });
  it("uses measured airflow and keeps the estimate for the placeholder", () => {
    const plan = airflowPlan({ ...house, airflow_measured: { "3": { supply: 170, extract: 210 } } }, profiles)!;
    expect(plan.levels["3"].supply_m3h).toBe(170);
    expect(plan.levels["3"].estimate_supply_m3h).toBe(161);
    expect(plan.base_level).toBe(3);
  });
});
