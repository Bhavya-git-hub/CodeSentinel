import type { FindingItem, FindingsPage, Severity } from "../api/types";
import { SEVERITY_ORDER } from "../api/types";
import "./Findings.css";

/**
 * Severity is one hue at four intensities, not a traffic light.
 *
 * A red/amber/green ramp would put amber on screen, and amber already means something
 * else here: nothing. Unknown is slate with a hatch, deliberately desaturated, and a
 * second warm colour a few pixels away would make "we could not measure this" and "this
 * is a moderate problem" read as neighbours on one scale. They are not on a scale at all.
 *
 * So severity ramps a single alarm hue by intensity, and the only other saturated colour
 * on the page stays phosphor, which means measured.
 */
export function SeverityTag({ severity }: { severity: Severity }) {
  return <span className={`sev sev--${severity}`}>{severity}</span>;
}

function SeveritySummary({ counts }: { counts: Partial<Record<Severity, number>> }) {
  const present = SEVERITY_ORDER.filter((s) => (counts[s] ?? 0) > 0);
  if (present.length === 0) return null;

  return (
    <div className="sev-summary">
      {present.map((severity) => (
        <span key={severity} className="sev-summary__item">
          <SeverityTag severity={severity} />
          <span className="sev-summary__count">{counts[severity]}</span>
        </span>
      ))}
    </div>
  );
}

/** Worst first, and a stable order within a severity so the list does not shuffle. */
export function sortFindings(findings: FindingItem[]): FindingItem[] {
  const rank = (s: Severity) => SEVERITY_ORDER.indexOf(s);
  return [...findings].sort(
    (a, b) =>
      rank(a.severity) - rank(b.severity) ||
      a.analyzer.localeCompare(b.analyzer) ||
      a.rule_id.localeCompare(b.rule_id),
  );
}

export function Findings({ page }: { page: FindingsPage }) {
  const findings = sortFindings(page.findings);
  const reasons = Object.entries(page.analyzer_statuses).filter(([, d]) => d.error);

  return (
    <section className="findings">
      <header className="findings__head">
        <h2>Findings</h2>
        {page.total === 0 ? (
          <p className="muted">
            {reasons.length > 0
              ? "No findings were recorded — but at least one analyser did not complete, so this is not a clean result."
              : "No findings. Every analyser ran and reported nothing."}
          </p>
        ) : (
          <p className="muted">
            {page.total} across the repository. Counts are for the whole scan, not just
            the {findings.length} shown.
          </p>
        )}
        <SeveritySummary counts={page.by_severity} />
        {reasons.map(([name, detail]) => (
          <p key={name} className="findings__reason">
            <span className="findings__analyzer">{name}</span>
            <span>{detail.error}</span>
          </p>
        ))}
      </header>

      {findings.length > 0 ? (
        <ol className="findings__list">
          {findings.map((finding, index) => (
            <li key={`${finding.analyzer}-${finding.rule_id}-${index}`} className="finding">
              <div className="finding__top">
                <SeverityTag severity={finding.severity} />
                <span className="finding__rule">{finding.rule_id}</span>
                <span className="finding__analyzer">{finding.analyzer}</span>
              </div>
              <p className="finding__message">{finding.message}</p>
              <p className="finding__where">
                {finding.path ? (
                  <>
                    <span className="path">{finding.path}</span>
                    {finding.line_start !== null ? (
                      <span className="finding__line">:{finding.line_start}</span>
                    ) : null}
                  </>
                ) : (
                  // Kept rather than dropped: the analyser could not attribute it to a
                  // file in the inventory, and omitting it would shrink the count.
                  <span className="finding__unattributed">
                    not attributed to a file in this repository
                  </span>
                )}
              </p>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
