/**
 * Airflow balancing (indregulering) after BR18 §447, the same rules the
 * controller uses for the house size:
 *  - outdoor air at least 0.3 l/s per m² heated floor area (supply),
 *  - extract at least 20 l/s from a kitchen, 15 l/s from a bathroom and
 *    10 l/s from a separate WC or utility room, and never less than the
 *    area requirement.
 * The HCH5 is a balanced unit, so supply follows extract minus the
 * controller's air-balance setting (extract a few % above supply), and is
 * never below the area requirement.
 * Supply is shared between the supply rooms by floor area; extract between
 * the extract rooms by their minimum (or area for rooms without one).
 */
export type RoomType = "living" | "bedroom" | "office" | "kitchen" | "bathroom" | "toilet" | "utility" | "hallway" | "other";

export interface Room {
  id: string;
  name: string;
  type: RoomType;
  area: number;
  height: number;
  supply: boolean;
  extract: boolean;
  measured_supply: number | null;
  measured_extract: number | null;
  valve_supply: string;
  valve_extract: string;
  note: string;
}

export interface Meta { site: string; address: string; owner: string; technician: string; company: string; instrument: string; notes: string }
export interface Project { rooms: Room[]; meta: Meta; measure_level: number | null; updated_at?: number; updated_by?: string | null }

export const AREA_LS_PER_M2 = 0.3;
export const LS_TO_M3H = 3.6;
/** Within ±10 % of the design flow is OK, within ±20 % a warning. */
export const TOLERANCE_OK = 10;
export const TOLERANCE_WARN = 20;

export const ROOM_TYPES: Record<RoomType, { label: string; extractMin: number; supply: boolean; extract: boolean }> = {
  living: { label: "Stue / opholdsrum", extractMin: 0, supply: true, extract: false },
  bedroom: { label: "Soveværelse", extractMin: 0, supply: true, extract: false },
  office: { label: "Kontor / værelse", extractMin: 0, supply: true, extract: false },
  kitchen: { label: "Køkken", extractMin: 20, supply: false, extract: true },
  bathroom: { label: "Bad", extractMin: 15, supply: false, extract: true },
  toilet: { label: "Separat toilet", extractMin: 10, supply: false, extract: true },
  utility: { label: "Bryggers", extractMin: 10, supply: false, extract: true },
  hallway: { label: "Gang / entré", extractMin: 0, supply: false, extract: false },
  other: { label: "Andet", extractMin: 0, supply: false, extract: false },
};

export function emptyMeta(): Meta {
  return { site: "", address: "", owner: "", technician: "", company: "", instrument: "", notes: "" };
}

export function newRoom(type: RoomType = "living", height = 2.5): Room {
  const kind = ROOM_TYPES[type];
  return {
    id: Math.random().toString(16).slice(2, 10), name: kind.label.split(" /")[0], type, area: 12, height,
    supply: kind.supply, extract: kind.extract, measured_supply: null, measured_extract: null,
    valve_supply: "", valve_extract: "", note: "",
  };
}

export interface RoomResult {
  room: Room;
  volume: number;
  designSupply: number;   // l/s
  designExtract: number;  // l/s
  supplyDeviation: number | null;  // % from design
  extractDeviation: number | null;
  supplyStatus: Status;
  extractStatus: Status;
}
export type Status = "ok" | "warn" | "bad" | "none";

export interface Result {
  rooms: RoomResult[];
  area: number;
  volume: number;
  areaRequirement: number;     // l/s
  wetRequirement: number;      // l/s
  supplyTotal: number;         // l/s design
  extractExcess: number;       // % more extract than supply
  extractTotal: number;        // l/s design
  measuredSupply: number | null;
  measuredExtract: number | null;
  airChanges: number | null;   // per hour, design supply
  measuredAirChanges: number | null;
  warnings: string[];
  verdict: "Godkendt" | "Godkendt med bemærkninger" | "Ikke godkendt" | "Mangler målinger" | "Ikke målt";
}

export function deviation(measured: number | null, design: number): number | null {
  if (measured === null || measured === undefined || !Number.isFinite(measured) || design <= 0) return null;
  return ((measured - design) / design) * 100;
}

export function status(dev: number | null): Status {
  if (dev === null) return "none";
  const size = Math.abs(dev);
  return size <= TOLERANCE_OK ? "ok" : size <= TOLERANCE_WARN ? "warn" : "bad";
}

