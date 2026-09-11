import { activeKey } from "./credentials";
import type {
  BlastRadius,
  DataSource,
  FindingsPage,
  RiskQueue,
  ScanAccepted,
  ScanDetail,
  ScanList,
  ScanReport,
} from "./types";

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
    const key = activeKey();
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(key ? { "X-API-Key": key } : {}),
        ...init?.headers,
      },
    });
  } catch {
    // The network never reached the API. Kept distinct from an API that answered,
    // because "the server is down" and "the server refused this" need different
    // actions from the reader.
    throw new ApiError(0, `Could not reach the API at ${BASE || "this origin"}.`);
  }

  if (response.status === 401) {
    // Distinguished from a generic failure: the fix is a credential, not a retry. The
    // instruction points at the panel rather than at the console, because a console
    // incantation is a fix only the person who wrote it can perform.
    throw new ApiError(
      401,
      "This API requires a key. Add one under Settings, then try again.",
    );
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
  getFindings: (id) => request<FindingsPage>(`/api/v1/scans/${id}/findings`),
  getImpact: (id, path, depth = 3) =>
    request<BlastRadius>(
      `/api/v1/scans/${id}/impact?path=${encodeURIComponent(path)}&depth=${depth}`,
    ),
  getReport: (id) => request<ScanReport>(`/api/v1/scans/${id}/report`),
  listScans: (limit = 20, offset = 0) =>
    request<ScanList>(`/api/v1/scans?limit=${limit}&offset=${offset}`),
};
