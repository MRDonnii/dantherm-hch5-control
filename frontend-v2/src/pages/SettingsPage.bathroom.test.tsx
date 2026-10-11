// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { CONTROLLER_KEYS, SettingsPage } from "./SettingsPage";

describe("Bathroom settings", () => {
  afterEach(() => { localStorage.clear(); window.location.hash = ""; });

  it("saves the bathroom settings with the controller", () => {
    for (const key of ["bathroom_rh_setpoint", "bathroom_rh_hysteresis", "bathroom_max_level", "bathroom_rise_percent",
      "bathroom_rise_minutes", "bathroom_night_drying", "bathroom_max_minutes", "bathroom_rooms"]) {
      expect(CONTROLLER_KEYS).toContain(key);
    }
  });

  it("lives under Fugt og tør luft with common limits, shower detection and a room table", () => {
    window.location.hash = "#/settings?section=humidity";
    const markup = renderToStaticMarkup(<SettingsPage/>);
    for (const text of ["Badeværelse", "Højeste trin ved udtørring", "Bad opdages før grænsen nås", "Tør også ud om natten", "Maks. udtørringstid", "Hvilke rum der er badeværelser"]) {
      expect(markup).toContain(text);
    }
  });

  it("is no longer hidden under Luftkvalitet", () => {
    window.location.hash = "#/settings?section=air";
    expect(renderToStaticMarkup(<SettingsPage/>)).not.toContain("Højeste trin ved udtørring");
  });
});
