import { describe, expect, it } from "vitest";
import { TEMPLATES, cloneWeek, overlaps, segments, snap, toTime, wrapsMidnight, type WeekPeriods } from "./schedule";

describe("week schedule helpers", () => {
  it("draws a period past midnight on the next day", () => {
    const week = cloneWeek({ "4": [{ start: "22:00", end: "02:00", level: 5, mode: "set", label: "Fest" }] } as WeekPeriods);
    const rows = segments(week);
    expect(rows[4]).toMatchObject([{ from: 1320, to: 1440, continued: false }]);
    expect(rows[5]).toMatchObject([{ from: 0, to: 120, continued: true, day: 4 }]);
    expect(wrapsMidnight(week["4"][0])).toBe(true);
  });

  it("treats an end at 00:00 as the end of the same day", () => {
    const week = cloneWeek({ "0": [{ start: "20:00", end: "00:00", level: 2, mode: "set", label: "" }] } as WeekPeriods);
    expect(segments(week)[0]).toMatchObject([{ from: 1200, to: 1440 }]);
    expect(segments(week)[1]).toEqual([]);
    expect(wrapsMidnight(week["0"][0])).toBe(false);
  });

  it("finds overlaps and snaps to 15 minutes", () => {
    const week = cloneWeek({ "0": [
      { start: "08:00", end: "12:00", level: 1, mode: "set", label: "" },
      { start: "11:00", end: "13:00", level: 4, mode: "min", label: "" },
      { start: "14:00", end: "15:00", level: 3, mode: "set", label: "" },
    ] } as WeekPeriods);
    expect(overlaps(week, 0, 0)).toBe(true);
    expect(overlaps(week, 0, 2)).toBe(false);
    expect(snap(452)).toBe(450);
    expect(toTime(1440)).toBe("00:00");
  });

  it("templates fill the working week", () => {
    const away = TEMPLATES.find(t => t.id === "away")!.build();
    expect(away["0"][0]).toMatchObject({ start: "08:00", end: "16:00", level: 1, mode: "set" });
    expect(away["6"]).toHaveLength(1);
  });
});
