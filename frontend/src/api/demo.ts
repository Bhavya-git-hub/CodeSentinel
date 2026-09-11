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

import realScan from "./real-scan.json";

/**
 * The payload is a real scan, produced by running the shipped services against
 * encode/starlette: 150 files, 1,665 commits, 1,311 import edges, 138 bug-fix commits.
 *
 * Complexity and coverage are null throughout because Radon and the test suite need a
 * Docker daemon, and the machine that produced this had none. That absence is kept rather
 * than filled in -- it is the state the interface exists to render honestly, and a demo
 * that quietly showed complexity numbers nobody measured would be the exact failure this
 * product is built to prevent.
 */
const scan: ScanDetail = realScan.scan as ScanDetail;
const queue: RiskQueue = realScan.queue as RiskQueue;
const impact: BlastRadius = realScan.impact as BlastRadius;
const report: ScanReport = realScan.report as ScanReport;
const files: FileRisk[] = queue.files;

const DEMO_SCAN_ID = scan.scan_id;


/**
 * The one part of this payload that is not measured.
 *
 * Pylint and Bandit run in the sandbox, so no real finding set could be produced without
 * a Docker daemon. These are illustrative, the shape is the API's own, and the banner
 * says the whole page is sample data.
 */
const findings: FindingsPage = {
  scan_id: DEMO_SCAN_ID,
  status: "partial",
  total: 5,
  by_severity: { critical: 1, major: 2, minor: 1, info: 1 },
  analyzer_statuses: queue.analyzer_statuses,
  findings: [
    {
      analyzer: "bandit",
      rule_id: "B602",
      severity: "critical",
      message: "subprocess call with shell=True identified, security issue [confidence: high]",
      path: "starlette/_utils.py",
      line_start: 54,
      line_end: null,
    },
    {
      analyzer: "pylint",
      rule_id: "E1101",
      severity: "major",
      message: "Instance of 'Request' has no 'scope' member",
      path: "starlette/requests.py",
      line_start: 128,
      line_end: null,
    },
    {
      analyzer: "pylint",
      rule_id: "W0718",
      severity: "major",
      message: "Catching too general exception Exception",
      path: "starlette/middleware/errors.py",
      line_start: 171,
      line_end: null,
    },
    {
      analyzer: "pylint",
      rule_id: "W0612",
      severity: "minor",
      message: "Unused variable 'exc_type'",
      path: "starlette/exceptions.py",
      line_start: 44,
      line_end: null,
    },
    {
      // Kept rather than dropped: the analyser could not attribute it to a file in the
      // inventory, and omitting it would shrink the count (C4).
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

export const DEMO_SCAN = DEMO_SCAN_ID;

/** The rows the landing hero renders, with the repository prefix trimmed for width. */
export const HERO_ROWS = files.slice(0, 6).map((file) => ({
  path: file.path,
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
  listScans: () =>
    Promise.resolve({
      total: 1,
      limit: 20,
      offset: 0,
      scans: [
        {
          scan_id: DEMO_SCAN_ID,
          repository_url: "https://github.com/encode/starlette",
          repository_name: "encode/starlette",
          status: scan.status,
          commit_sha: scan.commit_sha,
          error: scan.error,
          started_at: scan.started_at,
          completed_at: scan.completed_at,
        },
      ],
    }),
};
