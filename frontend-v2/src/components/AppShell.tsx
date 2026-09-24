import { useEffect, useMemo, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  BarChart3,
  Boxes,
  ChevronLeft,
  ChevronRight,
  Gauge,
  Home,
  Moon,
  RefreshCw,
  Settings,
  Sun,
  Wrench,
  Zap,
} from "lucide-react";
import { postJson, requestJson } from "../lib/api";
import { TopbarNoticeContext } from "../lib/topbar-notice";

const navigation = [
  ["/overview", "Overblik", Home],
  ["/history", "Historik", BarChart3],
  ["/technique", "Teknik", Gauge],
  ["/system", "System", Boxes],
  ["/home-assistant", "Home Assistant", Zap],
  ["/diagnostics", "Diagnostik", Wrench],
  ["/updates", "Opdateringer", RefreshCw],
  ["/settings", "Indstillinger", Settings],
] as const;

const routeTitles: Record<string, [string, string]> = {
  "/overview": ["Overblik", "Aktuel drift og status for dit HCH5 ventilationsanlæg"],
  "/history": ["Historik", "Udvikling i temperaturer, luftkvalitet og drift"],
  "/technique": ["Teknik", "Controller, bus og hardwarestatus"],
  "/system": ["System", "Raspberry Pi, services og gateway"],
  "/home-assistant": ["Home Assistant", "Integration og smart-data"],
  "/diagnostics": ["Diagnostik", "Fejlsøgning og rå systemdata"],
  "/updates": ["Opdateringer", "Software, kanal og failsafe-opdatering"],
  "/settings": ["Indstillinger", "Udseende, login og lokale præferencer"],
};

type ThemeMode = "system" | "light" | "dark";
type UnitState = Record<string, unknown>;
type UpdateInfo = { update_available?: boolean; available_version?: string; update?: { running?: boolean } };

