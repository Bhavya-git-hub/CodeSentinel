import { NavLink } from "react-router-dom";

import "../components/Findings.css";

export function ScanTabs({ id }: { id: string }) {
  return (
    <nav className="tabs">
      <NavLink to={`/scans/${id}`} end>
        Queue
      </NavLink>
      <NavLink to={`/scans/${id}/findings`}>Findings</NavLink>
      <NavLink to={`/scans/${id}/impact`}>Impact</NavLink>
      <NavLink to={`/scans/${id}/report`}>Report</NavLink>
    </nav>
  );
}
