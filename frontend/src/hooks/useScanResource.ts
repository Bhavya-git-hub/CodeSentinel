import { useEffect, useState } from "react";

/**
 * Loads one scan resource once.
 *
 * Separate from usePolledScan: findings, impact and the report are all derived from a
 * scan that has already finished, so there is nothing to poll for. A shared hook would
 * have to carry polling machinery that these three never use.
 *
 * `error` is surfaced rather than collapsed into an empty result, because an empty list
 * and an unreachable API are different facts and only one of them is about the code.
 */
export function useScanResource<T>(
  load: () => Promise<T>,
  deps: readonly unknown[],
): { data: T | null; error: string | null; loading: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    load()
      .then((value) => {
        if (!cancelled) setData(value);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // `deps` is the caller's dependency array, passed through deliberately: the
    // loader closes over the scan id, and the caller is what knows when it changed.
  }, deps);

  return { data, error, loading };
}
