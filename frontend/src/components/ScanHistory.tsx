import { Link } from "react-router-dom";

import type { ScanList } from "../api/types";
import { StatusPill } from "./Value";
import "./ScanHistory.css";

/**
 * How long a scan took, or null when it is still running.
 *
 * Null rather than "0s" or a dash for a scan with no `completed_at`. The duration of an
 * unfinished scan is not zero and it is not nothing -- it is unknown, and this product
 * renders unknown one way everywhere.
 */
export function durationSeconds(started: string, completed: string | null): number | null {
  if (completed === null) return null;
  const elapsed = Date.parse(completed) - Date.parse(started);
  return Number.isFinite(elapsed) ? elapsed / 1000 : null;
}

function Duration({ seconds }: { seconds: number | null }) {
  if (seconds === null) {
    return (
      <span className="value value--unknown" title="Still running, or never completed">
        None
      </span>
    );
  }
  const rendered = seconds >= 60 ? `${(seconds / 60).toFixed(1)}m` : `${seconds.toFixed(0)}s`;
  return <span className="value value--measured">{rendered}</span>;
}

/**
 * The scan history.
 *
 * `total` is rendered beside the page rather than inferred from `scans.length`, because
 * those are different numbers the moment a history outgrows one page, and a reader who
 * takes the visible count as the whole history draws exactly the wrong conclusion about
 * how much this instance has looked at.
 *
 * A failed scan shows its reason inline. The list is where someone goes to find out what
 * went wrong, and making them open each row to discover which ones failed and why is the
 * kind of hiding this project treats as a defect.
 */
export function ScanHistory({ page }: { page: ScanList }) {
  if (page.total === 0) {
    return (
      <p className="muted history__empty">
        No scans yet. This instance has not analysed anything &mdash; which is different
        from having analysed things and found nothing.
      </p>
    );
  }

  return (
    <div className="history">
      <p className="history__count muted">
        Showing {page.scans.length} of {page.total}{" "}
        {page.total === 1 ? "scan" : "scans"}.
      </p>
      <div className="history__scroll">
        <table className="history__table">
          <caption className="sr-only">Scans, newest first</caption>
          <thead>
            <tr>
              <th scope="col">Repository</th>
              <th scope="col">Status</th>
              <th scope="col">Commit</th>
              <th scope="col">Started</th>
              <th scope="col">Took</th>
            </tr>
          </thead>
          <tbody>
            {page.scans.map((scan) => (
              <tr key={scan.scan_id}>
                <td>
                  <Link className="path" to={`/scans/${scan.scan_id}`}>
                    {scan.repository_name}
                  </Link>
                  {scan.error ? <p className="history__error">{scan.error}</p> : null}
                </td>
                <td>
                  <StatusPill status={scan.status} />
                </td>
                <td className="mono">
                  {/* Null until the clone resolves the ref -- not an empty string. */}
                  {scan.commit_sha === null ? (
                    <span className="value value--unknown" title="Not resolved yet">
                      None
                    </span>
                  ) : (
                    scan.commit_sha.slice(0, 8)
                  )}
                </td>
                <td className="mono">{new Date(scan.started_at).toLocaleString()}</td>
                <td>
                  <Duration seconds={durationSeconds(scan.started_at, scan.completed_at)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
