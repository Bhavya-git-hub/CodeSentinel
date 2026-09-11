import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { API_KEY_STORAGE_KEY, describeKey } from "../api/credentials";
import { ApiKeyPanel } from "./ApiKeyPanel";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("ApiKeyPanel", () => {
  it("saves a key the viewer types in", async () => {
    render(<ApiKeyPanel />);

    await userEvent.type(screen.getByLabelText(/Set a key/), "ci-runner:s3cret");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(window.localStorage.getItem(API_KEY_STORAGE_KEY)).toBe("ci-runner:s3cret");
    expect(screen.getByRole("status")).toHaveTextContent("Key saved in this browser.");
  });

  it("reports a refused save instead of claiming success", async () => {
    // localStorage throws in a private window and where site data is blocked. A panel
    // that said "saved" and then 401'd would send someone looking at the server for a
    // fault that is in the browser.
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    render(<ApiKeyPanel />);

    await userEvent.type(screen.getByLabelText(/Set a key/), "ci-runner:s3cret");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(screen.getByRole("status")).toHaveTextContent(/refused to store/);
    expect(screen.getByRole("status")).toHaveTextContent(/without it/);
  });

  it("never displays the secret half of a stored key", async () => {
    // A prefix on screen is a prefix in a screenshot.
    window.localStorage.setItem(API_KEY_STORAGE_KEY, "ci-runner:s3cret-value");
    render(<ApiKeyPanel />);

    expect(screen.queryByText(/s3cret-value/)).not.toBeInTheDocument();
    expect(screen.getByText("ci-runner:…")).toBeInTheDocument();
  });

  it("forgets a stored key on request", async () => {
    window.localStorage.setItem(API_KEY_STORAGE_KEY, "ci-runner:s3cret");
    render(<ApiKeyPanel />);

    await userEvent.click(screen.getByRole("button", { name: "Forget it" }));

    expect(window.localStorage.getItem(API_KEY_STORAGE_KEY)).toBeNull();
  });

  it("says plainly when no key is configured", () => {
    render(<ApiKeyPanel />);

    expect(screen.getByText(/No key configured/)).toBeInTheDocument();
  });

  it("does not offer to forget a key that was never stored", () => {
    render(<ApiKeyPanel />);

    expect(screen.queryByRole("button", { name: "Forget it" })).not.toBeInTheDocument();
  });

  it("refuses to save an empty key", async () => {
    render(<ApiKeyPanel />);

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});

describe("describeKey", () => {
  it("shows the name of a named key, because the API logs that name", () => {
    // It is what lets a viewer match what they configured against what an operator sees.
    expect(describeKey("ci-runner:s3cret")).toBe("ci-runner:…");
  });

  it("shows nothing at all for an unnamed key", () => {
    // There is no safe half of a key with no name, so no part of it is rendered.
    expect(describeKey("s3cretvalue")).toBe("…");
    expect(describeKey("s3cretvalue")).not.toContain("s3c");
  });
});
