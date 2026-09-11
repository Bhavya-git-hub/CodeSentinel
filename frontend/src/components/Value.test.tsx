import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Bar, Metric, StatusPill } from "./Value";

describe("Metric", () => {
  it("renders a measured value", () => {
    render(<Metric value={433.1} digits={1} />);
    expect(screen.getByText("433.1")).toBeInTheDocument();
  });

  it("renders a genuine zero as zero", () => {
    render(<Metric value={0} digits={1} />);
    expect(screen.getByText("0.0")).toBeInTheDocument();
  });

  it("renders an unknown value as None, never as zero", () => {
    render(<Metric value={null} />);
    expect(screen.getByText("None")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("explains an unknown value on hover and to assistive technology", () => {
    render(<Metric value={null} />);
    expect(screen.getByText("None")).toHaveAttribute("title", "Could not be determined");
  });

  it("distinguishes a zero from an unknown in the DOM", () => {
    const zero = render(<Metric value={0} />);
    expect(zero.container.querySelector(".value--unknown")).toBeNull();

    const unknown = render(<Metric value={null} />);
    expect(unknown.container.querySelector(".value--unknown")).not.toBeNull();
  });
});

describe("Bar", () => {
  it("draws hatch and no fill for an unknown magnitude", () => {
    const { container } = render(<Bar value={null} />);
    expect(container.querySelector(".bar__fill")).toBeNull();
    expect(container.querySelector(".hatch")).not.toBeNull();
  });

  it("draws a fill proportional to a measured magnitude", () => {
    const { container } = render(<Bar value={0.5} />);
    expect(container.querySelector<HTMLElement>(".bar__fill")?.style.width).toBe("50%");
  });

  it("draws a measured zero as an empty track, not as hatch", () => {
    const { container } = render(<Bar value={0} />);
    expect(container.querySelector(".hatch")).toBeNull();
    expect(container.querySelector<HTMLElement>(".bar__fill")?.style.width).toBe("0%");
  });
});

describe("StatusPill", () => {
  it("gives partial its own state rather than calling it a success", () => {
    const { container } = render(<StatusPill status="partial" />);
    expect(screen.getByText("Partial")).toBeInTheDocument();
    expect(container.querySelector(".pill--succeeded")).toBeNull();
  });
});
