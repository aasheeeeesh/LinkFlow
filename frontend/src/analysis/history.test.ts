import { describe, expect, it } from "vitest";
import { historySeries, shortRelease } from "./history";

describe("shortRelease", () => {
  it("shortens Common Crawl release names", () => {
    expect(shortRelease("cc-main-2026-apr-may-jun")).toBe("Apr–Jun 2026");
    expect(shortRelease("cc-main-2025-26-dec-jan-feb")).toBe("Dec 2025–Feb 2026");
    expect(shortRelease("test-release")).toBe("test-release");
  });
});

describe("historySeries", () => {
  it("keeps the order of the points and indexes releases", () => {
    const p = (release: string, pr: number, hc: number) =>
      ({ release, pr_rank: pr, hc_rank: hc, domains: 10 });
    expect(historySeries([p("a", 5, 7), p("b", 3, 9)])).toEqual([[0, 1], [5, 3], [7, 9]]);
  });
});
