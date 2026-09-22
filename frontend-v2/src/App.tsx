import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { HistoryPage } from "./pages/HistoryPage";
import { OverviewPage } from "./pages/OverviewPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { UpdatesPage } from "./pages/UpdatesPage";

export function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Navigate to="/overview" replace />} />
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/technique" element={<PlaceholderPage eyebrow="Teknik" title="Controller og bus" description="Masterstatus, hardware writes, sensor freshness, readbacks og decision log — i samme app uden reload eller iframe." />} />
        <Route path="/system" element={<PlaceholderPage eyebrow="System" title="Raspberry Pi og gateway" description="Drift, services, netværk, ressourcer og versionsstatus med tydelig health state." />} />
        <Route path="/home-assistant" element={<PlaceholderPage eyebrow="Home Assistant" title="Integration" description="Forbindelse, entities og smart-data præsenteres uden at blande sig i den lokale sikkerhedsstyring." />} />
        <Route path="/diagnostics" element={<PlaceholderPage eyebrow="Diagnostik" title="Fejlsøgning" description="Rå data, busstatus, logs og sikre værktøjer samlet i en teknisk men overskuelig visning." />} />
        <Route path="/updates" element={<UpdatesPage />} />
        <Route path="/settings" element={<PlaceholderPage eyebrow="Indstillinger" title="Udseende og adgang" description="Tema, navigation, login og lokale præferencer med persistens på tværs af opdateringer." />} />
        <Route path="*" element={<Navigate to="/overview" replace />} />
      </Routes>
    </AppShell>
  );
}
