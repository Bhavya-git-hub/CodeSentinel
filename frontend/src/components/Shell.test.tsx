import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { DemoBanner } from "./Shell";

describe("DemoBanner", () => {
  it("announces demo mode when fixtures are the source", () => {
    render(
      <MemoryRouter>
        <DemoBanner isDemo={true} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("status")).toHaveTextContent(/sample data/i);
  });

  it("renders nothing when the live API is the source", () => {
    const { container } = render(
      <MemoryRouter>
        <DemoBanner isDemo={false} />
      </MemoryRouter>,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
