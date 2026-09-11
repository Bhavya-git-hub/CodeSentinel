import type { FileRisk, RiskQueue } from "../api/types";
import { Bar, Metric } from "./Value";
import "./RiskTable.css";

export type SortKey = "risk_score" | "churn_score" | "cyclomatic_complexity" | "loc";

/**
 * Ranks files, keeping unmeasurable ones at the bottom.
 *
 * Mirrors the database index, which is DESC NULLS LAST. An unknown is not a low score --
 * a file Radon could not parse may well be the worst in the repository -- but it must not
 * outrank a file that was actually measured and found dangerous. Last, and visibly
 * unknown, is the only honest position for it.
 */
export function sortFiles(files: FileRisk[], key: SortKey): FileRisk[] {
  return [...files].sort((a, b) => {
    const left = a[key];
    const right = b[key];
    if (left === null && right === null) return a.path.localeCompare(b.path);
    if (left === null) return 1;
    if (right === null) return -1;
    if (left === right) return a.path.localeCompare(b.path);
    return right - left;
  });
}

/**
 * When no file has a risk score, ranking by risk would produce an arbitrary order that
 * still looks authoritative. Falling back to churn ranks by the half that was actually
 * measured, and the caveat above the table says so.
 */
function rankingKey(queue: RiskQueue): SortKey {
  const anyRanked = queue.files.some((file) => file.risk_score !== null);
  return anyRanked ? "risk_score" : "churn_score";
}

export function RiskTable({ queue }: { queue: RiskQueue }) {
  const key = rankingKey(queue);
  const files = sortFiles(queue.files, key);
  const reasons = Object.entries(queue.analyzer_statuses);

  return (
    <section className="queue">
      <div className="queue__head">
        <h2>Review queue</h2>
        {queue.unmeasured > 0 ? (
          <p className="queue__caveat">
            {queue.unmeasured} of {queue.total_files} files could not be ranked. They are
            unknown rather than safe
            {key === "churn_score"
              ? ", so this list is ordered by churn alone — half the model."
              : ", and they are listed last."}
          </p>
        ) : (
          <p className="queue__caveat">
            All {queue.total_files} files were measured and ranked.
          </p>
        )}
        {reasons.map(([name, detail]) => (
          <p key={name} className="queue__reason">
            <span className="queue__analyzer">{name}</span>
            <span>{detail.error ?? "reported no detail"}</span>
          </p>
        ))}
      </div>

      <div className="queue__scroll">
        <table className="queue__table">
          <thead>
            <tr>
              <th scope="col">File</th>
              <th scope="col">Lines</th>
              <th scope="col">Complexity</th>
              <th scope="col">Churn</th>
              <th scope="col">Weighting</th>
              <th scope="col">Risk</th>
            </tr>
          </thead>
          <tbody>
            {files.map((file) => (
              <tr
                key={file.path}
                className={file.risk_score === null ? "row--unknown" : undefined}
              >
                <th scope="row">
                  <span className="path">{file.path}</span>
                  {file.is_test ? <span className="tag">test</span> : null}
                </th>
                <td>
                  <Metric value={file.loc} />
                </td>
                <td>
                  <Metric value={file.cyclomatic_complexity} digits={1} />
                </td>
                <td>
                  <Metric value={file.churn_score} digits={1} />
                </td>
                <td>
                  <Bar
                    value={file.normalized_churn}
                    label={`churn weighting for ${file.path}`}
                  />
                </td>
                <td>
                  <Metric value={file.risk_score} digits={3} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
