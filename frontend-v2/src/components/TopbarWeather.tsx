import { useEffect, useState, type FormEvent } from "react";
import { Cloud, CloudRain, CloudSnow, CloudSun, MapPin, Sun } from "lucide-react";

type Place = { name: string; latitude: number; longitude: number };
type Current = { temperature_2m: number; weather_code: number; is_day: number; time: string };
type AirQuality = { european_aqi: number; pm2_5: number; pm10: number; time: string };
const KEY = "hch5-weather-place";

function savedPlace(): Place | null {
  try {
    const value = JSON.parse(localStorage.getItem(KEY) || "null") as Place | null;
    return value && typeof value.name === "string" && Number.isFinite(value.latitude) && Number.isFinite(value.longitude) ? value : null;
  } catch { return null; }
}

function description(code: number) {
  if (code === 0) return "Klart";
  if (code <= 3) return "Skyet";
  if (code >= 71 && code <= 86) return "Sne";
  if (code >= 51 && code <= 67 || code >= 80 && code <= 82 || code >= 95) return "Regn";
  return "Diset";
}

export function TopbarWeather() {
  const [place, setPlace] = useState<Place | null>(savedPlace);
  const [current, setCurrent] = useState<Current | null>(null);
  const [air, setAir] = useState<AirQuality | null>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!place) return;
    let alive = true;
    const update = async () => {
      try {
        const params = new URLSearchParams({ latitude: String(place.latitude), longitude: String(place.longitude), current: "temperature_2m,weather_code,is_day", forecast_days: "1" });
        const response = await fetch(`https://api.open-meteo.com/v1/forecast?${params}`);
        if (!response.ok) throw new Error("Vejrtjenesten svarer ikke");
        const data = await response.json() as { current?: Current };
        if (!data.current || !Number.isFinite(data.current.temperature_2m)) throw new Error("Vejrdata mangler");
        if (alive) { setCurrent(data.current); setError(""); }
      } catch { if (alive) { setCurrent(null); setError("Vejrdata utilgængelige"); } }
      try {
        const params = new URLSearchParams({ latitude: String(place.latitude), longitude: String(place.longitude), current: "european_aqi,pm2_5,pm10", forecast_days: "1" });
        const response = await fetch(`https://air-quality-api.open-meteo.com/v1/air-quality?${params}`);
        if (!response.ok) throw new Error("Air quality unavailable");
        const data = await response.json() as { current?: AirQuality };
        if (!data.current || !Number.isFinite(data.current.european_aqi)) throw new Error("Air quality missing");
        if (alive) setAir(data.current);
      } catch { if (alive) setAir(null); }
    };
    void update();
    const timer = window.setInterval(() => void update(), 10 * 60 * 1000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [place]);

  const choose = async (event: FormEvent) => {
    event.preventDefault();
    if (query.trim().length < 2) return;
    try {
      const params = new URLSearchParams({ name: query.trim(), count: "1", language: "da" });
      const response = await fetch(`https://geocoding-api.open-meteo.com/v1/search?${params}`);
      if (!response.ok) throw new Error();
      const data = await response.json() as { results?: Place[] };
      const next = data.results?.[0];
      if (!next) { setError("Stedet blev ikke fundet"); return; }
      localStorage.setItem(KEY, JSON.stringify(next));
      setCurrent(null);
      setAir(null);
      setPlace(next);
      setOpen(false);
      setError("");
    } catch { setError("Kunne ikke slå stedet op"); }
  };

  const icon = current?.weather_code === 0 ? <Sun size={17}/> : current && current.weather_code >= 71 && current.weather_code <= 86 ? <CloudSnow size={17}/> : current && (current.weather_code >= 51 || current.weather_code >= 95) ? <CloudRain size={17}/> : current ? <CloudSun size={17}/> : <Cloud size={17}/>;
  return <div className="topbar-weather">
    <button type="button" className="topbar-weather-button" onClick={() => setOpen(value => !value)} aria-label="Vælg sted for live vejr" title={place ? `${place.name} · ${current ? `${Math.round(current.temperature_2m)} °C, ${description(current.weather_code)}` : error || "Henter vejr"}${air ? ` · EU luftindeks ${Math.round(air.european_aqi)}, PM2.5 ${air.pm2_5} µg/m³, PM10 ${air.pm10} µg/m³` : ""} · Open-Meteo / CAMS` : "Vælg sted for live vejr"}>
      {icon}<span>{place ? current ? `${Math.round(current.temperature_2m)} °C · ${description(current.weather_code)}` : error || "Henter vejr…" : "Vælg sted"}</span>{air && <small className="topbar-weather-aqi">EU {Math.round(air.european_aqi)}</small>}<small>{place?.name}</small>
    </button>
    {open && <form className="topbar-weather-picker" onSubmit={choose}>
      <label htmlFor="weather-place">Vejr for</label>
      <div><MapPin size={15}/><input id="weather-place" value={query} onChange={event => setQuery(event.target.value)} placeholder="By eller postnummer" autoFocus/><button type="submit">Vælg</button></div>
      {error && <small role="status">{error}</small>}
      <small>Vejr: Open-Meteo · Luft: CAMS via Open-Meteo</small>
    </form>}
  </div>;
}
