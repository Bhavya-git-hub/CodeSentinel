import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ScanReport } from "../api/types";
import { Report } from "./Report";

function report(over: Partial<ScanReport> = {}): ScanReport {
  return {
    scan_id: "abc",
    status: "partial",
    commit_sha: "a".repeat(40),
    started_at: "2026-09-11T10:00:00Z",
    completed_at: "2026-09-11T10:01:00Z",
    file_count: 44,
    commit_count: 39,
    files_ranked: 0,
    files_unmeasured: 44,
    findings_total: 0,
    findings_by_severity: {},
    dependency_edges: 100,
    dependency_edges_unresolved: 40,
    coverage_measured_files: 0,
    top_risks: [],
    commits_labelled: 0,
    commits_defect_inducing: 0,
    top_defect_risks: [],
    limitations: [
      {
        subject: "Coverage",
        detail: "No file has coverage data.",
        consequence: "They are unmeasured, which is a different thing from untested.",
      },
    ],
    config: { churn_half_life_days: 90 },
    analyzer_statuses: {},
    ...over,
  };
}

describe("Report", () => {
  it("shows a zero that means 'nothing measured' as none, not as 0", () => {
    render(<Report report={report()} />);
    // files_ranked and coverage are absences here, and a row of zeroes reads as
    // reassurance to someone skimming.
    expect(screen.getAllByText("none").length).toBeGreaterThan(0);
  });

  it("shows a real count as a number", () => {
    render(<Report report={report({ dependency_edges: 100 })} />);
    expect(screen.getByText("100")).toBeInTheDocument();
  });

  it("renders limitations as content", () => {
    render(<Report report={report()} />);
    expect(screen.getByText(/what this scan could not determine/i)).toBeInTheDocument();
    expect(screen.getByText(/different thing from untested/i)).toBeInTheDocument();
  });
});
