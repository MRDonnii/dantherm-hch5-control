// @vitest-environment jsdom
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Hch5UnitDiagram, type Hch5UnitDiagramProps } from "./Hch5UnitDiagram";

const baseProps: Hch5UnitDiagramProps = { outdoor: 17, extract: 22.3, exhaust: 18.1, beforeHeater: 20.9, afterHeater: 21.3, room: 21.8, frost: 19.4, flowWater: 31.2, returnWater: 26.4, supplyRpm: 1945, extractRpm: 2230, supplyPercent: 73, extractPercent: 85, bypassActual: false, bypassRequest: "OFF", heating: false, recovery: 79 };
const core = (container: HTMLElement) => container.querySelector(".hch-bypass-progress");

afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("Hch5UnitDiagram damper travel", () => {
  it("names the direction from the reported position, as the unit moves the damper by itself in Auto", () => {
    const { container, rerender } = render(<Hch5UnitDiagram {...baseProps} bypassActual bypassRaw={255}/>);
    expect(core(container)).toBeNull();
    rerender(<Hch5UnitDiagram {...baseProps} bypassRaw={160}/>);
    expect(core(container)?.getAttribute("class")).toBe("hch-bypass-progress closing");
    expect(core(container)?.textContent).toContain("Lukker bypass");
    expect(core(container)?.textContent).toContain("63 %");
    // The real damper can hold one reported step for a minute; it keeps closing.
    rerender(<Hch5UnitDiagram {...baseProps} bypassRaw={160} busActive/>);
    expect(core(container)?.textContent).toContain("Lukker bypass");
    rerender(<Hch5UnitDiagram {...baseProps} bypassRaw={32}/>);
    expect(core(container)?.textContent).toContain("13 %");
    rerender(<Hch5UnitDiagram {...baseProps} bypassRaw={96}/>);
    expect(core(container)?.textContent).toContain("Åbner bypass");
    expect(core(container)?.textContent).toContain("38 %");
  });

  it("returns to the heat-recovery view once the damper has settled", () => {
    vi.useFakeTimers();
    const { container, rerender } = render(<Hch5UnitDiagram {...baseProps} bypassRaw={224}/>);
    rerender(<Hch5UnitDiagram {...baseProps} bypassRaw={0}/>);
    expect(core(container)?.textContent).toContain("Lukker bypass");
    expect(core(container)?.textContent).toContain("0 %");
    act(() => { vi.advanceTimersByTime(2700); });
    expect(core(container)).toBeNull();
    expect(container.querySelector(".hch-exchanger-title")?.textContent).toBe("Varmeveksler");
  });
});
