import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Droplets, Flame, Gauge, House, Monitor, Moon, Save, ShieldCheck, Snowflake, Thermometer, Wind } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { postJson, requestJson } from "../lib/api";
import { airflowPlan, type AirflowProfiles } from "../lib/airflow";
import { LANG_KEY, currentLang, useLang, type Lang } from "../lib/i18n";
import "../styles/panels.css";import "../styles/management.css";

type Data = Record<string, unknown>;
type Auth = { csrf?: string | null; enabled?: boolean; username?: string | null };
type Text = { da: string; en: string };
type LevelPlan = { estimate_supply_m3h?: number; estimate_extract_m3h?: number; supply_m3h?: number; extract_m3h?: number; air_changes_per_hour?: number | null; measured?: boolean; meets_requirement?: boolean; meets_reduced?: boolean };
type Plan = { volume_m3?: number; supply_required_m3h?: number; extract_required_m3h?: number; area_requirement_ls?: number; wet_room_requirement_ls?: number; required_air_changes_per_hour?: number | null; base_level?: number; min_level?: number; reachable?: boolean; estimated?: boolean; levels?: Record<string, LevelPlan> };
type Airflow = Record<string, { supply?: number; extract?: number }>;

function n(v: unknown, f: number) { const x = Number(v); return Number.isFinite(x) ? x : f; }
function s(v: unknown, f = "") { return v === null || v === undefined ? f : String(v); }
function fmt(v: unknown, lang: Lang, digits = 1, unit = "") {
  const x = typeof v === "number" ? v : Number.NaN;
  return Number.isFinite(x) ? `${x.toLocaleString(lang === "en" ? "en-GB" : "da-DK", { maximumFractionDigits: digits })}${unit}` : "—";
}

/** Every controller field this page edits. UI-only preferences stay in localStorage. */
export const CONTROLLER_KEYS = [
  "local_normal_level", "rh_setpoint", "rh_hysteresis", "co2_setpoint", "co2_hysteresis", "co2_offset", "ha_timeout_seconds",
  "bathroom_rh_setpoint", "bathroom_rh_hysteresis", "bathroom_max_level",
  "night_enabled", "night_start", "night_end", "night_level", "night_air_quality_max_level",
  "afterheat_setpoint", "afterheat_coil", "afterheat_room_enabled", "afterheat_room_source", "afterheat_room_target",
  "afterheat_room_gain", "afterheat_room_min", "afterheat_room_max", "afterheat_room_step_minutes",
  "cooling_enabled", "cooling_room_setpoint", "cooling_hysteresis", "cooling_outdoor_min", "cooling_min_delta",
  "cooling_level", "cooling_start_delay_seconds", "cooling_min_on_seconds", "cooling_min_off_seconds",
  "sizing_enabled", "house_area_m2", "ceiling_height_m", "house_bathrooms", "house_utility_rooms",
  "airflow_max_m3h", "sizing_reduced_percent", "airflow_measured",
  "humidity_smart_enabled", "outdoor_humidity_source", "humidity_margin_gm3",
  "dry_protection_enabled", "dry_rh_limit", "dry_max_level",
  "fireplace_auto_enabled", "fireplace_auto_source", "fireplace_auto_on_temp", "fireplace_auto_off_temp",
  "fireplace_afterrun_minutes", "fireplace_max_hours",
] as const;

const T = {
  eyebrow: { da: "INDSTILLINGER", en: "SETTINGS" },
  title: { da: "Controller og brugerflade", en: "Controller and interface" },
  intro: { da: "Vælg et område til venstre. Hvert felt forklarer, hvad det styrer, og hvad der sker, hvis du ændrer det.", en: "Pick an area on the left. Every field explains what it controls and what happens when you change it." },
  saveHint: { da: "Ændringer gemmes først, når du trykker Gem controller.", en: "Changes are stored only when you press Save controller." },
  save: { da: "Gem controller", en: "Save controller" }, saving: { da: "Gemmer…", en: "Saving…" },
  saved: { da: "Indstillinger gemt.", en: "Settings saved." }, error: { da: "Fejl", en: "Error" },
  uiSaved: { da: "Brugerflade gemt.", en: "Interface saved." }, saveUi: { da: "Gem brugerflade", en: "Save interface" },
  on: { da: "Til", en: "On" }, off: { da: "Fra", en: "Off" }, none: { da: "Ingen valgt", en: "None selected" },
  level: { da: "Trin", en: "Level" }, status: { da: "Status lige nu", en: "Status right now" },
} satisfies Record<string, Text>;

type SectionId = "ui" | "house" | "air" | "humidity" | "night" | "afterheat" | "cooling" | "fireplace" | "security";
const SECTIONS: { id: SectionId; icon: LucideIcon; title: Text; lead: Text }[] = [
  { id: "house", icon: House, title: { da: "Hus og luftmængde", en: "House and airflow" }, lead: { da: "Grundtrin beregnet ud fra boligens størrelse", en: "Base level calculated from the size of the home" } },
  { id: "air", icon: Wind, title: { da: "Luftkvalitet", en: "Air quality" }, lead: { da: "Fugt og CO₂ løfter ventilationen", en: "Humidity and CO₂ raise the ventilation" } },
  { id: "humidity", icon: Droplets, title: { da: "Fugt og tør luft", en: "Moisture and dry air" }, lead: { da: "Ventilér kun når det faktisk tørrer", en: "Only ventilate when it actually dries" } },
  { id: "night", icon: Moon, title: { da: "Nat", en: "Night" }, lead: { da: "Lavere trin mens I sover", en: "Lower level while you sleep" } },
  { id: "afterheat", icon: Thermometer, title: { da: "Eftervarme", en: "Afterheat" }, lead: { da: "Indblæsningens temperatur", en: "Supply air temperature" } },
  { id: "cooling", icon: Snowflake, title: { da: "Frikøling", en: "Free cooling" }, lead: { da: "Køl huset med kølig udeluft via bypass", en: "Cool the house with cool outdoor air via bypass" } },
  { id: "fireplace", icon: Flame, title: { da: "Pejs og brændeovn", en: "Fireplace and stove" }, lead: { da: "Overtryk mens der fyres", en: "Positive pressure while the stove burns" } },
  { id: "ui", icon: Monitor, title: { da: "Brugerflade", en: "Interface" }, lead: { da: "Sprog, tema og bevægelse", en: "Language, theme and motion" } },
  { id: "security", icon: ShieldCheck, title: { da: "Sikkerhed", en: "Security" }, lead: { da: "Login og hvem der styrer anlægget", en: "Login and who controls the unit" } },
];

