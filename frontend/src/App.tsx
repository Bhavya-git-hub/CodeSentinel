import { Route, Routes } from "react-router-dom";

import { IS_DEMO } from "./api/source";
import { Shell } from "./components/Shell";
import { FindingsPage } from "./pages/FindingsPage";
import { ImpactPage } from "./pages/ImpactPage";
import { Landing } from "./pages/Landing";
import { ReportPage } from "./pages/ReportPage";
import { ScanDetailPage } from "./pages/ScanDetailPage";
import { ScansPage } from "./pages/ScansPage";
import { SettingsPage } from "./pages/SettingsPage";

export function App() {
  return (
    <Shell isDemo={IS_DEMO}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/scans" element={<ScansPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/scans/:id" element={<ScanDetailPage />} />
        <Route path="/scans/:id/findings" element={<FindingsPage />} />
        <Route path="/scans/:id/impact" element={<ImpactPage />} />
        <Route path="/scans/:id/report" element={<ReportPage />} />
      </Routes>
    </Shell>
  );
}
