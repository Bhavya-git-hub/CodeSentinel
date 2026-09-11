import { Link } from "react-router-dom";

import { DEMO_SCAN, HERO_ROWS } from "../api/demo";
import { Bar, Metric } from "../components/Value";
import "./Pages.css";

/**
 * The hero is the product's most characteristic object: a ranked queue in which the
 * scores say None.
 *
 * A headline statistic over a gradient would be the default treatment and would say
 * nothing only this product can say. The queue says both things at once -- that files are
 * ranked, and that the ranking admits what it does not know.
 */
export function Landing() {
  return (
    <div className="page">
      <section className="hero">
        <h1>Read the dangerous code first.</h1>
        <p className="hero__lede">
          CodeSentinel ranks a repository&rsquo;s files by complexity multiplied by
          recency-weighted churn &mdash; and tells you which files it could not measure,
          instead of scoring them zero.
        </p>

        <div className="hero__queue">
          <div className="hero__queue-head" aria-hidden="true">
            <span>File</span>
            <span>Churn</span>
            <span className="hero__weight">Weighting</span>
            <span>Risk</span>
          </div>
          {HERO_ROWS.map((row) => (
            <div className="hero__row" key={row.path}>
              <span className="path">{row.path}</span>
              <Metric value={row.churn} digits={1} />
              {/* Wrapped so the stylesheet can drop this column at phone widths. It is
                  the only one that can go: churn is still a measured green figure
                  beside it, and Risk is the claim the page is making. */}
              <div className="hero__weight">
                <Bar value={row.weight} label={`churn weighting for ${row.path}`} />
              </div>
              <Metric value={null} />
            </div>
          ))}
          <p className="hero__note">
            Every risk score here reads <span className="mono">None</span>. Radon had no
            container to run in, so complexity is unknown &mdash; and an unknown component
            gives an unknown product, not a zero.
          </p>
        </div>

        <Link className="cta" to="/scans">
          Scan a repository
        </Link>
      </section>

      <section className="strip">
        <article>
          <h2>Complexity alone ranks badly.</h2>
          <p>
            Intricate code nobody touches is not where defects land. Churn alone is no
            better: a heavily edited trivial file is not worth a reviewer&rsquo;s morning.
            The product of the two is the claim this makes.
          </p>
        </article>
        <article>
          <h2>Recency is the whole point.</h2>
          <p>
            Churn decays on a 90-day half-life. Total lifetime churn would rank a file
            rewritten five years ago above one being rewritten this week, which is exactly
            backwards for deciding what to read.
          </p>
        </article>
        <article>
          <h2>Absence is reported, not filled in.</h2>
          <p>
            A file the parser could not read is not a simple file. A history of binary
            changes is not a file that never changed. Both are recorded as unknown, and
            they sort last rather than looking safe.
          </p>
        </article>
      </section>

      <section className="strip">
        <article>
          <h2>Untrusted code stays in a box.</h2>
          <p>
            Every analyser runs in a container with no network, a read-only mount, dropped
            capabilities and a non-root user. There is no argument that relaxes it.
          </p>
        </article>
        <article>
          <h2>Results carry their provenance.</h2>
          <p>
            Each scan stores the commit it read, the tool versions that read it, and the
            configuration in force. A number you cannot reproduce is a number you cannot
            act on.
          </p>
        </article>
        <article>
          <h2>See it on a real repository.</h2>
          <p>
            The queue above is CodeSentinel measured against itself: 44 files, 39 commits,
            real churn. <Link to={`/scans/${DEMO_SCAN}`}>Open the full scan</Link>.
          </p>
        </article>
      </section>
    </div>
  );
}
