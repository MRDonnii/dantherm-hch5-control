import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  BarChart3,
  CalendarClock,
  Boxes,
  ChevronLeft,
  ChevronRight,
  Gauge,
  Home,
  LogOut,
  Moon,
  RefreshCw,
  Ruler,
  Settings,
  Sun,
  UserRound,
  Wrench,
  Zap,
} from "lucide-react";
import { postJson, requestJson } from "../lib/api";
import { TopbarNoticeContext } from "../lib/topbar-notice";
import { haLinkText, readHaLink } from "../lib/haLink";
import { ROLE_NAMES, SessionContext, sessionCan, type AuthStatus, type Permission } from "../lib/session";
import { TopbarWeather } from "./TopbarWeather";

const navigation = [
  ["/overview", "Overblik", Home, null],
  ["/history", "Historik", BarChart3, null],
  ["/schedule", "Ugeplan", CalendarClock, null],
  ["/technique", "Teknik", Gauge, "diagnostics"],
  ["/system", "System", Boxes, "system"],
  ["/home-assistant", "Home Assistant", Zap, "configure"],
  ["/diagnostics", "Diagnostik", Wrench, "diagnostics"],
  ["/balancing", "Indregulering", Ruler, "configure"],
  ["/updates", "Opdateringer", RefreshCw, "system"],
  ["/settings", "Indstillinger", Settings, null],
] as const satisfies readonly (readonly [string, string, unknown, Permission | null])[];

/** Pages that need a role above a plain user. */
export const ROUTE_PERMISSIONS: Record<string, Permission> = Object.fromEntries(
  navigation.filter(item => item[3] !== null).map(item => [item[0], item[3] as Permission]),
);

const routeTitles: Record<string, [string, string]> = {
  "/overview": ["Overblik", "Aktuel drift og status for dit HCH5 ventilationsanlæg"],
  "/history": ["Historik", "Udvikling i temperaturer, luftkvalitet og drift"],
  "/schedule": ["Ugeplan", "Ugens rytme, perioder og ferie"],
  "/technique": ["Teknik", "Controller, bus og hardwarestatus"],
  "/system": ["System", "Raspberry Pi, services og gateway"],
  "/home-assistant": ["Home Assistant", "Integration og smart-data"],
  "/diagnostics": ["Diagnostik", "Fejlsøgning og rå systemdata"],
  "/balancing": ["Indregulering", "Luftmængder pr. rum, måling og rapport"],
  "/updates": ["Opdateringer", "Software, kanal og failsafe-opdatering"],
  "/settings": ["Indstillinger", "Udseende, brugere, mail og lokale præferencer"],
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
  const [auth, setAuth] = useState<AuthStatus>({});
  const [authLoading, setAuthLoading] = useState(true);

  const refreshAuth = useCallback(async () => {
    try { setAuth(await requestJson<AuthStatus>("/api/auth/status", { timeoutMs: 3500 })); }
    catch { /* keep the last known session; the server still enforces every request */ }
    finally { setAuthLoading(false); }
  }, []);
  useEffect(() => { void refreshAuth(); }, [refreshAuth]);
  const session = useMemo(() => ({
    auth, loading: authLoading, refresh: refreshAuth,
    can: (permission: Permission) => sessionCan(auth, permission),
  }), [auth, authLoading, refreshAuth]);
  const haLink = readHaLink(unit);
  const haInfo = haLinkText(haLink);
  // Only shown once Home Assistant is part of the setup (has been seen, or Smart Auto needs it).
  const haVisible = haLink.state !== null && (haLink.state !== "never" || haLink.required);
  const haChipContent = <><span className="live-dot" />HA{haLink.state !== "online" && <small>{haInfo.label}</small>}</>;
  const haChip = !haVisible ? null : sessionCan(auth, "configure")
    ? <NavLink to="/home-assistant" className={`status-chip ha-chip tone-${haInfo.tone}`} title={`Home Assistant: ${haInfo.label}. ${haInfo.detail}`}>{haChipContent}</NavLink>
    : <span className={`status-chip ha-chip tone-${haInfo.tone}`} title={`Home Assistant: ${haInfo.label}. ${haInfo.detail}`}>{haChipContent}</span>;
  const visibleNavigation = navigation.filter(item => item[3] === null || session.can(item[3]));
  const logout = async () => {
    try { await postJson("/api/auth/logout", {}, auth.csrf ?? undefined); } catch { /* go to login regardless */ }
    window.location.href = "/login";
  };

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
          {visibleNavigation.map(([to, label, Icon]) => (
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
            <TopbarWeather />
            {availableUpdate && session.can("system") && <NavLink className="topbar-update-tab" to="/updates" title={availableUpdate}><RefreshCw size={15}/><span>{availableUpdate === "Installerer opdatering" ? availableUpdate : "Opdatering klar"}</span>{availableUpdate !== "Installerer opdatering" && <small>{availableUpdate}</small>}</NavLink>}
            <div className="topbar-clock"><strong>{now.toLocaleTimeString("da-DK", { hour: "2-digit", minute: "2-digit" })}</strong><span>{now.toLocaleDateString("da-DK", { day: "2-digit", month: "short", year: "numeric" })}</span></div>
            {notice && <div className={`topbar-control-notice${notice.startsWith("Kunne") ? " error" : ""}`} role="status" title={notice}><strong>Seneste ændring</strong><span>{notice}</span></div>}
            <span className={`status-chip${online ? "" : " muted"}`} title={online ? "Forbindelse til anlægget" : "Venter på data fra anlægget"}><span className="live-dot" /> {online ? "Forbundet" : "Afventer"}</span>
            {haChip}
            <button className="icon-button" type="button" onClick={() => setTheme(effectiveTheme === "dark" ? "light" : "dark")} aria-label="Skift tema">
              {effectiveTheme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            {auth.username && <div className="topbar-user" title={auth.role ? ROLE_NAMES[auth.role].da : undefined}>
              <UserRound size={16} />
              <span><strong>{auth.username}</strong>{auth.role && <small>{ROLE_NAMES[auth.role].da}</small>}</span>
              {auth.enabled !== false && <button className="icon-button" type="button" onClick={() => void logout()} aria-label="Log ud" title="Log ud"><LogOut size={16} /></button>}
            </div>}
          </div>
        </header>
        <SessionContext.Provider value={session}>
          <TopbarNoticeContext.Provider value={noticeContext}>
            <main className="content-stage">{children}</main>
          </TopbarNoticeContext.Provider>
        </SessionContext.Provider>
      </div>
    </div>
  );
}
