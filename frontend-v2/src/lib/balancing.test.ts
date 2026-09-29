import { describe, expect, it } from "vitest";
import { calculate, newRoom, recommendedLevel, sizingPatch, status, type Room, type RoomType } from "./balancing";

function room(type: RoomType, area: number, extra: Partial<Room> = {}): Room {
  return { ...newRoom(type, 2.5), area, name: `${type}-${area}`, ...extra };
}

const house = [room("living", 40), room("bedroom", 14), room("bedroom", 10), room("kitchen", 16), room("bathroom", 7), room("toilet", 3), room("hallway", 10)];

describe("balancing", () => {
  it("follows BR18: 0.3 l/s per m² supply, wet-room minimums for extract", () => {
    const r = calculate(house);
    expect(r.area).toBe(100);
    expect(r.areaRequirement).toBeCloseTo(30);
    expect(r.supplyTotal).toBeCloseTo(45 / 1.05);   // balanced against extract, 5 % underpressure
    expect(r.wetRequirement).toBe(45);           // 20 + 15 + 10
    expect(r.extractTotal).toBe(45);             // wet rooms decide here
    const living = r.rooms[0];
    expect(living.designSupply).toBeCloseTo((45 / 1.05) * 40 / 64);   // by area among supply rooms
    expect(calculate(house, 0).supplyTotal).toBeCloseTo(45);
    const kitchen = r.rooms[3];
    expect(kitchen.designExtract).toBeCloseTo(20);
    expect(r.rooms[6].designSupply + r.rooms[6].designExtract).toBe(0); // hallway: overflow only
  });

  it("shares extra extract above the minimums when the area needs more", () => {
    const big = [room("living", 150), room("kitchen", 20), room("bathroom", 8)];
    const r = calculate(big);
    expect(r.extractTotal).toBeCloseTo(53.4);    // 0.3 × 178
    const total = r.rooms.reduce((sum, x) => sum + x.designExtract, 0);
    expect(total).toBeCloseTo(53.4);
    expect(r.rooms[1].designExtract).toBeGreaterThan(20);
  });

  it("judges measurements with ±10 % / ±20 %", () => {
    expect(status(5)).toBe("ok");
    expect(status(-15)).toBe("warn");
    expect(status(30)).toBe("bad");
    const measured = house.map(r => ({ ...r, measured_supply: r.supply ? 0 : null, measured_extract: r.extract ? 0 : null }));
    const design = calculate(house);
    measured.forEach((r, i) => { r.measured_supply = r.supply ? design.rooms[i].designSupply : null; r.measured_extract = r.extract ? design.rooms[i].designExtract : null; });
    expect(calculate(measured).verdict).toBe("Godkendt");
    measured[0].measured_supply = null;
    expect(calculate(measured).verdict).toBe("Mangler målinger");
  });

  it("recommends the lowest level that covers the design and derives house sizing", () => {
    const r = calculate(house);
    const levels = { "1": { supply_m3h: 90, extract_m3h: 100 }, "2": { supply_m3h: 120, extract_m3h: 170 }, "3": { supply_m3h: 160, extract_m3h: 190 } };
    expect(recommendedLevel(r, levels)).toBe(3);   // needs 154 / 162 m³/h
    expect(sizingPatch(house)).toMatchObject({ house_area_m2: 100, ceiling_height_m: 2.5, house_bathrooms: 1, house_utility_rooms: 1 });
  });
});
