import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import type { BlastRadius } from "../api/types";
import { Metric } from "./Value";
import "./Findings.css";

/**
 * What breaks if one file changes.
 *
 * The unresolved-edge count is rendered as part of the answer rather than as a
 * diagnostic, because it changes what the answer means: third-party imports, dynamic
 * imports and relative imports above the repository root cannot be followed, so the list
 * is a floor. A reviewer shown only the resolved reach would read a floor as a ceiling
 * and conclude a change is safely contained when it may not be (C4).
 */
export function Impact({
  radius,
  onQuery,
  busy,
}: {
  radius: BlastRadius | null;
  onQuery: (path: string) => void;
  busy: boolean;
}) {
  const [path, setPath] = useState(radius?.path ?? "");

  // The field is initialised before the first result arrives, so a page opened from a
  // shared ?path= link would render results above an empty, disabled form -- no way to
  // see what was traced or to re-run it. Sync once the radius lands.
  useEffect(() => {
    if (radius?.path) setPath(radius.path);
  }, [radius?.path]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (path.trim()) onQuery(path.trim());
  }

  return (
    <section className="impact">
      <header className="impact__head">
        <h2>Change impact</h2>
        <p className="muted">
          Which files transitively import the one you name. The traversal runs against the
          direction of the import, because the question is what breaks if this changes.
        </p>
        <form className="impact__form" onSubmit={submit}>
          <label className="visually-hidden" htmlFor="impact-path">
            File path
          </label>
          <input
            id="impact-path"
            name="impact-path"
            type="text"
            value={path}
            onChange={(event) => setPath(event.target.value)}
            placeholder="backend/app/services/sandbox/runner.py"
            autoComplete="off"
            spellCheck={false}
          />
          <button type="submit" disabled={busy || !path.trim()}>
            {busy ? "Tracing…" : "Trace impact"}
          </button>
        </form>
      </header>

      {radius === null ? (
        <p className="muted">Name a file to see what depends on it.</p>
      ) : (
        <>
          <p className="impact__caveat">
            <span>
              {radius.impacted.length} file{radius.impacted.length === 1 ? "" : "s"} within{" "}
              {radius.depth} import hops
              {radius.unresolved_edges > 0
                ? ` — and ${radius.unresolved_edges} edges could not be followed, so this is a floor, not a ceiling.`
                : "."}
            </span>
          </p>

          {radius.impacted.length === 0 ? (
            <p className="muted">
              Nothing in this repository imports it, as far as the graph could resolve.
            </p>
          ) : (
            <div className="impact__rows">
              {radius.impacted.map((file) => (
                <div className="impact__row" key={file.path}>
                  <span className="path">{file.path}</span>
                  <span className="impact__hops">
                    {file.distance} hop{file.distance === 1 ? "" : "s"}
                  </span>
                  <Metric value={file.risk_score} digits={3} />
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
