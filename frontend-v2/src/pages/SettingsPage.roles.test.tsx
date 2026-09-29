// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { SessionContext, sessionCan, type AuthStatus } from "../lib/session";
import { SettingsPage } from "./SettingsPage";

function render(auth: AuthStatus) {
  const session = { auth, loading: false, refresh: async () => {}, can: (p: Parameters<typeof sessionCan>[1]) => sessionCan(auth, p) };
  return renderToStaticMarkup(<SessionContext.Provider value={session}><SettingsPage/></SessionContext.Provider>);
}

describe("SettingsPage roles", () => {
  it("shows a plain user only the interface and their own account", () => {
    const markup = render({ username: "familie", role: "user", permissions: ["control"] });
    expect(markup).toContain("Brugerflade");
    expect(markup).toContain("Sikkerhed");
    for (const hidden of ["Hus og luftmængde", "Følere", "Brugere, teknikere", "Fejlmeddelelser og nulstilling"]) expect(markup).not.toContain(hidden);
    expect(markup).not.toContain("Gem controller");
  });

  it("gives technicians mail but not user management", () => {
    const markup = render({ username: "tek", role: "technician", permissions: ["configure", "control", "diagnostics", "mail", "system"] });
    expect(markup).toContain("Hus og luftmængde");
    expect(markup).toContain("Fejlmeddelelser og nulstilling");
    expect(markup).not.toContain("Brugere, teknikere");
  });

  it("gives administrators user management", () => {
    const markup = render({ username: "admin", role: "admin", permissions: ["configure", "control", "diagnostics", "login_switch", "mail", "system", "users"] });
    expect(markup).toContain("Brugere, teknikere og administratorer");
  });
});