function readStored(key: string, fallback: string): string {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}
function readTheme(): ThemeMode {
  const value = readStored("hch5-v2-theme", "dark");
  return value === "light" || value === "dark" ? value : "system";
}

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(() => readStored("hch5-v2-sidebar", "0") === "1");
  const [theme, setTheme] = useState<ThemeMode>(readTheme);
  const [now, setNow] = useState(new Date());
  const [unit, setUnit] = useState<UnitState>({});
  const [online, setOnline] = useState(false);
  const [version, setVersion] = useState("—");
  const [notice, setNotice] = useState("");
  const [availableUpdate, setAvailableUpdate] = useState<string | null>(null);

  const effectiveTheme = useMemo(() => {
    if (theme !== "system") return theme;
    return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }, [theme]);
  const noticeContext = useMemo(() => ({ notice, setNotice }), [notice]);
  const [title, subtitle] = routeTitles[location.pathname] ?? ["HCH5 Control", "Local ventilation controller"];

  useEffect(() => {
    document.documentElement.dataset.theme = effectiveTheme;
    try { localStorage.setItem("hch5-v2-theme", theme); } catch {}
  }, [theme, effectiveTheme]);

  useEffect(() => {
    const syncPreferences = () => {
      setTheme(readTheme());
      setCollapsed(readStored("hch5-v2-sidebar", "0") === "1");
      document.documentElement.dataset.motion = readStored("hch5-v2-motion", "normal");
    };
    syncPreferences();
    window.addEventListener("hch5-ui-preferences", syncPreferences);
    return () => window.removeEventListener("hch5-ui-preferences", syncPreferences);
  }, []);

  useEffect(() => {
    document.body.dataset.sidebar = collapsed ? "collapsed" : "expanded";
    try { localStorage.setItem("hch5-v2-sidebar", collapsed ? "1" : "0"); } catch {}
  }, [collapsed]);

  useEffect(() => {
    const tick = window.setInterval(() => setNow(new Date()), 30000);
    return () => window.clearInterval(tick);
  }, []);

  useEffect(() => { setNotice(""); }, [location.pathname]);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const auth = await requestJson<{ csrf?: string | null }>("/api/auth/status", { timeoutMs: 3500 });
        if (!auth.csrf) return;
        const result = await postJson<UpdateInfo>("/api/admin/action", { action: "check_update", target: "beta" }, auth.csrf);
        if (!cancelled) setAvailableUpdate(result.update?.running ? "Installerer opdatering" : result.update_available ? result.available_version ?? "Opdatering klar" : null);
      } catch {
        // A temporarily unavailable update service must not affect control.
      }
    };
    void check();
    const timer = window.setInterval(() => void check(), 60000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await requestJson<UnitState>("/state.json", { timeoutMs: 2500 });
        if (cancelled) return;
        setUnit(next);
        setOnline(next.available === true || next.bus_traffic === true);
        const versionValue = next.version ?? next.app_version ?? next.gateway_version;
        if (versionValue) setVersion(String(versionValue));
      } catch {
        if (!cancelled) setOnline(false);
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 5000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Primær navigation">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true"><img src="/assets/brand-mark.svg" alt="" width="40" height="40" /></div>
          {!collapsed && <div className="brand-copy"><strong>HCH5 Control</strong><span>Modern local ventilation</span></div>}
          <button className="icon-button collapse-button" type="button" onClick={() => setCollapsed(value => !value)} aria-label={collapsed ? "Fold menu ud" : "Fold menu sammen"}>
            {collapsed ? <ChevronRight size={17} /> : <ChevronLeft size={17} />}
          </button>
        </div>

        <nav className="sidebar-nav">
          {navigation.map(([to, label, Icon]) => (
            <NavLink key={to} to={to} className={({ isActive }) => `nav-item${isActive ? " active" : ""}`} title={collapsed ? label : undefined}>
              <Icon size={18} strokeWidth={1.9} />
              {!collapsed && <span>{label}</span>}
            </NavLink>
          ))}
        </nav>

        {!collapsed && <div className="sidebar-product-note"><strong>HCH5 Control</strong><span>Kompatibel med Dantherm HCH5 MK1</span><small>Lokal styring · ingen cloud nødvendig</small></div>}
        <div className="sidebar-health">
          <span className={`live-dot${online ? "" : " offline"}`} />
          {!collapsed && <div><strong>{online ? "Anlæg online" : "Forbindelse afventer"}</strong><span>HCH5 MK1 · {version !== "—" ? `v${version}` : "lokal controller"}</span></div>}
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar-v2 pro-topbar">
          <div className="topbar-page-copy">
            <strong className="topbar-title">{title}</strong>
            <span>{subtitle}</span>
          </div>
          <div className="topbar-actions">
            {availableUpdate && <NavLink className="topbar-update-tab" to="/updates" title={availableUpdate}><RefreshCw size={15}/><span>{availableUpdate === "Installerer opdatering" ? availableUpdate : "Opdatering klar"}</span>{availableUpdate !== "Installerer opdatering" && <small>{availableUpdate}</small>}</NavLink>}
            <div className="topbar-clock"><strong>{now.toLocaleTimeString("da-DK", { hour: "2-digit", minute: "2-digit" })}</strong><span>{now.toLocaleDateString("da-DK", { day: "2-digit", month: "short", year: "numeric" })}</span></div>
            {notice && <div className={`topbar-control-notice${notice.startsWith("Kunne") ? " error" : ""}`} role="status" title={notice}><strong>Seneste ændring</strong><span>{notice}</span></div>}
            <span className={`status-chip${online ? "" : " muted"}`}><span className="live-dot" /> {online ? "Forbundet" : "Afventer"}</span>
            <button className="icon-button" type="button" onClick={() => setTheme(effectiveTheme === "dark" ? "light" : "dark")} aria-label="Skift tema">
              {effectiveTheme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            </button>
          </div>
        </header>
        <TopbarNoticeContext.Provider value={noticeContext}>
          <main className="content-stage">{children}</main>
        </TopbarNoticeContext.Provider>
      </div>
    </div>
  );
}
