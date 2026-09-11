import { useParams } from "react-router-dom";

import { RiskTable } from "../components/RiskTable";
import { StatusPill } from "../components/Value";
import { usePolledScan } from "../hooks/useScan";
import { ScanTabs } from "./ScanTabs";
import "./Pages.css";

export function ScanDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { scan, queue, error, loading } = usePolledScan(id);

  if (error) {
    return (
      <div className="page">
        <h1>This scan could not be loaded</h1>
        <p className="error">{error}</p>
        <p className="muted">
          Nothing is shown in place of the missing data. An empty queue and an unreachable
          API are different facts.
        </p>
      </div>
    );
  }

  if (loading || !scan) {
    return (
      <div className="page">
        <p className="muted">Loading scan&hellip;</p>
      </div>
    );
  }

  return (
    <div className="page">
      {id ? <ScanTabs id={id} /> : null}
      <header className="page__head">
        <div className="page__title">
          <h1>Scan</h1>
          <StatusPill status={scan.status} />
        </div>
        <dl className="facts">
          <div>
            <dt>Commit</dt>
            <dd className="mono">{scan.commit_sha?.slice(0, 12) ?? "not resolved"}</dd>
          </div>
          <div>
            <dt>Files</dt>
            <dd className="mono">{scan.file_count}</dd>
          </div>
          <div>
            <dt>Commits mined</dt>
            <dd className="mono">{scan.commit_count}</dd>
          </div>
        </dl>
      </header>

      {scan.error ? <p className="error">{scan.error}</p> : null}
      {queue ? (
        <RiskTable queue={queue} />
      ) : (
        <p className="muted">Waiting for the scan to finish.</p>
      )}
    </div>
  );
}
