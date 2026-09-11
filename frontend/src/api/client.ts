import type { DataSource, RiskQueue, ScanAccepted, ScanDetail } from "./types";

const BASE = import.meta.env.VITE_CODESENTINEL_API_BASE ?? "";

/**
 * A failed request, carrying the reason the API gave.
 *
 * The backend phrases its refusals for a person -- "The transport 'ext' is not
 * permitted. Allowed transports: https." -- so the detail is preserved verbatim and
 * shown. Paraphrasing it into "Invalid URL" would throw away the only part that tells
 * someone what to do next.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

async function readDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        return detail
          .map((item) =>
            item && typeof item === "object" && "msg" in item
              ? String((item as { msg: unknown }).msg)
              : String(item),
          )
          .join("; ");
      }
    }
  } catch {
    // Body was not JSON. The status line below is all we honestly have.
  }
  return `The API returned ${response.status} with no explanation.`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    // The network never reached the API. Kept distinct from an API that answered,
    // because "the server is down" and "the server refused this" need different
    // actions from the reader.
    throw new ApiError(0, `Could not reach the API at ${BASE || "this origin"}.`);
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readDetail(response));
  }
  return (await response.json()) as T;
}

export const liveSource: DataSource = {
  submitScan: (url) =>
    request<ScanAccepted>("/api/v1/scans", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  getScan: (id) => request<ScanDetail>(`/api/v1/scans/${id}`),
  getMetrics: (id) => request<RiskQueue>(`/api/v1/scans/${id}/metrics`),
  // The API has no list endpoint yet. Returning an empty list rather than inventing
  // one keeps the dashboard honest about what it actually knows.
  listScans: () => Promise.resolve([]),
};
