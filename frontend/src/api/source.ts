import { liveSource } from "./client";
import { demoSource } from "./demo";
import type { DataSource } from "./types";

/**
 * Chooses the data source. It does not arbitrate between them at runtime.
 *
 * There is deliberately no try/catch around the live client that returns fixtures on
 * failure. That fallback is the obvious convenience and it is the one thing this file
 * exists to prevent: a UI that invents data when the backend is unreachable produces a
 * confident report about a repository nobody analysed, which is the exact failure the
 * backend spends five phases avoiding.
 *
 * Demo mode is configuration, like the backend's clone_allowed_protocols -- explicit,
 * announced in the interface, and impossible to reach by accident (anti-pattern #1).
 * The comparison is against "1" exactly, so an unset, empty or mistyped value selects
 * the live API rather than silently serving samples.
 */
export function selectSource(
  env: { demo?: string | undefined },
  demo: DataSource,
  live: DataSource,
): DataSource {
  return env.demo === "1" ? demo : live;
}

export const IS_DEMO = import.meta.env.VITE_CODESENTINEL_DEMO === "1";

export const source: DataSource = selectSource(
  { demo: import.meta.env.VITE_CODESENTINEL_DEMO },
  demoSource,
  liveSource,
);
