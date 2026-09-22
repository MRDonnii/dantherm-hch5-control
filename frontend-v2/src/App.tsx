import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { DiagnosticsPage } from "./pages/DiagnosticsPage";
import { HistoryPage } from "./pages/HistoryPage";
import { HomeAssistantPage } from "./pages/HomeAssistantPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SystemPage } from "./pages/SystemPage";
import { TechniquePage } from "./pages/TechniquePage";
import { UpdatesPage } from "./pages/UpdatesPage";
export function App(){return <AppShell><Routes><Route path="/" element={<Navigate to="/overview" replace/>}/><Route path="/overview" element={<OverviewPage/>}/><Route path="/history" element={<HistoryPage/>}/><Route path="/technique" element={<TechniquePage/>}/><Route path="/system" element={<SystemPage/>}/><Route path="/home-assistant" element={<HomeAssistantPage/>}/><Route path="/diagnostics" element={<DiagnosticsPage/>}/><Route path="/updates" element={<UpdatesPage />}/><Route path="/settings" element={<SettingsPage/>}/><Route path="*" element={<Navigate to="/overview" replace/>}/></Routes></AppShell>}
