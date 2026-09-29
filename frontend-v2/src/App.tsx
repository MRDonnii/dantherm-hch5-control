import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell, ROUTE_PERMISSIONS } from "./components/AppShell";
import { useSession } from "./lib/session";
import { DiagnosticsPage } from "./pages/DiagnosticsPage";
import { HistoryPage } from "./pages/HistoryPage";
import { HomeAssistantPage } from "./pages/HomeAssistantPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SchedulePage } from "./pages/SchedulePage";
import { SettingsPage } from "./pages/SettingsPage";
import { SystemPage } from "./pages/SystemPage";
import { TechniquePage } from "./pages/TechniquePage";
import { UpdatesPage } from "./pages/UpdatesPage";

/** Technician/administrator pages; the server enforces the same rules on every request. */
function Guard({ path, children }: { path: string; children: ReactNode }) {
  const { can, loading } = useSession();
  const needed = ROUTE_PERMISSIONS[path];
  if (!needed || loading || can(needed)) return <>{children}</>;
  return <Navigate to="/overview" replace />;
}

const guarded = (path: string, page: ReactNode) => <Route path={path} element={<Guard path={path}>{page}</Guard>} />;

export function App() {
  return <AppShell><Routes>
    <Route path="/" element={<Navigate to="/overview" replace/>}/>
    <Route path="/overview" element={<OverviewPage/>}/>
    <Route path="/history" element={<HistoryPage/>}/>
    <Route path="/schedule" element={<SchedulePage/>}/>
    {guarded("/technique", <TechniquePage/>)}
    {guarded("/system", <SystemPage/>)}
    {guarded("/home-assistant", <HomeAssistantPage/>)}
    {guarded("/diagnostics", <DiagnosticsPage/>)}
    {guarded("/updates", <UpdatesPage />)}
    <Route path="/settings" element={<SettingsPage/>}/>
    <Route path="*" element={<Navigate to="/overview" replace/>}/>
  </Routes></AppShell>;
}