function Card({ title, lead, icon: Icon, children }: { title: string; lead?: string; icon?: LucideIcon; children: ReactNode }) {
  return <article className="surface panel-card settings-card"><div className="pro-card-head compact"><div><h2>{title}</h2>{lead && <p>{lead}</p>}</div>{Icon && <Icon size={20}/>}</div>{children}</article>;
}

/** Deep link: #/settings?section=afterheat (HashRouter keeps the query in the hash). */
function initialSection(): SectionId {
  const wanted = new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("section");
  return SECTIONS.some(item => item.id === wanted) ? wanted as SectionId : "house";
}

function Help({ children }: { children: ReactNode }) { return <small className="settings-field-help">{children}</small>; }

export function SettingsPage() {
  const lang = useLang();
  const t = (text: Text) => text[lang];
  const [controller, setController] = useState<Data>({});
  const [auth, setAuth] = useState<Auth>({});
  const [csrf, setCsrf] = useState("");
  const [form, setForm] = useState<Data>({});
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [section, setSection] = useState<SectionId>(initialSection);
  const [theme, setTheme] = useState(() => localStorage.getItem("hch5-v2-theme") ?? "dark");
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("hch5-v2-sidebar") === "1");
  const [motion, setMotion] = useState(() => localStorage.getItem("hch5-v2-motion") ?? "normal");
  const [language, setLanguage] = useState<Lang>(currentLang);

  const refresh = useCallback(async () => {
    const [c, a] = await Promise.all([requestJson<Data>("/api/controller/state"), requestJson<Auth>("/api/auth/status")]);
    setController(c); setForm(c); setAuth(a); setCsrf(a.csrf ?? "");
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const set = (key: string, value: unknown) => setForm(v => ({ ...v, [key]: value }));
  const num = (key: string) => (e: { target: { value: string } }) => set(key, Number(e.target.value));
  const check = (key: string) => (e: { target: { checked: boolean } }) => set(key, e.target.checked);
  const save = async () => {
    if (!csrf) return;
    setBusy(true); setNotice(t(T.saving));
    const patch = Object.fromEntries(CONTROLLER_KEYS.filter(k => form[k] !== undefined).map(k => [k, form[k]]));
    try { const next = await postJson<Data>("/api/controller/config", patch, csrf); setController(next); setForm(next); setNotice(t(T.saved)); }
    catch (e) { setNotice(`${t(T.error)}: ${e instanceof Error ? e.message : "?"}`); }
    finally { setBusy(false); }
  };
  const uiSave = () => {
    localStorage.setItem("hch5-v2-theme", theme); localStorage.setItem("hch5-v2-sidebar", collapsed ? "1" : "0");
    localStorage.setItem("hch5-v2-motion", motion); localStorage.setItem(LANG_KEY, language);
    document.documentElement.dataset.motion = motion; document.documentElement.lang = language;
    window.dispatchEvent(new Event("hch5-ui-preferences"));
    setNotice(language === "en" ? T.uiSaved.en : T.uiSaved.da);
  };

  const rooms = Array.isArray(controller.measurement_rooms) ? controller.measurement_rooms.map(String) : [];
  const roomOptions = (current: unknown) => {
    const names = new Set(rooms); const selected = s(current);
    if (selected.startsWith("room:")) names.add(selected.slice(5));
    return [...names].sort().map(name => <option key={name} value={`room:${name}`}>{name}</option>);
  };
  const roomHint = rooms.length ? null : <Help>{lang === "da" ? "Ingen målerum modtaget fra Home Assistant endnu. Tilføj rummet i HCH PassiveLink-integrationen (Smart Auto-rum) med styring slået fra." : "No measurement rooms received from Home Assistant yet. Add the room in the HCH PassiveLink integration (Smart Auto rooms) with control turned off."}</Help>;

  const plan = (airflowPlan(form, controller.profiles as AirflowProfiles | undefined) ?? controller.airflow_plan ?? {}) as Plan;
  const airflow = (form.airflow_measured ?? {}) as Airflow;
  const setAirflow = (level: number, side: "supply" | "extract", value: string) => {
    const next: Airflow = { ...airflow, [level]: { ...(airflow[level] ?? {}), [side]: value === "" ? undefined : Number(value) } };
    set("airflow_measured", next);
  };
  const sizing = form.sizing_enabled === true;

  const sections: Record<SectionId, ReactNode> = {
    house: <>
      <Card title={t(SECTIONS[0].title)} lead={lang === "da" ? "Bygningsreglementet (BR18) kræver mindst 0,3 l/s pr. m² plus udsugning fra køkken og vådrum." : "The Danish building regulations (BR18) require at least 0.3 l/s per m² plus extract from kitchen and wet rooms."} icon={House}>
        <div className="settings-grid">
          <div className="settings-mode-row"><span>{lang === "da" ? "Grundtrin" : "Base level"}</span>
            <div className="settings-segment" role="radiogroup" aria-label={lang === "da" ? "Grundtrin" : "Base level"}>
              <button type="button" role="radio" aria-checked={sizing} className={sizing ? "is-active" : undefined} onClick={() => set("sizing_enabled", true)}>{lang === "da" ? "Auto" : "Auto"}</button>
              <button type="button" role="radio" aria-checked={!sizing} className={!sizing ? "is-active" : undefined} onClick={() => set("sizing_enabled", false)}>{lang === "da" ? "Manuel" : "Manual"}</button>
            </div>
            {sizing
              ? <strong>{lang === "da" ? `Trin ${s(plan.base_level, "—")} fra husets størrelse, laveste trin ${s(plan.min_level, "—")}` : `Level ${s(plan.base_level, "—")} from the house size, lowest level ${s(plan.min_level, "—")}`}</strong>
              : <label className="settings-inline">{lang === "da" ? "Normaltrin" : "Normal level"}<input type="number" min="1" max="6" value={n(form.local_normal_level, 3)} onChange={num("local_normal_level")}/></label>}
          </div>
          <Help>{lang === "da" ? "Auto: controlleren bruger det beregnede grundtrin i stedet for Normaltrin, og nat, ferie og tør luft kan aldrig gå under det reducerede minimum. Manuel: du vælger selv Normaltrin, og beregningen er kun vejledende. Manuel ventilatordrift påvirkes ikke." : "Auto: the controller uses the calculated base level instead of Normal level, and night, vacation and dry-air protection can never go below the reduced minimum. Manual: you pick Normal level yourself and the calculation is advisory only. Manual fan mode is not affected."}</Help>
          <label>{lang === "da" ? "Opvarmet boligareal" : "Heated floor area"}<input type="number" min="20" max="1000" step="1" value={n(form.house_area_m2, 150)} onChange={num("house_area_m2")}/><span>m²</span><Help>{lang === "da" ? "Fra BBR eller tegningen. Kravet er 0,3 l/s pr. m²." : "From the building register or drawings. The requirement is 0.3 l/s per m²."}</Help></label>
          <label>{lang === "da" ? "Loftshøjde" : "Ceiling height"}<input type="number" min="1.8" max="6" step="0.1" value={n(form.ceiling_height_m, 2.5)} onChange={num("ceiling_height_m")}/><span>m</span><Help>{lang === "da" ? "Bruges til husets luftvolumen og luftskifte pr. time." : "Used for the air volume and air changes per hour."}</Help></label>
          <label>{lang === "da" ? "Badeværelser" : "Bathrooms"}<input type="number" min="0" max="10" value={n(form.house_bathrooms, 1)} onChange={num("house_bathrooms")}/><Help>{lang === "da" ? "Hvert badeværelse kræver 15 l/s udsugning." : "Each bathroom needs 15 l/s extract."}</Help></label>
          <label>{lang === "da" ? "Bryggers og separate toiletter" : "Utility rooms and separate toilets"}<input type="number" min="0" max="10" value={n(form.house_utility_rooms, 1)} onChange={num("house_utility_rooms")}/><Help>{lang === "da" ? "10 l/s hver. Køkkenet (20 l/s) regnes altid med." : "10 l/s each. The kitchen (20 l/s) is always included."}</Help></label>
          <label>{lang === "da" ? "Anlæggets maks. luftmængde" : "Unit maximum airflow"}<input type="number" min="100" max="1500" value={n(form.airflow_max_m3h, 375)} onChange={num("airflow_max_m3h")}/><span>m³/h</span><Help>{lang === "da" ? "HCH5 er 375 m³/h ifølge databladet. Bruges til at skønne luftmængden på trin uden en målt værdi." : "HCH5 is 375 m³/h according to the datasheet. Used to estimate airflow for levels without a measured value."}</Help></label>
          <label>{lang === "da" ? "Reduceret minimum" : "Reduced minimum"}<input type="number" min="30" max="100" value={n(form.sizing_reduced_percent, 50)} onChange={num("sizing_reduced_percent")}/><span>%</span><Help>{lang === "da" ? "Laveste luftmængde i procent af kravet, som nat, ferie og tør luft må gå ned til." : "Lowest airflow, as a share of the requirement, that night, vacation and dry-air protection may use."}</Help></label>
        </div>
      </Card>
      <Card title={lang === "da" ? "Beregning" : "Calculation"} lead={lang === "da" ? "Følger felterne, mens du taster. Styringen bruger tallene, når du gemmer." : "Follows the fields as you type. Control uses them once you save."} icon={Gauge}>
        <div className="settings-summary">
          <span>{lang === "da" ? "Luftvolumen" : "Air volume"}<strong>{fmt(plan.volume_m3, lang, 0, " m³")}</strong></span>
          <span>{lang === "da" ? "Krav, indblæsning" : "Required supply"}<strong>{fmt(plan.supply_required_m3h, lang, 0, " m³/h")}</strong></span>
          <span>{lang === "da" ? "Krav, udsugning" : "Required extract"}<strong>{fmt(plan.extract_required_m3h, lang, 0, " m³/h")}</strong></span>
          <span>{lang === "da" ? "Luftskifte ved kravet" : "Air changes at requirement"}<strong>{fmt(plan.required_air_changes_per_hour, lang, 2, " /h")}</strong></span>
          <span>{lang === "da" ? "Beregnet grundtrin" : "Calculated base level"}<strong>{s(plan.base_level, "—")}</strong></span>
          <span>{lang === "da" ? "Laveste tilladte trin" : "Lowest allowed level"}<strong>{s(plan.min_level, "—")}</strong></span>
        </div>
        {plan.reachable === false && <p className="settings-warning">{lang === "da" ? "Selv trin 6 når ikke kravet med de nuværende tal. Tjek areal, maks. luftmængde eller indtast målte værdier." : "Even level 6 does not reach the requirement with the current figures. Check the area, maximum airflow or enter measured values."}</p>}
        {plan.estimated && <p className="settings-help">{lang === "da" ? "Luftmængder uden målt værdi er skønnet lineært ud fra ventilatorprocenten og ser bort fra kanaltrykket, så de er som regel for høje. Står der målte luftmængder i indreguleringsrapporten, skal de indtastes herunder." : "Airflows without a measured value are estimated linearly from the fan percentage and ignore duct pressure, so they are usually too high. If the commissioning report lists measured airflows, enter them below."}</p>}
        <div className="settings-table-wrap"><table className="settings-table"><thead><tr><th>{t(T.level)}</th><th>{lang === "da" ? "Indblæsning" : "Supply"}</th><th>{lang === "da" ? "Udsugning" : "Extract"}</th><th>{lang === "da" ? "Luftskifte" : "Air changes"}</th><th>{lang === "da" ? "Opfylder krav" : "Meets requirement"}</th><th>{lang === "da" ? "Målt indbl." : "Measured supply"}</th><th>{lang === "da" ? "Målt udsug." : "Measured extract"}</th></tr></thead>
          <tbody>{[1, 2, 3, 4, 5, 6].map(level => { const row = plan.levels?.[String(level)] ?? {}; return <tr key={level} className={level === plan.base_level ? "is-base" : undefined}>
            <td>{level}</td><td>{fmt(row.supply_m3h, lang, 0, " m³/h")}{row.measured ? "" : " *"}</td><td>{fmt(row.extract_m3h, lang, 0, " m³/h")}</td><td>{fmt(row.air_changes_per_hour, lang, 2)}</td>
            <td>{row.meets_requirement ? "✓" : row.meets_reduced ? (lang === "da" ? "Reduceret" : "Reduced") : "—"}</td>
            <td><input aria-label={`${t(T.level)} ${level} supply`} type="number" min="10" max="1500" placeholder={row.estimate_supply_m3h === undefined ? undefined : String(row.estimate_supply_m3h)} value={airflow[level]?.supply ?? ""} onChange={e => setAirflow(level, "supply", e.target.value)}/></td>
            <td><input aria-label={`${t(T.level)} ${level} extract`} type="number" min="10" max="1500" placeholder={row.estimate_extract_m3h === undefined ? undefined : String(row.estimate_extract_m3h)} value={airflow[level]?.extract ?? ""} onChange={e => setAirflow(level, "extract", e.target.value)}/></td>
          </tr>; })}</tbody></table></div>
        <p className="settings-help">{lang === "da" ? "* skønnet. De grå tal i felterne er skønnet; skriv den målte værdi fra indreguleringsrapporten for at erstatte det." : "* estimated. The grey numbers in the fields are the estimate; type the measured value from the commissioning report to replace it."}</p>
      </Card>
    </>,
    air: <>
      <Card title={lang === "da" ? "Generel luftkvalitet" : "General air quality"} lead={lang === "da" ? "Gælder Local Auto og Smart Auto" : "Applies to Local Auto and Smart Auto"} icon={Wind}>
        <div className="settings-grid">
          <label>{lang === "da" ? "Normaltrin" : "Normal level"}<input type="number" min="1" max="6" disabled={sizing} value={sizing ? n(controller.effective_normal_level, 3) : n(form.local_normal_level, 3)} onChange={num("local_normal_level")}/><Help>{sizing ? (lang === "da" ? "Styres lige nu af husets størrelse (se Hus og luftmængde)." : "Currently set by the house size (see House and airflow).") : (lang === "da" ? "Trinnet anlægget kører på, når luften er god." : "The level the unit runs at when the air is good.")}</Help></label>
          <label>{lang === "da" ? "Fugt (RH) grænse" : "Humidity (RH) limit"}<input type="number" min="25" max="80" value={n(form.rh_setpoint, 50)} onChange={num("rh_setpoint")}/><span>%</span><Help>{lang === "da" ? "Over denne relative fugt skrues der op. Et trin pr. 5 % over grænsen." : "Above this relative humidity the fans step up. One level per 5 % above the limit."}</Help></label>
          <label>{lang === "da" ? "Fugt hysterese" : "Humidity hysteresis"}<input type="number" min="1" max="10" value={n(form.rh_hysteresis, 3)} onChange={num("rh_hysteresis")}/><span>%</span><Help>{lang === "da" ? "Hvor langt under grænsen fugten skal ned, før der skrues ned igen. Forhindrer at trinnet hopper frem og tilbage." : "How far below the limit humidity must fall before stepping down again. Stops the level from flapping."}</Help></label>
          <label>{lang === "da" ? "CO₂ grænse" : "CO₂ limit"}<input type="number" min="500" max="2000" step="50" value={n(form.co2_setpoint, 800)} onChange={num("co2_setpoint")}/><span>ppm</span><Help>{lang === "da" ? "Over denne CO₂ skrues der op. Udeluft er ca. 420 ppm, og over 1000 ppm føles luften tung." : "Above this CO₂ the fans step up. Outdoor air is about 420 ppm; above 1000 ppm the air feels stuffy."}</Help></label>
          <label>{lang === "da" ? "CO₂ hysterese" : "CO₂ hysteresis"}<input type="number" min="25" max="500" step="25" value={n(form.co2_hysteresis, 100)} onChange={num("co2_hysteresis")}/><span>ppm</span><Help>{lang === "da" ? "Hvor langt under grænsen CO₂ skal ned, før der skrues ned igen." : "How far below the limit CO₂ must fall before stepping down."}</Help></label>
          <label>{lang === "da" ? "CO₂ kalibrering" : "CO₂ calibration"}<input type="number" min="-1000" max="1000" step="10" value={n(form.co2_offset, 0)} onChange={num("co2_offset")}/><span>ppm</span><Help>{lang === "da" ? `Lægges til anlæggets egen CO₂-måler, før der styres og vises. Måler den fx 200 for højt i forhold til dine rumfølere, så sæt −200. Lige nu: rå ${fmt(controller.co2_raw, lang, 0, " ppm")}, korrigeret ${fmt(controller.co2_measured, lang, 0, " ppm")}.` : `Added to the unit's own CO₂ sensor before it is used for control and shown. If it reads 200 too high compared with your room sensors, set −200. Now: raw ${fmt(controller.co2_raw, lang, 0, " ppm")}, corrected ${fmt(controller.co2_measured, lang, 0, " ppm")}.`}</Help></label>
          <label>{lang === "da" ? "Timeout for HA-rumdata" : "HA room data timeout"}<input type="number" min="60" max="3600" step="30" value={n(form.ha_timeout_seconds, 300)} onChange={num("ha_timeout_seconds")}/><span>s</span><Help>{lang === "da" ? "Hører controlleren ikke fra Home Assistant så længe, falder Smart Auto tilbage til anlæggets egne følere." : "If the controller hears nothing from Home Assistant for this long, Smart Auto falls back to the unit's own sensors."}</Help></label>
        </div>
      </Card>
      <Card title={lang === "da" ? "Badeværelse" : "Bathroom"} lead={lang === "da" ? "Egne grænser for rum med bad" : "Separate limits for rooms with a shower"} icon={Droplets}>
        <div className="settings-grid">
          <label>{lang === "da" ? "Fugt start" : "Humidity start"}<input type="number" min="35" max="90" value={n(form.bathroom_rh_setpoint, 65)} onChange={num("bathroom_rh_setpoint")}/><span>%</span><Help>{lang === "da" ? "Badeværelser er naturligt fugtigere, så de får en højere grænse." : "Bathrooms are naturally more humid, so they get a higher limit."}</Help></label>
          <label>{lang === "da" ? "Hysterese" : "Hysteresis"}<input type="number" min="1" max="20" value={n(form.bathroom_rh_hysteresis, 5)} onChange={num("bathroom_rh_hysteresis")}/><span>%</span></label>
          <label>{lang === "da" ? "Maks. trin" : "Maximum level"}<input type="number" min="1" max="6" value={n(form.bathroom_max_level, 4)} onChange={num("bathroom_max_level")}/><Help>{lang === "da" ? "Et bad kan højst løfte hele huset til dette trin, så et brusebad ikke giver fuld boost." : "A bathroom can raise the whole house to this level at most, so a shower does not trigger full boost."}</Help></label>
          <p className="settings-help">{lang === "da" ? "Gælder rum med rumtypen badeværelse, eller rum med navne som Bad, Bath eller Shower." : "Applies to rooms of type bathroom, or rooms named like Bad, Bath or Shower."}</p>
        </div>
      </Card>
    </>,
    humidity: <>
      <Card title={lang === "da" ? "Fugt efter absolut vandindhold" : "Humidity by absolute water content"} lead={lang === "da" ? "Om sommeren kan udeluften være fugtigere end inde" : "In summer outdoor air can be wetter than indoor air"} icon={Droplets}>
        <div className="settings-grid">
          <label className="check-row"><input type="checkbox" checked={form.humidity_smart_enabled === true} onChange={check("humidity_smart_enabled")}/> {lang === "da" ? "Skru kun op for fugt, når udeluften tørrer" : "Only raise for humidity when outdoor air dries"}</label>
          <Help>{lang === "da" ? "Controlleren regner fugten om til gram vand pr. m³ inde og ude. Indeholder udeluften lige så meget vand, fjerner mere ventilation ikke fugt, og fugtkravet ignoreres. CO₂ virker stadig." : "The controller converts humidity to grams of water per m³ indoors and outdoors. If outdoor air holds as much water, more ventilation removes no moisture and the humidity demand is ignored. CO₂ still applies."}</Help>
          <label>{lang === "da" ? "Udeluftens fugt" : "Outdoor humidity"}<select value={s(form.outdoor_humidity_source)} onChange={e => set("outdoor_humidity_source", e.target.value)}><option value="">{t(T.none)}</option>{roomOptions(form.outdoor_humidity_source)}</select><Help>{lang === "da" ? "Et målerum fra Home Assistant med udendørs luftfugtighed, fx fra vejrintegrationen. Udetemperaturen tages fra anlæggets T1." : "A measurement room from Home Assistant with outdoor humidity, e.g. from the weather integration. Outdoor temperature comes from the unit's T1."}</Help>{roomHint}</label>
          <label>{lang === "da" ? "Margin" : "Margin"}<input type="number" min="0" max="3" step="0.1" value={n(form.humidity_margin_gm3, 0.5)} onChange={num("humidity_margin_gm3")}/><span>g/m³</span><Help>{lang === "da" ? "Så meget tørrere skal udeluften mindst være, før fugt tæller." : "How much drier outdoor air must be before humidity counts."}</Help></label>
        </div>
        <div className="settings-summary">
          <span>{lang === "da" ? "Inde" : "Indoor"}<strong>{fmt(controller.indoor_absolute_humidity, lang, 1, " g/m³")}</strong></span>
          <span>{lang === "da" ? "Ude" : "Outdoor"}<strong>{fmt(controller.outdoor_absolute_humidity, lang, 1, " g/m³")}</strong></span>
          <span>{lang === "da" ? "Udeluften tørrer" : "Outdoor air dries"}<strong>{controller.humidity_drying === false ? (lang === "da" ? "Nej" : "No") : (lang === "da" ? "Ja" : "Yes")}</strong></span>
        </div>
      </Card>
      <Card title={lang === "da" ? "Beskyttelse mod tør luft" : "Dry-air protection"} lead={lang === "da" ? "Om vinteren kan for meget ventilation udtørre huset" : "In winter too much ventilation can dry out the house"} icon={Droplets}>
        <div className="settings-grid">
          <label className="check-row"><input type="checkbox" checked={form.dry_protection_enabled === true} onChange={check("dry_protection_enabled")}/> {lang === "da" ? "Begræns ventilationen ved tør luft" : "Limit ventilation when the air is dry"}</label>
          <Help>{lang === "da" ? "Når luften inde er tørrere end grænsen, og CO₂ er under sin grænse i alle rum, går anlægget højst op på det valgte trin. Stiger CO₂, slipper begrænsningen straks." : "When indoor air is drier than the limit and CO₂ is below its limit in every room, the unit runs at most at the chosen level. If CO₂ rises, the limit is lifted at once."}</Help>
          <label>{lang === "da" ? "Tør luft under" : "Dry air below"}<input type="number" min="15" max="45" value={n(form.dry_rh_limit, 30)} onChange={num("dry_rh_limit")}/><span>% RH</span><Help>{lang === "da" ? "Under ca. 30 % RH giver tørre øjne, statisk elektricitet og revner i trægulve." : "Below about 30 % RH causes dry eyes, static and cracks in wooden floors."}</Help></label>
          <label>{lang === "da" ? "Maks. trin ved tør luft" : "Maximum level in dry air"}<input type="number" min="1" max="6" value={n(form.dry_max_level, 2)} onChange={num("dry_max_level")}/><Help>{lang === "da" ? "Styres grundtrinnet af husets størrelse, går det aldrig under det reducerede minimum." : "If the base level follows the house size, it never goes below the reduced minimum."}</Help></label>
        </div>
      </Card>
    </>,
    night: <Card title={lang === "da" ? "Natdrift" : "Night mode"} lead={lang === "da" ? "Nat og luftkvalitet kæmper ikke mod hinanden" : "Night mode and air quality never fight"} icon={Moon}>
      <div className="settings-grid">
        <label className="check-row"><input type="checkbox" checked={form.night_enabled === true} onChange={check("night_enabled")}/> {lang === "da" ? "Natsænkning" : "Night reduction"}</label>
        <Help>{lang === "da" ? "Sænker ventilationen i tidsrummet, så anlægget er mere stille." : "Lowers ventilation during the period so the unit is quieter."}</Help>
        <label>{lang === "da" ? "Start" : "Start"}<input type="time" value={s(form.night_start, "22:00")} onChange={e => set("night_start", e.target.value)}/></label>
        <label>{lang === "da" ? "Slut" : "End"}<input type="time" value={s(form.night_end, "06:00")} onChange={e => set("night_end", e.target.value)}/></label>
        <label>{lang === "da" ? "Nat-trin" : "Night level"}<input type="number" min="1" max="6" value={n(form.night_level, 2)} onChange={num("night_level")}/><Help>{lang === "da" ? "Trinnet om natten, når luften er god." : "The level at night when the air is good."}</Help></label>
        <label>{lang === "da" ? "Maks. ved dårlig luft" : "Maximum with poor air"}<input type="number" min="1" max="6" value={n(form.night_air_quality_max_level, 4)} onChange={num("night_air_quality_max_level")}/><Help>{lang === "da" ? "Om natten må fugt og CO₂ højst løfte til dette trin." : "At night humidity and CO₂ may raise the level to this at most."}</Help></label>
      </div>
    </Card>,
    afterheat: <>
      <Card title={lang === "da" ? "Eftervarme" : "Afterheat"} lead={lang === "da" ? "HAC1 styrer selv ventil, aktuator og frostsikring" : "HAC1 handles the valve, actuator and frost protection itself"} icon={Thermometer}>
        <div className="settings-grid">
          <label>{lang === "da" ? "Indblæsning, grundsetpunkt" : "Supply air base setpoint"}<input type="number" min="10" max="35" value={n(form.afterheat_setpoint, 20)} onChange={num("afterheat_setpoint")}/><span>°C</span><Help>{lang === "da" ? "Temperaturen luften varmes op til efter varmefladen. Er styring efter rumtemperatur slået til, er det udgangspunktet." : "The temperature the air is heated to after the coil. With room control on, this is the starting point."}</Help></label>
          <label>{lang === "da" ? "Varmeflade" : "Heating coil"}<select value={form.afterheat_coil === "water" ? "water" : "electric"} onChange={e => set("afterheat_coil", e.target.value)}><option value="electric">{lang === "da" ? "Elvarmeflade" : "Electric coil"}</option><option value="water">{lang === "da" ? "Vandbåren varmeflade" : "Water coil"}</option></select><Help>{lang === "da" ? "Ændrer kun tegningen på forsiden." : "Only changes the drawing on the overview."}</Help></label>
          <p className="settings-help">{lang === "da" ? "HAC1 varmer aldrig, når udetemperaturen er 15 °C eller mere. Det er anlæggets egen spærre." : "HAC1 never heats when it is 15 °C or warmer outside. That is the unit's own lockout."}</p>
        </div>
      </Card>
      <Card title={lang === "da" ? "Styr efter rumtemperatur" : "Follow the room temperature"} lead={lang === "da" ? "Varmere indblæsning når huset er koldt" : "Warmer supply air when the house is cold"} icon={Thermometer}>
        <div className="settings-grid">
          <label className="check-row"><input type="checkbox" checked={form.afterheat_room_enabled === true} onChange={check("afterheat_room_enabled")}/> {lang === "da" ? "Flyt setpunktet efter rumtemperaturen" : "Move the setpoint with the room temperature"}</label>
          <Help>{lang === "da" ? "Setpunkt = grundsetpunkt + forstærkning × (ønsket rum − målt rum). Det flyttes én grad ad gangen og holdes mellem laveste og højeste værdi. Mangler rumtemperaturen, bruges grundsetpunktet. Ventilationsluften giver kun få hundrede watt, så det er komfort og ikke opvarmning." : "Setpoint = base setpoint + gain × (wanted room − measured room). It moves one degree at a time and stays between the lowest and highest value. Without a room temperature the base setpoint is used. Ventilation air carries only a few hundred watts, so this is comfort, not heating."}</Help>
          <label>{lang === "da" ? "Rumtemperatur fra" : "Room temperature from"}<select value={s(form.afterheat_room_source, "auto")} onChange={e => set("afterheat_room_source", e.target.value)}><option value="auto">{lang === "da" ? "Automatisk: HA-rum, ellers T3" : "Automatic: HA rooms, else T3"}</option><option value="t3">{lang === "da" ? "Udsugningsluft T3" : "Extract air T3"}</option><option value="t5">{lang === "da" ? "HRC2-rumføler T5 (upålidelig uden HCP4)" : "HRC2 room sensor T5 (unreliable without HCP4)"}</option><option value="ha_average">{lang === "da" ? "Gennemsnit af HA-rum" : "Average of HA rooms"}</option>{roomOptions(form.afterheat_room_source)}</select><Help>{lang === "da" ? "Automatisk bruger gennemsnittet af dine HA-rum med temperatur (badeværelser og brændeovns- og udeluftsfølere tæller ikke med). Tilføj rummene med dine egne temperaturfølere i HCH PassiveLink-integrationen under Smart Auto-rum, gerne med styring slået fra. Findes der ingen, bruges T3, som er udsugningsluft og også indeholder luft fra køkken og bad. T5 sidder i HRC2-fjernbetjeningen og opdateres ikke, når Pi'en har erstattet HCP4." : "Automatic uses the average of your HA rooms with a temperature (bathrooms and stove or outdoor sensors are left out). Add rooms with your own temperature sensors in the HCH PassiveLink integration under Smart Auto rooms, ideally with control turned off. Without any, T3 is used, which is extract air and includes kitchen and bathroom air. T5 sits in the HRC2 remote and is not updated once the Pi has replaced HCP4."}</Help></label>
          <label>{lang === "da" ? "Ønsket rumtemperatur" : "Wanted room temperature"}<input type="number" min="15" max="26" step="0.5" value={n(form.afterheat_room_target, 21)} onChange={num("afterheat_room_target")}/><span>°C</span><Help>{lang === "da" ? "Sæt den lidt under radiatorernes eller gulvvarmens, så de ikke modarbejder hinanden." : "Set it slightly below the radiators or floor heating so they do not work against each other."}</Help></label>
          <label>{lang === "da" ? "Forstærkning" : "Gain"}<input type="number" min="0.5" max="5" step="0.5" value={n(form.afterheat_room_gain, 1.5)} onChange={num("afterheat_room_gain")}/><span>°C/°C</span><Help>{lang === "da" ? "Grader indblæsning pr. grad rummet afviger." : "Degrees of supply air per degree of room deviation."}</Help></label>
          <label>{lang === "da" ? "Laveste indblæsning" : "Lowest supply"}<input type="number" min="10" max="35" value={n(form.afterheat_room_min, 17)} onChange={num("afterheat_room_min")}/><span>°C</span><Help>{lang === "da" ? "Under ca. 17 °C kan indblæsningen føles som træk." : "Below about 17 °C the supply air can feel draughty."}</Help></label>
          <label>{lang === "da" ? "Højeste indblæsning" : "Highest supply"}<input type="number" min="10" max="35" value={n(form.afterheat_room_max, 24)} onChange={num("afterheat_room_max")}/><span>°C</span></label>
          <label>{lang === "da" ? "Minutter pr. grad" : "Minutes per degree"}<input type="number" min="2" max="60" value={n(form.afterheat_room_step_minutes, 10)} onChange={num("afterheat_room_step_minutes")}/><span>min</span><Help>{lang === "da" ? "Hvor ofte setpunktet må flyttes én grad. Længere tid giver roligere regulering." : "How often the setpoint may move one degree. Longer gives calmer control."}</Help></label>
        </div>
        <div className="settings-summary">
          <span>{lang === "da" ? "Rumtemperatur" : "Room temperature"}<strong>{fmt(controller.afterheat_room_temperature, lang, 1, " °C")}</strong></span>
          <span>{lang === "da" ? "Kilde lige nu" : "Source right now"}<strong>{(() => { const used = s(controller.afterheat_room_source_used); if (!used) return "—"; if (used === "ha_average") return lang === "da" ? "Gennemsnit af HA-rum" : "Average of HA rooms"; if (used.startsWith("room:")) return used.slice(5); return used.toUpperCase(); })()}</strong></span>
          <span>{lang === "da" ? "Aktuelt setpunkt" : "Current setpoint"}<strong>{fmt(controller.afterheat_effective_setpoint, lang, 0, " °C")}</strong></span>
        </div>
        <p className="settings-help">{s(controller.afterheat_room_reason)}</p>
      </Card>
    </>,
    cooling: <Card title={t(SECTIONS[5].title)} lead={t(SECTIONS[5].lead)} icon={Snowflake}>
      <div className="settings-grid">
        <label className="check-row"><input type="checkbox" checked={form.cooling_enabled === true} onChange={check("cooling_enabled")}/> {lang === "da" ? "Frikøling" : "Free cooling"}</label>
        <Help>{lang === "da" ? "Er det for varmt inde og køligere ude, åbnes bypass, så udeluften går uden om varmeveksleren. Bypass-spjældet er langsomt (ca. 3 minutter), derfor venter controlleren og holder minimumstider." : "If it is too warm inside and cooler outside, the bypass opens so outdoor air skips the heat exchanger. The damper is slow (about 3 minutes), so the controller waits and keeps minimum times."}</Help>
        <label>{lang === "da" ? "Start ved rumtemperatur" : "Start at room temperature"}<input type="number" min="18" max="30" step="0.5" value={n(form.cooling_room_setpoint, 23)} onChange={num("cooling_room_setpoint")}/><span>°C</span></label>
        <label>{lang === "da" ? "Hysterese" : "Hysteresis"}<input type="number" min="0.2" max="3" step="0.1" value={n(form.cooling_hysteresis, 0.5)} onChange={num("cooling_hysteresis")}/><span>°C</span></label>
        <label>{lang === "da" ? "Laveste udetemperatur" : "Lowest outdoor temperature"}<input type="number" min="-10" max="25" step="0.5" value={n(form.cooling_outdoor_min, 12)} onChange={num("cooling_outdoor_min")}/><span>°C</span><Help>{lang === "da" ? "Koldere udeluft end dette blæses ikke ind uden varmegenvinding." : "Outdoor air colder than this is never blown in without heat recovery."}</Help></label>
        <label>{lang === "da" ? "Mindste forskel inde/ude" : "Minimum indoor/outdoor difference"}<input type="number" min="0.5" max="10" step="0.5" value={n(form.cooling_min_delta, 1.5)} onChange={num("cooling_min_delta")}/><span>°C</span></label>
        <label>{lang === "da" ? "Trin under frikøling" : "Level during free cooling"}<input type="number" min="1" max="6" value={n(form.cooling_level, 4)} onChange={num("cooling_level")}/></label>
        <label>{lang === "da" ? "Vent før start" : "Wait before start"}<input type="number" min="0" max="1800" step="30" value={n(form.cooling_start_delay_seconds, 180)} onChange={num("cooling_start_delay_seconds")}/><span>s</span></label>
        <label>{lang === "da" ? "Mindste tid tændt" : "Minimum on time"}<input type="number" min="0" max="3600" step="60" value={n(form.cooling_min_on_seconds, 600)} onChange={num("cooling_min_on_seconds")}/><span>s</span></label>
        <label>{lang === "da" ? "Mindste tid slukket" : "Minimum off time"}<input type="number" min="0" max="3600" step="60" value={n(form.cooling_min_off_seconds, 300)} onChange={num("cooling_min_off_seconds")}/><span>s</span></label>
      </div>
    </Card>,
    fireplace: <Card title={t(SECTIONS[6].title)} lead={lang === "da" ? "Holder anlæggets pejsefunktion, så længe der fyres" : "Holds the unit's fireplace mode while the stove burns"} icon={Flame}>
      <div className="settings-grid">
        <label className="check-row"><input type="checkbox" checked={form.fireplace_auto_enabled === true} onChange={check("fireplace_auto_enabled")}/> {lang === "da" ? "Automatisk pejsefunktion" : "Automatic fireplace mode"}</label>
        <Help>{lang === "da" ? "Pejsefunktionen giver overtryk i huset, så røgen ikke suges ind. Den startes af brændeovnens føler eller af en ekstern switch (Home Assistant, knap, automation). Bypass lukkes, mens den er aktiv. Slukker du pejsefunktionen manuelt, venter automatikken, til signalet har været væk." : "Fireplace mode gives positive pressure so smoke is not drawn in. It is started by the stove sensor or by an external switch (Home Assistant, button, automation). The bypass is closed while it is active. If you turn fireplace mode off manually, the automation waits until the signal has cleared."}</Help>
        <label>{lang === "da" ? "Brændeovnens føler" : "Stove sensor"}<select value={s(form.fireplace_auto_source)} onChange={e => set("fireplace_auto_source", e.target.value)}><option value="">{lang === "da" ? "Ingen – kun ekstern switch" : "None – external switch only"}</option>{roomOptions(form.fireplace_auto_source)}</select><Help>{lang === "da" ? "Et målerum fra Home Assistant med temperaturen ved brændeovnen." : "A measurement room from Home Assistant with the temperature at the stove."}</Help>{roomHint}</label>
        <label>{lang === "da" ? "Start ved" : "Start at"}<input type="number" min="15" max="400" step="0.5" value={n(form.fireplace_auto_on_temp, 25)} onChange={num("fireplace_auto_on_temp")}/><span>°C</span></label>
        <label>{lang === "da" ? "Stop under" : "Stop below"}<input type="number" min="10" max="399" step="0.5" value={n(form.fireplace_auto_off_temp, 24)} onChange={num("fireplace_auto_off_temp")}/><span>°C</span><Help>{lang === "da" ? "Skal være lavere end start, så den ikke slår til og fra." : "Must be lower than start so it does not flap on and off."}</Help></label>
        <label>{lang === "da" ? "Efterløb" : "Afterrun"}<input type="number" min="0" max="120" step="5" value={n(form.fireplace_afterrun_minutes, 15)} onChange={num("fireplace_afterrun_minutes")}/><span>min</span><Help>{lang === "da" ? "Så længe fortsætter pejsefunktionen, efter signalet er væk." : "How long fireplace mode continues after the signal is gone."}</Help></label>
        <label>{lang === "da" ? "Maks. varighed" : "Maximum duration"}<input type="number" min="1" max="24" value={n(form.fireplace_max_hours, 6)} onChange={num("fireplace_max_hours")}/><span>{lang === "da" ? "timer" : "hours"}</span><Help>{lang === "da" ? "Sikkerhed hvis en føler eller switch hænger. Derefter stopper den, til signalet har været væk." : "Safety if a sensor or switch gets stuck. It then stops until the signal has cleared."}</Help></label>
      </div>
      <div className="settings-summary">
        <span>{lang === "da" ? "Brændeovn" : "Stove"}<strong>{fmt(controller.stove_temperature, lang, 1, " °C")}</strong></span>
        <span>{lang === "da" ? "Automatik" : "Automation"}<strong>{controller.fireplace_auto_active === true ? t(T.on) : t(T.off)}</strong></span>
      </div>
    </Card>,
    ui: <Card title={t(SECTIONS[7].title)} lead={lang === "da" ? "Gemmes kun i denne browser" : "Stored in this browser only"} icon={Monitor}>
      <div className="settings-grid">
        <label>{lang === "da" ? "Sprog" : "Language"}<select value={language} onChange={e => setLanguage(e.target.value === "en" ? "en" : "da")}><option value="da">Dansk</option><option value="en">English</option></select><Help>{lang === "da" ? "Indstillinger og forklaringer vises på det valgte sprog." : "Settings and explanations are shown in the chosen language."}</Help></label>
        <label>{lang === "da" ? "Tema" : "Theme"}<select value={theme} onChange={e => setTheme(e.target.value)}><option value="system">System</option><option value="light">{lang === "da" ? "Lyst" : "Light"}</option><option value="dark">{lang === "da" ? "Mørkt" : "Dark"}</option></select></label>
        <label>{lang === "da" ? "Sidemenu" : "Sidebar"}<select value={collapsed ? "collapsed" : "expanded"} onChange={e => setCollapsed(e.target.value === "collapsed")}><option value="expanded">{lang === "da" ? "Udvidet" : "Expanded"}</option><option value="collapsed">{lang === "da" ? "Sammenfoldet" : "Collapsed"}</option></select></label>
        <label>{lang === "da" ? "Animation" : "Animation"}<select value={motion} onChange={e => setMotion(e.target.value)}><option value="normal">Normal</option><option value="reduced">{lang === "da" ? "Reduceret" : "Reduced"}</option></select></label>
        <button className="secondary-action" onClick={uiSave}>{t(T.saveUi)}</button>
      </div>
    </Card>,
    security: <Card title={t(SECTIONS[8].title)} lead={t(SECTIONS[8].lead)} icon={ShieldCheck}>
      <div className="settings-summary">
        <span>{lang === "da" ? "Bruger" : "User"}<strong>{auth.username ?? "—"}</strong></span>
        <span>Login<strong>{auth.enabled === false ? (lang === "da" ? "Deaktiveret" : "Disabled") : (lang === "da" ? "Aktiveret" : "Enabled")}</strong></span>
        <span>Master<strong>{s(controller.active_master, "—")}</strong></span>
        <span>{lang === "da" ? "Skrivninger" : "Writes"}<strong>{controller.hardware_writes_allowed === true ? (lang === "da" ? "Tilladt" : "Allowed") : (lang === "da" ? "Blokeret" : "Blocked")}</strong></span>
      </div>
      <p className="settings-help">{lang === "da" ? "Pi'en skriver kun til anlægget, når den er master. Sidder HCP4-panelet på bussen, vinder det altid." : "The Pi only writes to the unit when it is master. If the HCP4 panel is on the bus, it always wins."}</p>
    </Card>,
  };

  const active = SECTIONS.find(item => item.id === section) ?? SECTIONS[0];
  return <section className="dashboard-overview page-enter">
    <header className="overview-heading-row"><div><span className="eyebrow">{t(T.eyebrow)}</span><h1>{t(T.title)}</h1><p>{t(T.intro)}</p></div></header>
    <div className="settings-layout">
      <nav className="settings-nav" aria-label={t(T.eyebrow)}>{SECTIONS.map(item => { const Icon = item.icon; return <button key={item.id} type="button" aria-current={item.id === active.id ? "page" : undefined} onClick={() => setSection(item.id)}><Icon size={16}/><span><strong>{t(item.title)}</strong><small>{t(item.lead)}</small></span></button>; })}</nav>
      <div className="settings-content" data-section={active.id}>{sections[active.id]}</div>
    </div>
    <div className="settings-savebar"><span>{notice || t(T.saveHint)}</span><button className="primary-action" disabled={busy || !csrf} onClick={() => void save()}><Save size={15}/>{busy ? t(T.saving) : t(T.save)}</button></div>
  </section>;
}
