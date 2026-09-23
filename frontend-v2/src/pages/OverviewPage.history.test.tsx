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
      if (endpoint === "/api/controller/state") return {};
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
