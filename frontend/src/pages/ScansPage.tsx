import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { source } from "../api/source";
import type { ScanAccepted } from "../api/types";
import "./Pages.css";

/**
 * The URL field submits to the API without pre-validating the transport.
 *
 * The backend already refuses a hostile URL at its boundary and phrases the refusal for
 * a person -- "The transport 'ext' is not permitted. Allowed transports: https." A second
 * copy of that rule in the browser would be a second thing to keep in step, and the
 * browser's copy is the one an attacker skips anyway. So the refusal is shown verbatim
 * rather than pre-empted or paraphrased.
 */
export function SubmitForm({
  onSubmit,
}: {
  onSubmit: (url: string) => Promise<ScanAccepted>;
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function handle(event: FormEvent) {
    event.preventDefault();
    if (!url.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const accepted = await onSubmit(url.trim());
      navigate(`/scans/${accepted.scan_id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="submit" onSubmit={handle}>
      <label htmlFor="repo-url">Repository URL</label>
      <div className="submit__row">
        <input
          id="repo-url"
          name="repo-url"
          type="text"
          placeholder="https://github.com/psf/requests"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
        <button type="submit" disabled={busy}>
          {busy ? "Starting…" : "Start scan"}
        </button>
      </div>
      {error ? <p className="error">{error}</p> : null}
    </form>
  );
}

export function ScansPage() {
  return (
    <div className="page">
      <header className="page__head">
        <h1>Scan a repository</h1>
        <p className="muted">
          Public repositories over https. The clone is size- and time-bounded, runs under a
          hardened git with hooks and submodules disabled, and is deleted when the scan
          ends.
        </p>
      </header>
      <SubmitForm onSubmit={(url) => source.submitScan(url)} />
    </div>
  );
}
