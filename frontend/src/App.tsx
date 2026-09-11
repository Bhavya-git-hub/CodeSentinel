import { Route, Routes } from "react-router-dom";

import { IS_DEMO } from "./api/source";
import { Shell } from "./components/Shell";
import { Landing } from "./pages/Landing";
import { ScanDetailPage } from "./pages/ScanDetailPage";
import { ScansPage } from "./pages/ScansPage";

export function App() {
  return (
    <Shell isDemo={IS_DEMO}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/scans" element={<ScansPage />} />
        <Route path="/scans/:id" element={<ScanDetailPage />} />
      </Routes>
    </Shell>
  );
}
