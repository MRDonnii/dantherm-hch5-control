// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SystemPage } from "./SystemPage";

const api = vi.hoisted(() => ({ requestJson: vi.fn() }));
vi.mock("../lib/api", () => ({ requestJson: api.requestJson }));
class ResizeObserverStub { observe() {} disconnect() {} }
vi.stubGlobal("ResizeObserver", ResizeObserverStub);
afterEach(() => { cleanup(); api.requestJson.mockReset(); });

describe("System controls", () => {
  it("changes a power profile and connects Wi-Fi through authenticated actions", async () => {
    api.requestJson.mockImplementation(async (endpoint: string, options?: { body?: string }) => {
      if (endpoint === "/state.json") return { system_boot_mode: "SD-kort" };
      if (endpoint.startsWith("/history.json")) return { samples: [] };
      if (endpoint === "/api/auth/status") return { csrf: "csrf-test" };
      if (endpoint === "/api/admin/action") {
        const request = JSON.parse(options?.body ?? "{}");
        if (request.action === "wifi_scan") return { networks: [{ ssid: "Home", signal: 75, security: "WPA2", connected: false }] };
        return { power_profile: request.action === "power_profile" ? "performance" : "balanced", governor: "ondemand", available_profiles: ["powersave", "balanced", "performance"], wifi_available: true, wifi_enabled: true, bluetooth_available: true };
      }
      throw new Error(endpoint);
    });
    render(<SystemPage />);
    const performance = await screen.findByRole("button", { name: /Ydelse/ });
    await waitFor(() => expect(performance.hasAttribute("disabled")).toBe(false));
    fireEvent.click(performance);
    await waitFor(() => expect(api.requestJson.mock.calls.some(([endpoint, options]) => endpoint === "/api/admin/action" && JSON.parse(options.body).action === "power_profile" && JSON.parse(options.body).target === "performance" && options.headers["X-CSRF-Token"] === "csrf-test")).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Find netværk" }));
    fireEvent.click(await screen.findByRole("button", { name: /Home.*75%/ }));
    fireEvent.change(screen.getByPlaceholderText("Wi-Fi-adgangskode"), { target: { value: "secret-passphrase" } });
    fireEvent.click(screen.getByRole("button", { name: "Forbind Wi-Fi" }));
    await waitFor(() => expect(api.requestJson.mock.calls.some(([endpoint, options]) => endpoint === "/api/admin/action" && JSON.parse(options.body).action === "wifi_connect" && JSON.parse(options.body).target.ssid === "Home" && JSON.parse(options.body).target.password === "secret-passphrase")).toBe(true));
    await waitFor(() => expect((screen.getByPlaceholderText("Wi-Fi-adgangskode") as HTMLInputElement).value).toBe(""));
    expect(screen.getByText("SD-kort")).toBeTruthy();
  });
});
