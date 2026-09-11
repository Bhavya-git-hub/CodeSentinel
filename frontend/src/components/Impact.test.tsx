import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BlastRadius } from "../api/types";
import { Impact } from "./Impact";

const radius: BlastRadius = {
  scan_id: "abc",
  path: "pkg/core.py",
  depth: 3,
  impacted: [{ path: "pkg/user.py", distance: 1, risk_score: 0.42 }],
  resolved_edges: 10,
  unresolved_edges: 7,
};

describe("Impact", () => {
  it("says the radius is a floor when edges could not be followed", () => {
    render(<Impact radius={radius} onQuery={vi.fn()} busy={false} />);
    expect(screen.getByText(/floor, not a ceiling/i)).toBeInTheDocument();
  });

  it("omits the caveat when every edge resolved", () => {
    render(
      <Impact radius={{ ...radius, unresolved_edges: 0 }} onQuery={vi.fn()} busy={false} />,
    );
    expect(screen.queryByText(/floor, not a ceiling/i)).not.toBeInTheDocument();
  });

  it("distinguishes no importers from an unqueried state", () => {
    render(<Impact radius={{ ...radius, impacted: [] }} onQuery={vi.fn()} busy={false} />);
    expect(screen.getByText(/as far as the graph could resolve/i)).toBeInTheDocument();
  });
});
