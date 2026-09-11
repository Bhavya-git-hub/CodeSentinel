import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { SubmitForm } from "./ScansPage";

describe("SubmitForm", () => {
  it("shows the API's own refusal verbatim", async () => {
    const submit = vi
      .fn()
      .mockRejectedValue(
        new ApiError(422, "The transport 'ext' is not permitted. Allowed transports: https."),
      );

    render(
      <MemoryRouter>
        <SubmitForm onSubmit={submit} />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByLabelText(/repository url/i), "ext::sh -c whoami");
    await userEvent.click(screen.getByRole("button", { name: /start scan/i }));

    // Verbatim, not paraphrased into "Invalid URL": the allowed-transports half is the
    // only part that tells the reader what to do next.
    expect(
      await screen.findByText(/the transport 'ext' is not permitted/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/allowed transports: https/i)).toBeInTheDocument();
  });

  it("does not submit an empty url", async () => {
    const submit = vi.fn();
    render(
      <MemoryRouter>
        <SubmitForm onSubmit={submit} />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: /start scan/i }));
    expect(submit).not.toHaveBeenCalled();
  });
});
