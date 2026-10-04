// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OverviewPage } from "./OverviewPage";

const api = vi.hoisted(() => ({ requestJson: vi.fn() }));
vi.mock("../lib/api", () => ({ requestJson: api.requestJson, postJson: vi.fn() }));

class ResizeObserverStub { observe() {} disconnect() {} }
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

afterEach(() => { cleanup(); api.requestJson.mockReset(); });

describe("sensor history popup", () => {
  it("opens the selected sensor's 24-hour graph and closes with Escape", async () => {
    const now = Math.floor(Date.now() / 1000);
    api.requestJson.mockImplementation(async (endpoint: string) => {
      if (endpoint === "/state.json") return { outdoor_temp: 6.1, flow_temperature: 34, return_temperature: 28 };
      if (endpoint === "/api/controller/state?compact=1") return {};
      if (endpoint === "/api/auth/status") return { csrf: "test" };
      if (endpoint === "/history.json?range=24h") return { samples: [{ ts: now - 60, outdoor_temp: 5.5 }, { ts: now, outdoor_temp: 6.1 }] };
      throw new Error(endpoint);
    });
    render(<OverviewPage/>);
    fireEvent.click(await screen.findByRole("button", { name: /Udeluft · T1: 6,1°C, vis 24 timers graf/ }));
    const dialog = await screen.findByRole("dialog", { name: "Udeluft · T1" });
    expect(api.requestJson).toHaveBeenCalledWith("/history.json?range=24h", { timeoutMs: 6000 });
    await waitFor(() => expect(dialog.querySelector("path[stroke='var(--blue)']")).not.toBeNull());
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

describe("exchanger reading", () => {
  it("shows the measured T2 result and flags disagreement with T2AH while afterheat is off", async () => {
    api.requestJson.mockImplementation(async (endpoint: string) => {
      if (endpoint === "/state.json") return { outdoor_temp: 12.4, extract_temp: 23.2, exhaust_temp: 13.7, heating_coil_after_temperature: 21.7, bypass_active: false };
      if (endpoint === "/api/controller/state?compact=1") return { actual_afterheat: false, actual_supply_before_heater_temperature: 20.7, actual_supply_air_temperature: 21.7, supply_recovery_percent: 77 };
      if (endpoint === "/api/auth/status") return { csrf: "test" };
      throw new Error(endpoint);
    });
    render(<OverviewPage/>);
    expect(await screen.findByText("T2 ≈77%", { selector: "text" })).toBeTruthy();
    expect(screen.getByText(/T2\/T2AH afviger/)).toBeTruthy();
  });
});
