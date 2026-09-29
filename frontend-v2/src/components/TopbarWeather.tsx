import { useState } from "react";
import { Cloud, CloudRain, CloudSnow, CloudSun, Sun, Thermometer } from "lucide-react";

export type WeatherSummary = {
  source?: string;
  condition?: string;
  temperature_c?: number;
  humidity_pct?: number;
  humidity_at_t1?: number | null;
  humidity_reason?: string;
};

const CONDITIONS: Record<string, string> = {
  "clear-night": "Klart", cloudy: "Skyet", fog: "Tåge", hail: "Hagl",
  lightning: "Torden", "lightning-rainy": "Torden og regn", partlycloudy: "Let skyet",
  pouring: "Kraftig regn", rainy: "Regn", snowy: "Sne", "snowy-rainy": "Slud",
  sunny: "Sol", windy: "Blæst", "windy-variant": "Blæst og skyer", exceptional: "Ekstremt vejr",
};

function icon(condition?: string) {
  if (!condition) return <Thermometer size={17}/>;
  if (condition === "sunny" || condition === "clear-night") return <Sun size={17}/>;
  if (["snowy", "snowy-rainy", "hail"].includes(condition)) return <CloudSnow size={17}/>;
  if (["rainy", "pouring", "lightning", "lightning-rainy"].includes(condition)) return <CloudRain size={17}/>;
  if (condition === "cloudy" || condition === "fog") return <Cloud size={17}/>;
  return <CloudSun size={17}/>;
}

function degrees(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value.toLocaleString("da-DK", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} °C`
    : "—";
}

/** T1 is physical telemetry. Optional HA weather supplies condition and humidity. */
export function TopbarWeather({ outdoorTemp, weather }: { outdoorTemp: number | null; weather: WeatherSummary | null }) {
  const [open, setOpen] = useState(false);
  const condition = weather?.condition ? CONDITIONS[weather.condition] : undefined;
  return <div className="topbar-weather">
    <button type="button" className="topbar-weather-button" onClick={() => setOpen(value => !value)} aria-label="Udetemperatur fra anlæggets T1 og vejrdata" title={`Udeluft målt ved anlægget (T1): ${degrees(outdoorTemp)}${condition ? ` · ${condition} fra ${weather?.source}` : ""}`}>
      {icon(weather?.condition)}<span>T1 {degrees(outdoorTemp)}{condition ? ` · ${condition}` : ""}</span>
    </button>
    {open && <div className="topbar-weather-picker" role="status">
      <strong>Udeluft ved anlægget: {degrees(outdoorTemp)}</strong>
      <small>T1 er anlæggets målte temperatur og bruges også af controlleren.</small>
      {weather ? <>
        <small>Vejrkilde: {weather.source} · {condition ?? "Ukendt forhold"}</small>
        <small>Vejrmodellens temperatur: {degrees(weather.temperature_c)} · fugt: {typeof weather.humidity_pct === "number" ? `${weather.humidity_pct} %` : "—"}</small>
        <small>Vejrfugt ved T1 (hvis valgt til styring): {weather.humidity_at_t1 == null ? "Ikke brugbar" : `${weather.humidity_at_t1} %`} · {weather.humidity_reason}</small>
      </> : <small>Valgfri vejrkilde vælges i HCH5 Control-integrationen i Home Assistant. Lokal styring virker uden den.</small>}
    </div>}
  </div>;
}