export function calculate(rooms: Room[], extractExcessPercent = 5): Result {
  const area = rooms.reduce((sum, r) => sum + (r.area || 0), 0);
  const volume = rooms.reduce((sum, r) => sum + (r.area || 0) * (r.height || 0), 0);
  const areaRequirement = area * AREA_LS_PER_M2;
  const extractRooms = rooms.filter(r => r.extract);
  const supplyRooms = rooms.filter(r => r.supply);
  const wetRequirement = extractRooms.reduce((sum, r) => sum + ROOM_TYPES[r.type].extractMin, 0);
  const extractTotal = Math.max(areaRequirement, wetRequirement);
  const excess = Math.min(20, Math.max(0, extractExcessPercent));
  const supplyTotal = Math.max(areaRequirement, extractTotal / (1 + excess / 100));
  const supplyWeight = supplyRooms.reduce((sum, r) => sum + r.area, 0);
  const extractWeight = (r: Room) => Math.max(ROOM_TYPES[r.type].extractMin, r.area * AREA_LS_PER_M2);
  const extractWeights = extractRooms.reduce((sum, r) => sum + extractWeight(r), 0);
  // Each extract room gets at least its minimum; the rest is shared by weight.
  const minimums = extractRooms.reduce((sum, r) => sum + ROOM_TYPES[r.type].extractMin, 0);
  const surplus = Math.max(0, extractTotal - minimums);

  const results: RoomResult[] = rooms.map(room => {
    const designSupply = room.supply && supplyWeight > 0 ? supplyTotal * (room.area / supplyWeight) : 0;
    const designExtract = room.extract && extractWeights > 0
      ? ROOM_TYPES[room.type].extractMin + surplus * (extractWeight(room) / extractWeights)
      : 0;
    const supplyDeviation = room.supply ? deviation(room.measured_supply, designSupply) : null;
    const extractDeviation = room.extract ? deviation(room.measured_extract, designExtract) : null;
    return {
      room, volume: room.area * room.height, designSupply, designExtract,
      supplyDeviation, extractDeviation, supplyStatus: status(supplyDeviation), extractStatus: status(extractDeviation),
    };
  });

  const sum = (values: (number | null)[]) => values.every(v => v !== null && v !== undefined) && values.length ? values.reduce<number>((a, b) => a + (b as number), 0) : null;
  const measuredSupply = sum(supplyRooms.map(r => r.measured_supply));
  const measuredExtract = sum(extractRooms.map(r => r.measured_extract));

  const warnings: string[] = [];
  if (!rooms.length) warnings.push("Tilføj husets rum for at beregne luftmængderne.");
  if (rooms.length && !supplyRooms.length) warnings.push("Ingen rum har indblæsning. Stuer og soveværelser har normalt indblæsning.");
  if (rooms.length && !extractRooms.length) warnings.push("Ingen rum har udsugning. Køkken, bad, toilet og bryggers skal have udsugning.");
  if (!rooms.some(r => r.type === "kitchen")) warnings.push("Der er intet køkken i listen. BR18 kræver 20 l/s udsugning fra køkkenet.");
  for (const r of rooms) {
    if (ROOM_TYPES[r.type].extractMin > 0 && !r.extract) warnings.push(`${r.name}: vådrum og køkken skal have udsugning (mindst ${ROOM_TYPES[r.type].extractMin} l/s).`);
  }

  const measured = results.filter(r => r.supplyStatus !== "none" || r.extractStatus !== "none");
  const expected = results.reduce((n, r) => n + (r.room.supply ? 1 : 0) + (r.room.extract ? 1 : 0), 0);
  const statuses = results.flatMap(r => [r.room.supply ? r.supplyStatus : null, r.room.extract ? r.extractStatus : null]).filter(Boolean) as Status[];
  let verdict: Result["verdict"] = "Ikke målt";
  if (measured.length && expected) {
    if (statuses.includes("bad")) verdict = "Ikke godkendt";
    else if (statuses.includes("none")) verdict = "Mangler målinger";
    else if (statuses.includes("warn")) verdict = "Godkendt med bemærkninger";
    else verdict = "Godkendt";
    if (measuredExtract !== null && measuredExtract + 0.5 < wetRequirement) verdict = "Ikke godkendt";
  }

  return {
    rooms: results, area, volume, areaRequirement, wetRequirement, supplyTotal, extractTotal, extractExcess: excess,
    measuredSupply, measuredExtract,
    airChanges: volume ? (supplyTotal * LS_TO_M3H) / volume : null,
    measuredAirChanges: volume && measuredSupply !== null ? (measuredSupply * LS_TO_M3H) / volume : null,
    warnings, verdict,
  };
}

export type LevelPlan = Record<string, { supply_m3h?: number; extract_m3h?: number; measured?: boolean }>;

/** Lowest fan level whose (estimated or measured) airflow covers the design. */
export function recommendedLevel(result: Result, levels: LevelPlan | undefined): number | null {
  if (!levels || !result.rooms.length) return null;
  for (let level = 1; level <= 6; level += 1) {
    const entry = levels[String(level)];
    if (!entry) continue;
    if ((entry.supply_m3h ?? 0) >= result.supplyTotal * LS_TO_M3H && (entry.extract_m3h ?? 0) >= result.extractTotal * LS_TO_M3H) return level;
  }
  return 6;
}

/** Values for Indstillinger → Hus og luftmængde derived from the rooms. */
export function sizingPatch(rooms: Room[]) {
  const area = rooms.reduce((sum, r) => sum + r.area, 0);
  const volume = rooms.reduce((sum, r) => sum + r.area * r.height, 0);
  const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
  return {
    sizing_enabled: true,
    house_area_m2: Math.round(clamp(area, 20, 1000) * 10) / 10,
    ceiling_height_m: Math.round(clamp(area ? volume / area : 2.5, 1.8, 6) * 100) / 100,
    house_bathrooms: Math.min(10, rooms.filter(r => r.type === "bathroom").length),
    house_utility_rooms: Math.min(10, rooms.filter(r => r.type === "toilet" || r.type === "utility").length),
  };
}

export const fmt = (value: number | null | undefined, digits = 1) =>
  value === null || value === undefined || !Number.isFinite(value) ? "—" : value.toLocaleString("da-DK", { maximumFractionDigits: digits, minimumFractionDigits: digits });
