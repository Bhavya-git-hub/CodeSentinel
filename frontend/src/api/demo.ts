import type { DataSource, FileRisk, RiskQueue, ScanDetail } from "./types";

/**
 * Fixtures carrying real measurements.
 *
 * These are the figures the shipped services actually produced against this repository:
 * 44 files inventoried under backend/app, 39 non-merge commits, churn from the real
 * `churn_score` over the real history. Complexity is null throughout because Radon
 * genuinely could not run without a Docker daemon -- so even the sample data tells the
 * truth about itself, and demo mode demonstrates the unknown state rather than hiding it.
 */

const MEASURED: ReadonlyArray<readonly [string, number, number, number]> = [
  ["backend/app/services/sandbox/runner.py", 433, 433.1, 1.0],
  ["backend/app/services/ingestion/cloner.py", 328, 328.0, 0.757],
  ["backend/app/services/ingestion/history.py", 239, 239.0, 0.552],
  ["backend/app/services/ingestion/pipeline.py", 195, 209.0, 0.483],
  ["backend/app/services/analyzers/analysis.py", 175, 175.0, 0.404],
  ["backend/app/api/v1/scans.py", 165, 171.0, 0.395],
  ["backend/app/services/analyzers/radon.py", 170, 170.0, 0.393],
  ["backend/app/config.py", 151, 158.4, 0.366],
  ["backend/app/models/code.py", 159, 158.3, 0.365],
  ["backend/app/services/ingestion/inventory.py", 152, 152.0, 0.351],
  ["backend/app/models/history.py", 136, 135.5, 0.313],
  ["backend/app/services/scoring/risk.py", 98, 98.0, 0.226],
  ["backend/app/services/mining/churn.py", 84, 84.0, 0.194],
  ["backend/app/services/ingestion/url.py", 78, 78.0, 0.18],
  ["backend/app/models/base.py", 62, 71.0, 0.164],
  ["backend/app/db.py", 61, 64.0, 0.148],
  ["backend/app/services/ingestion/errors.py", 41, 41.0, 0.095],
  ["backend/app/main.py", 88, 38.0, 0.088],
  ["backend/app/models/repository.py", 82, 34.0, 0.079],
  ["backend/app/schemas/scan.py", 72, 31.0, 0.072],
];

const DEMO_SCAN_ID = "3f7c1a90-4d2b-4c11-9d8e-2a6f5b0c7e41";

const files: FileRisk[] = MEASURED.map(([path, loc, churn, normalizedChurn]) => ({
  path,
  is_test: path.includes("/tests/"),
  loc,
  // Radon did not run: unknown, not zero. This is what the UI must render as `None`.
  cyclomatic_complexity: null,
  maintainability_index: null,
  churn_score: churn,
  normalized_complexity: null,
  normalized_churn: normalizedChurn,
  risk_score: null,
}));

const scan: ScanDetail = {
  scan_id: DEMO_SCAN_ID,
  status: "partial",
  commit_sha: "3c5ad571f0e2b8a94c6d1e7f2a8b5c3d9e0f4a16",
  error: null,
  file_count: 44,
  commit_count: 39,
  started_at: "2026-09-11T10:03:13Z",
  completed_at: "2026-09-11T10:03:58Z",
};

const queue: RiskQueue = {
  scan_id: DEMO_SCAN_ID,
  status: "partial",
  total_files: 44,
  unmeasured: 44,
  analyzer_statuses: {
    radon: {
      status: "partial",
      error: "Radon could not run in the sandbox: no Docker daemon is reachable.",
    },
  },
  files,
};

export const DEMO_SCAN = DEMO_SCAN_ID;

/** The rows the landing hero renders, with the repository prefix trimmed for width. */
export const HERO_ROWS = files.slice(0, 6).map((file) => ({
  path: file.path.replace("backend/app/", ""),
  churn: file.churn_score,
  weight: file.normalized_churn,
}));

export const demoSource: DataSource = {
  submitScan: () => Promise.resolve({ scan_id: DEMO_SCAN_ID, status: "pending" as const }),
  getScan: () => Promise.resolve(scan),
  getMetrics: () => Promise.resolve(queue),
  listScans: () => Promise.resolve([scan]),
};
