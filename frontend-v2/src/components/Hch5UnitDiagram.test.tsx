import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Hch5UnitDiagram, type Hch5UnitDiagramProps } from "./Hch5UnitDiagram";


const baseProps: Hch5UnitDiagramProps = {
  outdoor: 4.2,
  extract: 22.1,
  exhaust: 8.4,
  beforeHeater: 18.5,
  afterHeater: 21.0,
  room: 21.7,
  frost: 7.0,
  flowWater: 34.0,
  returnWater: 28.0,
  supplyRpm: 1180,
  extractRpm: 1120,
  supplyPercent: 42,
  extractPercent: 40,
  bypassActual: false,
  bypassRequest: "auto",
  heating: true,
  recovery: 82,
};


describe("Hch5UnitDiagram", () => {
  it("routes both normal air paths through the exchanger centre", () => {
    const markup = renderToStaticMarkup(<Hch5UnitDiagram {...baseProps} />);
    expect(markup).toContain("L550 295");
    expect(markup.match(/L550 295/g)?.length).toBeGreaterThanOrEqual(6);
    expect(markup).toContain("is-recovery");
  });

  it("reroutes supply only while preserving the normal extract path in bypass", () => {
    const normal = renderToStaticMarkup(<Hch5UnitDiagram {...baseProps} />);
    const bypass = renderToStaticMarkup(<Hch5UnitDiagram {...baseProps} bypassActual />);
    const extractPath = "M1138 182 H774 Q753 182 735 200 L550 295 L365 390 Q350 400 325 400 H-38";

    expect(normal).toContain(extractPath);
    expect(bypass).toContain(extractPath);
    expect(bypass).toContain("M-38 182 H326 Q360 182 360 148 V126");
    expect(bypass).toContain("is-bypass");
    expect(bypass).toContain("Åben");
    expect(bypass).toContain("ønske Auto");
  });

  it("stops both animated paths when fan RPM is zero", () => {
    const markup = renderToStaticMarkup(
      <Hch5UnitDiagram {...baseProps} supplyRpm={0} extractRpm={0} heating={false} />,
    );
    expect(markup.match(/--flow-speed:0s/g)?.length).toBe(8);
    expect(markup).toContain("stopped");
    expect(markup).toContain("Ikke aktiv");
  });
});
