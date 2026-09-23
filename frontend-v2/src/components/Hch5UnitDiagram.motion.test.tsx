// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Hch5UnitDiagram, type Hch5UnitDiagramProps } from "./Hch5UnitDiagram";

const baseProps: Hch5UnitDiagramProps = { outdoor: 17, extract: 22.3, exhaust: 18.1, afterHeater: 21.3, frost: 19.4, flowWater: 31.2, returnWater: 26.4, supplyRpm: 1945, extractRpm: 2230, supplyPercent: 73, extractPercent: 85, bypassActual: false, bypassRequest: "OFF", heating: false, recovery: 79 };
const core = (container: HTMLElement) => container.querySelector(".hch-bypass-progress");
afterEach(cleanup);

describe("Hch5UnitDiagram damper travel", () => {
  it("uses elapsed time for closing while the status code stays at 32", () => {
    const { container, rerender } = render(<Hch5UnitDiagram {...baseProps} bypassActual bypassRaw={255}/>);
    expect(core(container)).toBeNull();
    rerender(<Hch5UnitDiagram {...baseProps} bypassRaw={32} bypassTravelDirection="closing" bypassTravelSeconds={45}/>);
    expect(core(container)?.getAttribute("class")).toBe("hch-bypass-progress closing");
    expect(core(container)?.textContent).toContain("25 %");
    rerender(<Hch5UnitDiagram {...baseProps} bypassRaw={32} bypassTravelDirection="closing" bypassTravelSeconds={90}/>);
    expect(core(container)?.textContent).toContain("50 %");
  });

  it("returns to the heat-recovery view as soon as the end code arrives", () => {
    const { container, rerender } = render(<Hch5UnitDiagram {...baseProps} bypassRaw={32} bypassTravelDirection="closing" bypassTravelSeconds={178}/>);
    expect(core(container)).not.toBeNull();
    rerender(<Hch5UnitDiagram {...baseProps} bypassRaw={0}/>);
    expect(core(container)).toBeNull();
    expect(container.querySelector(".hch-exchanger-title")?.textContent).toBe("Varmeveksler");
  });
  it("keeps both directions in motion at 92 percent and waits for the real end code", () => {
    const { container, rerender } = render(<Hch5UnitDiagram {...baseProps} bypassRaw={64} bypassTravelDirection="opening" bypassTravelSeconds={166}/>);
    expect(core(container)?.textContent).toContain("92 %");
    rerender(<Hch5UnitDiagram {...baseProps} bypassRaw={64} bypassTravelDirection="opening" bypassTravelSeconds={181}/>);
    expect(core(container)?.textContent).toContain("Afventer endestilling");
    rerender(<Hch5UnitDiagram {...baseProps} bypassActual bypassRaw={255}/>);
    expect(core(container)).toBeNull();
    rerender(<Hch5UnitDiagram {...baseProps} bypassRaw={32} bypassTravelDirection="closing" bypassTravelSeconds={166}/>);
    expect(core(container)?.textContent).toContain("92 %");
    rerender(<Hch5UnitDiagram {...baseProps} bypassRaw={32} bypassTravelDirection="closing" bypassTravelSeconds={183}/>);
    expect(core(container)?.textContent).toContain("Afventer endestilling");
    rerender(<Hch5UnitDiagram {...baseProps} bypassRaw={0}/>);
    expect(core(container)).toBeNull();
  });
});
