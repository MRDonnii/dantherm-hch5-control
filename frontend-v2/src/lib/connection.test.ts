// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { requestJson } from "./api";
import { usePollHealth, useSinglePoll } from "./connection";

afterEach(() => { vi.unstubAllGlobals(); });

describe("poll health", () => {
  it("stays online through a single missed poll", () => {
    const { result } = renderHook(() => usePollHealth(2));
    act(() => result.current[1](true));
    expect(result.current[0]).toBe(true);
    act(() => result.current[1](false));
    expect(result.current[0]).toBe(true);
    act(() => result.current[1](false));
    expect(result.current[0]).toBe(false);
    act(() => result.current[1](true));
    expect(result.current[0]).toBe(true);
  });

  it("skips a poll while the previous one is still waiting", async () => {
    let release = () => {};
    const poll = vi.fn(() => new Promise<void>(resolve => { release = resolve; }));
    const { result } = renderHook(() => useSinglePoll(poll));
    const first = result.current();
    await result.current();
    expect(poll).toHaveBeenCalledTimes(1);
    release();
    await first;
    void result.current();
    expect(poll).toHaveBeenCalledTimes(2);
  });
});

describe("ended session", () => {
  it("sends the browser to the login page instead of waiting forever", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, pathname: "/", assign });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: "Log ind igen", login_required: true }), { status: 401 })));
    await expect(requestJson("/state.json")).rejects.toMatchObject({ status: 401 });
    expect(assign).toHaveBeenCalledWith("/login");
  });
});
