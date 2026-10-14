import { describe, expect, it } from "vitest";
import { computeComposite } from "./composite";

describe("computeComposite", () => {
  it("rescales weights to sum to 1 and keeps every row in the breakdown", () => {
    const r = computeComposite([
      { id: "pagerank", percentile: 90, weight: 2 },
      { id: "trustrank", percentile: 40, weight: 2 },
      { id: "seed", percentile: 10, weight: 0 },
    ]);
    expect(r.composite).toBeCloseTo(65);
    expect(r.rows.map((x) => x.id)).toEqual(["pagerank", "trustrank", "seed"]);
    expect(r.rows.reduce((t, x) => t + x.share, 0)).toBeCloseTo(1);
    expect(r.rows[2].contribution).toBe(0);
  });

  it("matches the Python implementation's example", () => {
    // backend/tests/test_other_algorithms.py::test_composite_keeps_breakdown_and_normalises_weights
    const r = computeComposite([
      { id: "a", percentile: 90, weight: 2 },
      { id: "b", percentile: 40, weight: 2 },
      { id: "c", percentile: 10, weight: 0 },
    ]);
    expect(r.composite).toBeCloseTo(65.0, 10);
  });

  it("has no composite when every weight is zero", () => {
    const r = computeComposite([{ id: "a", percentile: 50, weight: 0 }]);
    expect(r.composite).toBeNull();
    expect(r.rows[0].share).toBe(0);
  });

  it("rejects negative weights", () => {
    expect(() => computeComposite([{ id: "a", percentile: 50, weight: -1 }])).toThrow();
  });
});
