/**
 * The API contract, as settled by phases 3 and 4 and proved by CI run 34587978470.
 *
 * Every `| null` here is deliberate and load-bearing. The backend distinguishes a value
 * it measured, a value that is genuinely zero, and a value it could not determine; the
 * types carry that distinction so a component cannot quietly collapse it.
 */

export type ScanStatus = "pending" | "running" | "succeeded" | "partial" | "failed";

export const TERMINAL_STATUSES: readonly ScanStatus[] = ["succeeded", "partial", "failed"];

export interface ScanAccepted {
  scan_id: string;
  status: ScanStatus;
}

export interface ScanDetail {
  scan_id: string;
  status: ScanStatus;
  /** Null until the clone resolves the ref. */
  commit_sha: string | null;
  /** Populated for a failed scan, phrased for a person to act on. */
  error: string | null;
  file_count: number;
  commit_count: number;
  started_at: string;
  completed_at: string | null;
}

export interface FileRisk {
  path: string;
  is_test: boolean;
  /** Null means the lines could not be counted, not that the file is empty. */
  loc: number | null;
  cyclomatic_complexity: number | null;
  maintainability_index: number | null;
  /** 0 means it never changed in the mined history. Null means every change was binary. */
  churn_score: number | null;
  normalized_complexity: number | null;
  normalized_churn: number | null;
  /** Null when either component is unknown. Never zero in that case. */
  risk_score: number | null;
}

export interface AnalyzerStatus {
  status?: string;
  error?: string;
}

export interface RiskQueue {
  scan_id: string;
  status: ScanStatus;
  total_files: number;
  /** How many files carry no risk score. Part of the contract, not a footnote. */
  unmeasured: number;
  analyzer_statuses: Record<string, AnalyzerStatus>;
  files: FileRisk[];
}

export interface DataSource {
  submitScan(url: string): Promise<ScanAccepted>;
  getScan(id: string): Promise<ScanDetail>;
  getMetrics(id: string): Promise<RiskQueue>;
  getFindings(id: string): Promise<FindingsPage>;
  getImpact(id: string, path: string, depth?: number): Promise<BlastRadius>;
  getReport(id: string): Promise<ScanReport>;
  listScans(): Promise<ScanDetail[]>;
}

export type Severity = "critical" | "major" | "minor" | "info";

/** Worst first. Used for ordering and for the intensity ramp in the UI. */
export const SEVERITY_ORDER: readonly Severity[] = ["critical", "major", "minor", "info"];

export interface FindingItem {
  analyzer: string;
  rule_id: string;
  severity: Severity;
  message: string;
  /** Null when the analyser could not attribute it to a file in the inventory. */
  path: string | null;
  line_start: number | null;
  line_end: number | null;
}

export interface FindingsPage {
  scan_id: string;
  status: ScanStatus;
  total: number;
  by_severity: Partial<Record<Severity, number>>;
  analyzer_statuses: Record<string, AnalyzerStatus>;
  findings: FindingItem[];
}

export interface ImpactedFile {
  path: string;
  /** Import hops away. 1 means it imports the changed file directly. */
  distance: number;
  risk_score: number | null;
}

export interface BlastRadius {
  scan_id: string;
  path: string;
  depth: number;
  impacted: ImpactedFile[];
  resolved_edges: number;
  /** Edges the graph could not follow. The radius is a floor, not a ceiling. */
  unresolved_edges: number;
}

export interface CommitRisk {
  commit_sha: string;
  defect_probability: number;
  model_version: string;
}

export interface Limitation {
  subject: string;
  detail: string;
  consequence: string;
}

export interface ScanReport {
  scan_id: string;
  status: ScanStatus;
  commit_sha: string | null;
  started_at: string;
  completed_at: string | null;
  file_count: number;
  commit_count: number;
  files_ranked: number;
  files_unmeasured: number;
  findings_total: number;
  findings_by_severity: Partial<Record<Severity, number>>;
  dependency_edges: number;
  dependency_edges_unresolved: number;
  coverage_measured_files: number;
  top_risks: FileRisk[];
  commits_labelled: number;
  commits_defect_inducing: number;
  top_defect_risks: CommitRisk[];
  limitations: Limitation[];
  config: Record<string, unknown>;
  analyzer_statuses: Record<string, AnalyzerStatus>;
}

