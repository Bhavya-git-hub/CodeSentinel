import { useParams } from "react-router-dom";

import { source } from "../api/source";
import type { ScanReport } from "../api/types";
import { Report } from "../components/Report";
import { useScanResource } from "../hooks/useScanResource";
import { ScanTabs } from "./ScanTabs";
import "./Pages.css";

export function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, loading } = useScanResource<ScanReport>(
    () => source.getReport(id ?? ""),
    [id],
  );

  return (
    <div className="page">
      {id ? <ScanTabs id={id} /> : null}
      {error ? (
        <>
          <h1>The report could not be loaded</h1>
          <p className="error">{error}</p>
        </>
      ) : loading || !data ? (
        <p className="muted">Assembling report&hellip;</p>
      ) : (
        <Report report={data} />
      )}
    </div>
  );
}
