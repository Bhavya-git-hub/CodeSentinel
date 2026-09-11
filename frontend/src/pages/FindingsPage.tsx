import { useParams } from "react-router-dom";

import { source } from "../api/source";
import type { FindingsPage as FindingsPayload } from "../api/types";
import { Findings } from "../components/Findings";
import { useScanResource } from "../hooks/useScanResource";
import { ScanTabs } from "./ScanTabs";
import "./Pages.css";

export function FindingsPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, loading } = useScanResource<FindingsPayload>(
    () => source.getFindings(id ?? ""),
    [id],
  );

  return (
    <div className="page">
      {id ? <ScanTabs id={id} /> : null}
      {error ? (
        <>
          <h1>Findings could not be loaded</h1>
          <p className="error">{error}</p>
        </>
      ) : loading || !data ? (
        <p className="muted">Loading findings&hellip;</p>
      ) : (
        <Findings page={data} />
      )}
    </div>
  );
}
