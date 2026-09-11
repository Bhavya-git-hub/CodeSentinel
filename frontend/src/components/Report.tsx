import type { ScanReport } from "../api/types";
import { RiskTable } from "./RiskTable";
import { Metric, StatusPill } from "./Value";
import "./Findings.css";

/**
 * A count that says whether it is a measurement or an absence.
 *
 * `0` and "nothing was measured" look identical as bare numbers, and this is the page
 * where that confusion does the most damage: a reader skimming a report is looking for
 * reassurance and will take a row of zeroes as one.
 */
function Stat({
  label,
  value,
  unknownWhenZero = false,
}: {
  label: string;
  value: number;
  unknownWhenZero?: boolean;
}) {
  const unknown = unknownWhenZero && value === 0;
  return (
    <div className="report__stat">
      <dt>{label}</dt>
      <dd className={unknown ? "is-unknown" : undefined}>{unknown ? "none" : value}</dd>
    </div>
  );
}

export function Report({ report }: { report: ScanReport }) {
  return (
    <section className="report">
      <header className="page__head">
        <div className="page__title">
          <h2>Report</h2>
          <StatusPill status={report.status} />
        </div>
        <p className="muted">
          Commit <span className="mono">{report.commit_sha?.slice(0, 12) ?? "not resolved"}</span>
          {" · "}
          {report.file_count} files, {report.commit_count} commits mined.
        </p>
      </header>

      <dl className="report__grid">
        <Stat label="Files ranked" value={report.files_ranked} unknownWhenZero />
        <Stat label="Files unmeasured" value={report.files_unmeasured} />
        <Stat label="Findings" value={report.findings_total} />
        <Stat label="Import edges" value={report.dependency_edges} />
        <Stat label="Edges unresolved" value={report.dependency_edges_unresolved} />
        <Stat label="Files with coverage" value={report.coverage_measured_files} unknownWhenZero />
        <Stat label="Commits labelled" value={report.commits_labelled} unknownWhenZero />
        <Stat label="Defect-inducing" value={report.commits_defect_inducing} unknownWhenZero />
      </dl>

      {/* Limitations come before the findings, deliberately. They change how every
          number above should be read, and a reader who meets them afterwards has
          already formed a conclusion. */}
      {report.limitations.length > 0 ? (
        <section className="findings">
          <h2>What this scan could not determine</h2>
          <div className="limits">
            {report.limitations.map((limit) => (
              <div className="limit" key={limit.subject}>
                <span className="limit__subject">{limit.subject}</span>
                <p className="limit__detail">{limit.detail}</p>
                <p className="limit__consequence">{limit.consequence}</p>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {report.top_defect_risks.length > 0 ? (
        <section className="findings">
          <h2>Commits most likely to have introduced a defect</h2>
          <p className="muted">
            Modelled by <span className="mono">{report.top_defect_risks[0]?.model_version}</span>{" "}
            from this repository&rsquo;s own fix history.
          </p>
          <div className="impact__rows">
            {report.top_defect_risks.map((commit) => (
              <div className="impact__row" key={commit.commit_sha}>
                <span className="path">{commit.commit_sha.slice(0, 12)}</span>
                <span className="impact__hops">{commit.model_version}</span>
                <Metric value={commit.defect_probability} digits={3} />
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {report.top_risks.length > 0 ? (
        <RiskTable
          queue={{
            scan_id: report.scan_id,
            status: report.status,
            total_files: report.files_ranked + report.files_unmeasured,
            unmeasured: report.files_unmeasured,
            analyzer_statuses: report.analyzer_statuses,
            files: report.top_risks,
          }}
        />
      ) : null}

      <section className="findings">
        <h2>Configuration this scan ran under</h2>
        <p className="muted">
          Stored with the result, so the numbers stay interpretable after the settings
          change.
        </p>
        <div className="impact__rows">
          {Object.entries(report.config).map(([key, value]) => (
            <div className="impact__row" key={key}>
              <span className="path">{key}</span>
              <span />
              <span className="mono">{JSON.stringify(value)}</span>
            </div>
          ))}
        </div>
      </section>
    </section>
  );
}
