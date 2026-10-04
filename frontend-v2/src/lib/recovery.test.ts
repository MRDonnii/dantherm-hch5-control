import { describe, expect, it } from "vitest";
import { t2ahRecoveryPercent } from "./recovery";

describe("T2AH exchanger reading", () => {
  it("uses measured T2AH when afterheat is off", () => {
    expect(t2ahRecoveryPercent(12.62, 23.17, 21.71, true, false, false)).toBe(86);
  });

  it("does not attribute afterheat or bypass heat to the exchanger", () => {
    expect(t2ahRecoveryPercent(0, 20, 21, true, true, false)).toBeNull();
    expect(t2ahRecoveryPercent(0, 20, 19, true, false, true)).toBeNull();
    expect(t2ahRecoveryPercent(0, 20, 19, false, false, false)).toBeNull();
  });

  it("withholds an unreliable small-span or impossible reading", () => {
    expect(t2ahRecoveryPercent(18, 20, 19, true, false, false)).toBeNull();
    expect(t2ahRecoveryPercent(0, 20, 22, true, false, false)).toBeNull();
  });
});
