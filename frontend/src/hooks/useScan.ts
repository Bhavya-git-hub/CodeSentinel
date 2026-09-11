import { useEffect, useState } from "react";

import { source } from "../api/source";
import { TERMINAL_STATUSES } from "../api/types";
import type { RiskQueue, ScanDetail } from "../api/types";

const POLL_MS = 2000;

/**
 * Follows one scan until it reaches a terminal status.
 *
 * Analysis is asynchronous by constraint C2, so the browser polls rather than holding a
 * request open. Polling stops at a terminal status: an interval that keeps running after
 * a scan has finished is a request every two seconds, forever, for a row that cannot
 * change again.
 */
export function usePolledScan(id: string | undefined) {
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [queue, setQueue] = useState<RiskQueue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    let timer: number | undefined;

    async function tick(scanId: string) {
      try {
        const detail = await source.getScan(scanId);
        if (cancelled) return;
        setScan(detail);

        if (TERMINAL_STATUSES.includes(detail.status)) {
          const metrics = await source.getMetrics(scanId);
          if (cancelled) return;
          setQueue(metrics);
        } else {
          timer = window.setTimeout(() => void tick(scanId), POLL_MS);
        }
      } catch (cause) {
        if (cancelled) return;
        // Surfaced, never swallowed into an empty table: an empty queue and an
        // unreachable API must not look the same to a reader.
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void tick(id);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [id]);

  return { scan, queue, error, loading };
}
