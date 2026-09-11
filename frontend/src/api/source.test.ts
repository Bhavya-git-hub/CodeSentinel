import { describe, expect, it } from "vitest";

import { ApiError } from "./client";
import { demoSource } from "./demo";
import { selectSource } from "./source";
import type { DataSource } from "./types";

/** A live client that fails the way an unreachable backend fails. */
function failingLive(): DataSource {
  const boom = () => Promise.reject(new ApiError(503, "database unavailable"));
  return {
    submitScan: boom,
    getScan: boom,
    getMetrics: boom,
    listScans: boom,
  };
}

describe("selectSource", () => {
  it("serves fixtures only when demo mode is explicitly set", () => {
    expect(selectSource({ demo: "1" }, demoSource, failingLive())).toBe(demoSource);
  });

  it("serves the live client by default", () => {
    const live = failingLive();
    expect(selectSource({}, demoSource, live)).toBe(live);
  });

  it("does not treat an arbitrary value as demo mode", () => {
    const live = failingLive();
    expect(selectSource({ demo: "0" }, demoSource, live)).toBe(live);
    expect(selectSource({ demo: "false" }, demoSource, live)).toBe(live);
    expect(selectSource({ demo: "" }, demoSource, live)).toBe(live);
  });

  it("never falls back to fixtures when the live client fails", async () => {
    const selected = selectSource({}, demoSource, failingLive());

    // The assertion is the absence of a feature. A UI that quietly served samples here
    // would be a confident report about a repository nobody analysed -- exactly what
    // the backend spends five phases preventing. Do not delete this test to make a
    // "graceful degradation" change pass.
    await expect(selected.getScan("any-id")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("demo fixtures", () => {
  it("carry a genuinely unknown complexity rather than a flattering number", async () => {
    const queue = await demoSource.getMetrics("any-id");
    expect(queue.files.every((file) => file.cyclomatic_complexity === null)).toBe(true);
    expect(queue.unmeasured).toBeGreaterThan(0);
  });

  it("report a partial status, because that is what the real scan produced", async () => {
    expect((await demoSource.getScan("any-id")).status).toBe("partial");
  });
});
