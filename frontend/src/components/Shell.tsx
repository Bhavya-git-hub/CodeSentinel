import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import "./Shell.css";

/**
 * Says, permanently and without being dismissible, that the figures on screen are
 * samples.
 *
 * Not a toast and not a one-time notice: the whole product is a claim about a real
 * repository, so a reader arriving mid-page must still be able to tell that these
 * numbers describe nothing they own.
 */
export function DemoBanner({ isDemo }: { isDemo: boolean }) {
  if (!isDemo) return null;
  return (
    <div className="demo" role="status">
      Sample data: a real scan of <strong>encode/starlette</strong> &mdash; 150 files,
      1,665 commits &mdash; run without a Docker daemon, so complexity and coverage are
      genuinely unmeasured. Nothing here was scanned just now.
    </div>
  );
}

export function Shell({ isDemo, children }: { isDemo: boolean; children: ReactNode }) {
  return (
    <>
      <DemoBanner isDemo={isDemo} />
      <header className="masthead">
        <NavLink to="/" className="wordmark">
          <span className="wordmark__mark" aria-hidden="true" />
          CodeSentinel
        </NavLink>
        <nav className="nav">
          <NavLink to="/" end>
            Overview
          </NavLink>
          <NavLink to="/scans">Scans</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
      </header>
      <main>{children}</main>
      <footer className="footer">
        Ranks files by complexity and recency-weighted churn. Says plainly what it could
        not measure.
      </footer>
    </>
  );
}
