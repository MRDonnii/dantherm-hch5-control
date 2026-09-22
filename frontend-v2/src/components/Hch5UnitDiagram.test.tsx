import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Hch5UnitDiagram, type Hch5UnitDiagramProps } from "./Hch5UnitDiagram";
const baseProps:Hch5UnitDiagramProps={outdoor:4.2,extract:22.1,exhaust:8.4,beforeHeater:18.5,afterHeater:21,room:21.7,frost:7,flowWater:34,returnWater:28,supplyRpm:1180,extractRpm:1120,supplyPercent:42,extractPercent:40,bypassActual:false,bypassRequest:"auto",heating:true,recovery:82};
describe("Hch5UnitDiagram",()=>{
  it("crosses both normal air paths through exchanger centre",()=>{const m=renderToStaticMarkup(<Hch5UnitDiagram {...baseProps}/>);expect(m.match(/L550 295/g)?.length).toBeGreaterThanOrEqual(6);expect(m).toContain("is-recovery");});
  it("reroutes only supply in bypass and keeps the external coil",()=>{const m=renderToStaticMarkup(<Hch5UnitDiagram {...baseProps} bypassActual/>);expect(m).toContain("Q356 205 356 178 V143");expect(m).toContain("M1260 205 H776");expect(m).toContain("Ekstern eftervarme · HAC1");expect(m).toContain("is-bypass");});
  it("uses larger inward duct collars and shows T2 before external coil",()=>{const m=renderToStaticMarkup(<Hch5UnitDiagram {...baseProps}/>);expect(m).toContain('rx="43"');expect(m).toContain("T2 før flade");expect(m).toContain("Kun setpunkt styres");});
  it("stops airflow animation with stopped fans",()=>{const m=renderToStaticMarkup(<Hch5UnitDiagram {...baseProps} supplyRpm={0} extractRpm={0}/>);expect(m.match(/--flow-speed:0s/g)?.length).toBe(8);});
});
