// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AppShell } from "./AppShell";
import { useTopbarNotice } from "../lib/topbar-notice";

const api = vi.hoisted(() => ({ available: false, checks: vi.fn() }));
vi.mock("../lib/api", () => ({
  requestJson: async (endpoint: string) => endpoint === "/api/auth/status"
    ? { csrf: "test-token" }
    : { available: true, bus_traffic: true, version: "1.2.0-beta.36" },
  postJson: async () => {
    api.checks();
    return { update_available: api.available, available_version: "1.2.0-beta.37" };
  },
}));

function ChangeButton() {
  const { setNotice } = useTopbarNotice();
  return <button onClick={() => setNotice("Manuel valgt.")}>Gem ændring</button>;
}

afterEach(() => { cleanup(); api.checks.mockClear(); });

describe("AppShell update tab and control feedback", () => {
  it("keeps update navigation hidden when the beta channel is current", async () => {
    api.available = false;
    render(<MemoryRouter><AppShell><ChangeButton/></AppShell></MemoryRouter>);
    await waitFor(() => expect(api.checks).toHaveBeenCalled());
    expect(screen.queryByRole("link", { name: /Opdatering klar/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Gem ændring" }));
    expect(screen.getByRole("status").textContent).toContain("Manuel valgt.");
    expect(document.querySelector(".topbar-control-notice")).not.toBeNull();
  });

  it("shows an update tab in the top banner only when a new beta exists", async () => {
    api.available = true;
    render(<MemoryRouter><AppShell><ChangeButton/></AppShell></MemoryRouter>);
    const tab = await screen.findByRole("link", { name: /Opdatering klar/ });
    expect(tab.getAttribute("href")).toBe("/updates");
    expect(tab.textContent).toContain("1.2.0-beta.37");
    expect(document.querySelector(".sidebar-nav a[href='/updates']")).not.toBeNull();
  });
});
