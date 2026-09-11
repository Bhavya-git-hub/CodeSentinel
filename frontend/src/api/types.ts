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
  listScans(): Promise<ScanDetail[]>;
}
