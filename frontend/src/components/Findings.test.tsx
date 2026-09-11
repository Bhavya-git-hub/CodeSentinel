import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { FindingItem, FindingsPage } from "../api/types";
import { Findings, sortFindings } from "./Findings";

function finding(over: Partial<FindingItem> = {}): FindingItem {
  return {
    analyzer: "pylint",
    rule_id: "W0612",
    severity: "minor",
    message: "Unused variable",
    path: "pkg/a.py",
    line_start: 4,
    line_end: null,
    ...over,
  };
}

describe("sortFindings", () => {
  it("puts the worst first", () => {
    const sorted = sortFindings([
      finding({ rule_id: "I", severity: "info" }),
      finding({ rule_id: "C", severity: "critical" }),
      finding({ rule_id: "M", severity: "major" }),
    ]);
    expect(sorted.map((f) => f.severity)).toEqual(["critical", "major", "info"]);
  });

  it("is stable within a severity so the list does not shuffle", () => {
    const a = sortFindings([finding({ rule_id: "B" }), finding({ rule_id: "A" })]);
    const b = sortFindings([finding({ rule_id: "A" }), finding({ rule_id: "B" })]);
    expect(a.map((f) => f.rule_id)).toEqual(b.map((f) => f.rule_id));
  });
});

function page(over: Partial<FindingsPage> = {}): FindingsPage {
  return {
    scan_id: "abc",
    status: "succeeded",
    total: 1,
    by_severity: { minor: 1 },
    analyzer_statuses: {},
    findings: [finding()],
    ...over,
  };
}

describe("Findings", () => {
  it("keeps a finding it could not attribute to a file", () => {
    render(<Findings page={page({ findings: [finding({ path: null, line_start: null })] })} />);
    expect(screen.getByText(/not attributed to a file/i)).toBeInTheDocument();
  });

  it("says counts are for the whole scan, not the page", () => {
    render(<Findings page={page({ total: 940 })} />);
    expect(screen.getByText(/whole scan/i)).toBeInTheDocument();
  });

  it("refuses to call an empty result clean when an analyser fell short", () => {
    render(
      <Findings
        page={page({
          total: 0,
          findings: [],
          analyzer_statuses: { bandit: { status: "partial", error: "no daemon" } },
        })}
      />,
    );
    expect(screen.getByText(/not a clean result/i)).toBeInTheDocument();
  });

  it("calls an empty result clean when every analyser ran", () => {
    render(<Findings page={page({ total: 0, findings: [] })} />);
    expect(screen.getByText(/reported nothing/i)).toBeInTheDocument();
  });
});
