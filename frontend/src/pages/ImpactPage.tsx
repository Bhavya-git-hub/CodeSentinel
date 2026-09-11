import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { source } from "../api/source";
import type { BlastRadius } from "../api/types";
import { Impact } from "../components/Impact";
import { ScanTabs } from "./ScanTabs";
import "./Pages.css";

export function ImpactPage() {
  const { id } = useParams<{ id: string }>();
  const [params, setParams] = useSearchParams();
  const [radius, setRadius] = useState<BlastRadius | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function query(path: string) {
    if (!id) return;
    setBusy(true);
    setError(null);
    // The path lives in the URL so a traced impact can be linked to and reloaded.
    setParams({ path });
    try {
      setRadius(await source.getImpact(id, path));
    } catch (cause) {
      setRadius(null);
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  const initial = params.get("path");
  if (initial && radius === null && !busy && !error) {
    void query(initial);
  }

  return (
    <div className="page">
      {id ? <ScanTabs id={id} /> : null}
      {error ? <p className="error">{error}</p> : null}
      <Impact radius={radius} onQuery={query} busy={busy} />
    </div>
  );
}
