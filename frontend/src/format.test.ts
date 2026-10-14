import { describe, expect, it } from "vitest";
import { tidyQuery } from "./components/SearchBox";
import { formatPercentile, formatScore } from "./format";

describe("tidyQuery", () => {
  it("reduces pasted URLs to a host name", () => {
    expect(tidyQuery("  https://www.nasa.gov/missions?x=1#top ")).toBe("www.nasa.gov");
    expect(tidyQuery("http://user:pw@example.com:8080/a")).toBe("example.com");
    expect(tidyQuery("example.com.")).toBe("example.com");
    expect(tidyQuery("bücher.de")).toBe("bücher.de");
  });
});

describe("formatPercentile", () => {
  it("prints exactly 100 only for the top score", () => {
    expect(formatPercentile(100)).toBe("100");
    const n = 117_963_409;
    for (const rank of [2, 4, 38, 1000]) {
      const p = (100 * (n - rank)) / (n - 1);
      expect(formatPercentile(p)).not.toBe("100");
      expect(Number(formatPercentile(p))).toBeLessThan(100);
    }
  });

  it("uses one decimal away from the top", () => {
    expect(formatPercentile(50.34)).toBe("50.3");
    expect(formatPercentile(0)).toBe("0.0");
    expect(formatPercentile(99.5)).toBe("99.50");
  });
});

describe("formatScore", () => {
  it("switches to scientific notation for small values", () => {
    expect(formatScore(0)).toBe("0");
    expect(formatScore(0.25)).toBe("0.2500");
    expect(formatScore(8.873526e-4)).toBe("8.874e-4");
    expect(formatScore(2.1254186e7)).toBe("2.125e+7");
  });
});
