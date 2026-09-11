import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { FileRisk, RiskQueue } from "../api/types";
import { RiskTable, sortFiles } from "./RiskTable";

function file(path: string, risk: number | null, churn = 1): FileRisk {
  return {
    path,
    is_test: false,
    loc: 10,
    cyclomatic_complexity: risk === null ? null : 5,
    maintainability_index: null,
    churn_score: churn,
    normalized_complexity: risk,
    normalized_churn: risk,
    risk_score: risk,
  };
}

describe("sortFiles", () => {
  it("ranks higher risk first", () => {
    const sorted = sortFiles([file("low", 0.1), file("high", 0.9)], "risk_score");
    expect(sorted.map((f) => f.path)).toEqual(["high", "low"]);
  });

  it("sorts unknown risk last, never first", () => {
    const sorted = sortFiles(
      [file("unknown", null), file("high", 0.9), file("low", 0.1)],
      "risk_score",
    );
    expect(sorted.map((f) => f.path)).toEqual(["high", "low", "unknown"]);
  });

  it("keeps unknown last even when every other file scores zero", () => {
    const sorted = sortFiles([file("unknown", null), file("zero", 0)], "risk_score");
    expect(sorted.map((f) => f.path)).toEqual(["zero", "unknown"]);
  });
});

const queue: RiskQueue = {
  scan_id: "abc",
  status: "partial",
  total_files: 3,
  unmeasured: 1,
  analyzer_statuses: { radon: { status: "partial", error: "no Docker daemon" } },
  files: [file("a.py", 0.5), file("b.py", null)],
};

describe("RiskTable", () => {
  it("states how many files could not be ranked", () => {
    render(<RiskTable queue={queue} />);
    expect(screen.getByText(/1 of 3 files could not be ranked/i)).toBeInTheDocument();
  });

  it("says unknown rather than safe", () => {
    render(<RiskTable queue={queue} />);
    expect(screen.getByText(/unknown rather than safe/i)).toBeInTheDocument();
  });

  it("shows the analyser's reason rather than hiding it", () => {
    render(<RiskTable queue={queue} />);
    expect(screen.getByText(/no Docker daemon/i)).toBeInTheDocument();
  });

  it("falls back to churn ordering when nothing could be ranked, and says so", () => {
    const unranked: RiskQueue = {
      ...queue,
      unmeasured: 2,
      files: [file("small", null, 5), file("big", null, 50)],
    };
    const { container } = render(<RiskTable queue={unranked} />);
    expect(screen.getByText(/ordered by churn alone/i)).toBeInTheDocument();

    const paths = [...container.querySelectorAll(".path")].map((el) => el.textContent);
    expect(paths).toEqual(["big", "small"]);
  });
});
