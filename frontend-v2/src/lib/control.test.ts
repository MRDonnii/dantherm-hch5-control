import { describe, expect, it } from "vitest";
import { describeControl } from "./control";

describe("describeControl", () => {
  it("explains Smart Auto driven by the unit's own CO2 sensor", () => {
    const c = describeControl({ active_master: "pi", effective_source: "ha_smart", effective_level: 4, effective_reason: "CO2 HCH5 / lokale sensorer 722 (auto)" });
    expect(c.title).toBe("Smart Auto");
    expect(c.level).toBe(4);
    expect(c.reason).toBe("CO₂ 722 ppm ved anlæggets egen føler");
    expect(c.footer).toBe("Pi styrer");
  });

  it("translates room humidity, rise and hold reasons", () => {
    expect(describeControl({ active_master: "pi", effective_source: "ha_smart", effective_level: 5, effective_reason: "Badeværelse RH Badeværelse 71.5% / 65% (high); Boost hold" }).reason)
      .toBe("Fugt 71,5 % i Badeværelse (grænse 65 %); holder boost");
    expect(describeControl({ active_master: "pi", effective_source: "ha_smart", effective_level: 6, effective_reason: "RH rise Badeværelse +8.2%/10m (high)" }).reason)
      .toBe("Fugten stiger 8,2 % på 10 min i Badeværelse");
    const night = describeControl({ active_master: "pi", effective_source: "night_air_quality", effective_level: 3, effective_reason: "CO2 Soveværelse 1040 (high); nat: luftkvalitet begrænset til trin 4; Downshift delay" });
    expect(night.title).toBe("Nat · luftkvalitet");
    expect(night.tone).toBe("reduced");
    expect(night.reason).toBe("CO₂ 1040 ppm i Soveværelse; nat: luftkvalitet begrænset til trin 4; venter før nedgang");
  });

  it("says when HCP4 or the fireplace takes over", () => {
    expect(describeControl({ active_master: "hcp4", effective_source: "ha_smart", effective_level: 3 }).title).toBe("HCP4-panelet styrer");
    const fire = describeControl({ active_master: "pi", fireplace: true, fireplace_auto_active: true, effective_level: 3 });
    expect(fire.title).toBe("Pejsefunktion");
    expect(fire.tone).toBe("boost");
  });
});
