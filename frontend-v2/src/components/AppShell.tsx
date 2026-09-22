import { useEffect, useMemo, useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import {
  Activity,
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

type ThemeMode = "system" | "light" | "dark";

function readStored<T extends string>(key: string, fallback: T): T {
  try {
    return (localStorage.getItem(key) as T | null) ?? fallback;
  } catch {
    return fallback;
  }
}

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(() => readStored("hch5-v2-sidebar", "0") === "1");
  const [theme, setTheme] = useState<ThemeMode>(() => readStored("hch5-v2-theme", "system"));
  const effectiveTheme = useMemo(() => {
    if (theme !== "system") return theme;
    return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }, [theme]);

  useEffect(() => {
    document.documentElement.dataset.theme = effectiveTheme;
    try { localStorage.setItem("hch5-v2-theme", theme); } catch {}
  }, [theme, effectiveTheme]);

  useEffect(() => {
    document.body.dataset.sidebar = collapsed ? "collapsed" : "expanded";
    try { localStorage.setItem("hch5-v2-sidebar", collapsed ? "1" : "0"); } catch {}
  }, [collapsed]);

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Primær navigation">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true"><Activity size={24} /></div>
          {!collapsed && <div className="brand-copy"><strong>HCH5 Control</strong><span>Smart ventilation</span></div>}
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

        <div className="sidebar-health">
          <span className="live-dot" />
          {!collapsed && <div><strong>Controller online</strong><span>Afventer live health</span></div>}
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar-v2">
          <div>
            <span className="eyebrow">LOCAL FIRST · HCH5 MK1</span>
            <strong className="topbar-title">Ventilation controller</strong>
          </div>
          <div className="topbar-actions">
            <span className="status-chip"><span className="live-dot" /> Forbundet</span>
            <button className="icon-button" type="button" onClick={() => setTheme(effectiveTheme === "dark" ? "light" : "dark")} aria-label="Skift tema">
              {effectiveTheme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            </button>
          </div>
        </header>
        <main className="content-stage">{children}</main>
      </div>
    </div>
  );
}
