import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { ScanList, ScanSummary } from "../api/types";
import { ScanHistory, durationSeconds } from "./ScanHistory";

function summary(overrides: Partial<ScanSummary> = {}): ScanSummary {
  return {
    scan_id: "11111111-1111-1111-1111-111111111111",
    repository_url: "https://github.com/psf/requests",
    repository_name: "psf/requests",
    status: "succeeded",
    commit_sha: "abcdef1234567890",
    error: null,
    started_at: "2026-06-01T10:00:00Z",
    completed_at: "2026-06-01T10:00:30Z",
    ...overrides,
  };
}

function page(overrides: Partial<ScanList> = {}): ScanList {
  return { total: 1, limit: 20, offset: 0, scans: [summary()], ...overrides };
}

function draw(list: ScanList) {
  return render(
    <MemoryRouter>
      <ScanHistory page={list} />
    </MemoryRouter>,
  );
}

describe("ScanHistory", () => {
  it("states the total rather than the length of the page", () => {
    // The two diverge the moment a history outgrows one page, and a reader who takes
    // the visible count as the whole history concludes this instance has barely run.
    draw(page({ total: 96, scans: [summary(), summary({ scan_id: "b" })] }));

    expect(screen.getByText(/Showing 2 of 96 scans/)).toBeInTheDocument();
  });

  it("says an empty history is empty, not that nothing was found", () => {
    draw(page({ total: 0, scans: [] }));

    expect(screen.getByText(/has not analysed anything/)).toBeInTheDocument();
  });

  it("renders an unresolved commit as None, never as a blank cell", () => {
    // commit_sha is null until the clone resolves the ref. A blank cell reads as
    // "no commit", which is a claim about the repository rather than about the scan.
    draw(page({ scans: [summary({ commit_sha: null, status: "pending" })] }));

    expect(screen.getByText("None")).toBeInTheDocument();
  });

  it("renders the duration of an unfinished scan as None, not as zero", () => {
    draw(page({ scans: [summary({ status: "running", completed_at: null })] }));

    expect(screen.queryByText("0s")).not.toBeInTheDocument();
    expect(screen.getAllByText("None").length).toBeGreaterThan(0);
  });

  it("shows a failed scan's reason in the list itself", () => {
    // The list is where someone goes to find out what went wrong. Making them open each
    // row to discover which failed and why hides it behind a click.
    draw(
      page({
        scans: [
          summary({
            status: "failed",
            error: "The transport 'ext' is not permitted. Allowed transports: https.",
          }),
        ],
      }),
    );

    expect(screen.getByText(/Allowed transports: https/)).toBeInTheDocument();
  });

  it("links each row to its scan", () => {
    draw(page());

    expect(screen.getByRole("link", { name: "psf/requests" })).toHaveAttribute(
      "href",
      "/scans/11111111-1111-1111-1111-111111111111",
    );
  });

  it("distinguishes partial from succeeded", () => {
    // PARTIAL means usable work plus a stated gap. Showing it as success hides the gap.
    draw(page({ scans: [summary({ status: "partial" })] }));

    expect(screen.getByText("Partial")).toBeInTheDocument();
  });
});

describe("durationSeconds", () => {
  it("is null while a scan is still running", () => {
    expect(durationSeconds("2026-06-01T10:00:00Z", null)).toBeNull();
  });

  it("measures a completed scan", () => {
    expect(durationSeconds("2026-06-01T10:00:00Z", "2026-06-01T10:00:30Z")).toBe(30);
  });

  it("is null rather than NaN when a timestamp is unparseable", () => {
    // NaN formats as "NaNs", which reads as a broken page rather than as unknown data.
    expect(durationSeconds("not a date", "2026-06-01T10:00:30Z")).toBeNull();
  });
});
