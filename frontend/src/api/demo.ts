import type {
  BlastRadius,
  DataSource,
  FileRisk,
  FindingsPage,
  RiskQueue,
  ScanDetail,
  ScanReport,
} from "./types";

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

const findings: FindingsPage = {
  scan_id: DEMO_SCAN_ID,
  status: "partial",
  total: 5,
  by_severity: { critical: 1, major: 2, minor: 1, info: 1 },
  analyzer_statuses: {
    radon: {
      status: "partial",
      error: "Radon could not run in the sandbox: no Docker daemon is reachable.",
    },
  },
  findings: [
    {
      analyzer: "bandit",
      rule_id: "B602",
      severity: "critical",
      message: "subprocess call with shell=True identified, security issue [confidence: high]",
      path: "backend/app/services/ingestion/cloner.py",
      line_start: 154,
      line_end: null,
    },
    {
      analyzer: "pylint",
      rule_id: "E1101",
      severity: "major",
      message: "Instance of 'Popen' has no 'stdout' member",
      path: "backend/app/services/ingestion/cloner.py",
      line_start: 210,
      line_end: null,
    },
    {
      analyzer: "pylint",
      rule_id: "W0718",
      severity: "major",
      message: "Catching too general exception Exception",
      path: "backend/app/services/ingestion/pipeline.py",
      line_start: 168,
      line_end: null,
    },
    {
      analyzer: "pylint",
      rule_id: "W0612",
      severity: "minor",
      message: "Unused variable 'maintainability'",
      path: "backend/app/services/analyzers/analysis.py",
      line_start: 116,
      line_end: null,
    },
    {
      // A finding the analyser could not attribute to a file in the inventory. Kept
      // rather than dropped, so the count is honest (C4).
      analyzer: "bandit",
      rule_id: "B101",
      severity: "info",
      message: "Use of assert detected [confidence: low]",
      path: null,
      line_start: null,
      line_end: null,
    },
  ],
};

const impact: BlastRadius = {
  scan_id: DEMO_SCAN_ID,
  path: "backend/app/services/sandbox/runner.py",
  depth: 3,
  impacted: [
    { path: "backend/app/services/analyzers/radon.py", distance: 1, risk_score: null },
    { path: "backend/app/services/analyzers/analysis.py", distance: 1, risk_score: null },
    { path: "backend/app/services/ingestion/pipeline.py", distance: 2, risk_score: null },
    { path: "backend/app/workers/tasks.py", distance: 3, risk_score: null },
  ],
  resolved_edges: 61,
  unresolved_edges: 48,
};

const report: ScanReport = {
  scan_id: DEMO_SCAN_ID,
  status: "partial",
  commit_sha: "3c5ad571f0e2b8a94c6d1e7f2a8b5c3d9e0f4a16",
  started_at: "2026-09-11T10:03:13Z",
  completed_at: "2026-09-11T10:03:58Z",
  file_count: 44,
  commit_count: 39,
  files_ranked: 0,
  files_unmeasured: 44,
  findings_total: 5,
  findings_by_severity: { critical: 1, major: 2, minor: 1, info: 1 },
  dependency_edges: 109,
  dependency_edges_unresolved: 48,
  coverage_measured_files: 0,
  top_risks: files.slice(0, 8),
  commits_labelled: 0,
  commits_defect_inducing: 0,
  top_defect_risks: [],
  limitations: [
    {
      subject: "Unranked files",
      detail: "44 of 44 files have no risk score.",
      consequence:
        "They are unknown, not safe. They sort last in the queue, so a file that could " +
        "not be parsed will not appear near the top even if it is the worst in the " +
        "repository.",
    },
    {
      subject: "Unresolved imports",
      detail: "48 import edges could not be resolved to a file.",
      consequence:
        "Third-party imports, dynamic imports and relative imports above the repository " +
        "root cannot be followed, so every blast radius here is a floor rather than a " +
        "ceiling.",
    },
    {
      subject: "Coverage",
      detail: "No file has coverage data.",
      consequence:
        "The sandbox has no network, so a target whose tests need third-party packages " +
        "cannot run them. No file here is known to be untested; they are unmeasured, " +
        "which is a different thing.",
    },
    {
      subject: "Defect prediction",
      detail: "No commit carries a modelled defect probability.",
      consequence:
        "SZZ labels only the commits it can reach, and a probability computed over a " +
        "handful of them is noise. An empty list here means the model declined, not " +
        "that no commit is risky.",
    },
  ],
  config: {
    churn_half_life_days: 90,
    max_repo_size_mb: 1024,
    clone_allowed_protocols: ["https"],
    analysis_enabled: true,
  },
  analyzer_statuses: queue.analyzer_statuses,
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
  getFindings: () => Promise.resolve(findings),
  getImpact: (_id, path) => Promise.resolve({ ...impact, path }),
  getReport: () => Promise.resolve(report),
  listScans: () => Promise.resolve([scan]),
};
