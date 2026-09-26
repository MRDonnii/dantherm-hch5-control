// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { CONTROLLER_KEYS, SettingsPage } from "./SettingsPage";

describe("SettingsPage", () => {
  afterEach(() => localStorage.clear());

  it("saves every advanced controller feature", () => {
    for (const key of ["sizing_enabled", "house_area_m2", "ceiling_height_m", "airflow_measured", "afterheat_room_enabled",
      "fireplace_auto_enabled", "fireplace_auto_source", "humidity_smart_enabled", "dry_protection_enabled", "cooling_min_on_seconds"]) {
      expect(CONTROLLER_KEYS).toContain(key);
    }
  });

  it("groups settings into named sections with Danish help by default", () => {
    const markup = renderToStaticMarkup(<SettingsPage/>);
    for (const label of ["Hus og luftmængde", "Luftkvalitet", "Fugt og tør luft", "Eftervarme", "Frikøling", "Pejs og brændeovn", "Brugerflade", "Sikkerhed"]) {
      expect(markup).toContain(label);
    }
    expect(markup).toContain("Grundtrin");
    expect(markup).toContain(">Manuel<");
    expect(markup).toContain('aria-current="page"');
  });

  it("follows the chosen language", () => {
    localStorage.setItem("hch5-v2-lang", "en");
    const markup = renderToStaticMarkup(<SettingsPage/>);
    expect(markup).toContain("House and airflow");
    expect(markup).toContain(">Manual<");
    expect(markup).not.toContain("Hus og luftmængde");
  });
});
