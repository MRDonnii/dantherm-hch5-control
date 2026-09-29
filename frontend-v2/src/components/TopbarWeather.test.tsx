// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TopbarWeather } from "./TopbarWeather";

describe("TopbarWeather", () => {
  it("keeps measured T1 prominent even when the weather model differs", () => {
    render(<TopbarWeather outdoorTemp={15.4} weather={{
      source: "weather.home", condition: "cloudy", temperature_c: 22,
      humidity_pct: 61, humidity_at_t1: null,
      humidity_reason: "Vejrkildens temperatur afviger over 6 °C fra T1",
    }}/>)
    expect(screen.getByRole("button", { name: /Udetemperatur fra anlæggets T1/ }).textContent).toContain("15,4 °C")
    fireEvent.click(screen.getByRole("button", { name: /Udetemperatur fra anlæggets T1/ }))
    expect(screen.getByText(/Vejrmodellens temperatur: 22,0 °C/)).toBeTruthy()
    expect(screen.getByText(/Vejrfugt ved T1 \(hvis valgt til styring\): Ikke brugbar/)).toBeTruthy()
  })
})
