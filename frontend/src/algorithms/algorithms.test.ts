import { describe, expect, it } from "vitest";
import fixtures from "./fixtures.json";
import { harmonicCentrality } from "./harmonic";
import { hits } from "./hits";
import { DANGLING_STRATEGIES, PageRankRun, pagerank, stripDangling } from "./pagerank";
import { adjacency, sum, type Graph } from "./graph";

type Case = (typeof fixtures.cases)[number];
const graphOf = (c: Case): Graph => ({ n: c.n, edges: c.edges as [number, number][] });
const maxAbsDiff = (a: ArrayLike<number>, b: ArrayLike<number>) => {
  let m = 0;
  for (let i = 0; i < a.length; i++) m = Math.max(m, Math.abs(a[i] - b[i]));
  return m;
};

describe("TypeScript ports reproduce the Python reference implementation", () => {
  for (const c of fixtures.cases) {
    describe(c.name, () => {
      for (const dangling of DANGLING_STRATEGIES) {
        for (const teleport of ["uniform", "seeds"] as const) {
          for (const alpha of [0.5, 0.85]) {
            it(`pagerank ${dangling} / ${teleport} / alpha=${alpha}`, () => {
              const ref = (c.pagerank as Record<string, { scores: number[]; iterations: number; converged: boolean }>)[
                `${dangling}|${teleport}|${alpha}`
              ];
              const ours = pagerank(graphOf(c), {
                alpha,
                dangling,
                tol: fixtures.tol,
                maxIter: fixtures.maxIter,
                seeds: teleport === "seeds" ? c.seeds : null,
              });
              expect(maxAbsDiff(ours.scores, ref.scores)).toBeLessThan(1e-9);
              expect(Math.abs(sum(ours.scores) - 1)).toBeLessThan(1e-9);
              expect(ours.converged).toBe(ref.converged);
              expect(Math.abs(ours.iteration - ref.iterations)).toBeLessThanOrEqual(1);
            });
          }
        }
      }
      it("hits", () => {
        const ours = hits(graphOf(c), fixtures.tol, fixtures.maxIter);
        expect(maxAbsDiff(ours.hubs, c.hits.hubs)).toBeLessThan(1e-9);
        expect(maxAbsDiff(ours.authorities, c.hits.authorities)).toBeLessThan(1e-9);
      });
      it("harmonic centrality", () => {
        expect(maxAbsDiff(harmonicCentrality(graphOf(c)), c.harmonic)).toBeLessThan(1e-12);
      });
    });
  }
});

describe("paper examples", () => {
  it("Figure 3 converges to A=0.4, B=0.2, C=0.4 with alpha=1", () => {
    const r = pagerank({ n: 3, edges: [[0, 1], [0, 2], [1, 2], [2, 0]] }, { alpha: 1, tol: 1e-12, maxIter: 1000 });
    expect(r.converged).toBe(true);
    expect(maxAbsDiff(r.scores, [0.4, 0.2, 0.4])).toBeLessThan(1e-6);
  });

  it("rank sink: alpha=1 drains the feeder, alpha=0.85 keeps every node positive", () => {
    const g: Graph = { n: 3, edges: [[2, 0], [0, 1], [1, 0]] };
    const sink = pagerank(g, { alpha: 1 });
    expect(sink.scores[2]).toBeLessThan(1e-12);
    expect(sink.converged).toBe(false);
    const damped = pagerank(g, { alpha: 0.85 });
    expect(Math.min(...damped.scores)).toBeGreaterThan(0);
  });
});

describe("stepping", () => {
  it("step() advances one iteration and records one residual", () => {
    const run = new PageRankRun({ n: 3, edges: [[0, 1], [1, 2], [2, 0]] }, {
      alpha: 0.85, tol: 1e-8, maxIter: 200, dangling: "teleport", seeds: null,
    });
    expect(run.current.iteration).toBe(0);
    run.step();
    expect(run.current.iteration).toBe(1);
    expect(run.current.residuals).toHaveLength(1);
  });

  it("remove_readd reports stripping rounds", () => {
    const g: Graph = { n: 5, edges: [[0, 1], [1, 0], [1, 2], [2, 3], [3, 4]] };
    expect(stripDangling(adjacency(g)).rounds).toBe(3);
    const r = pagerank(g, { dangling: "remove_readd" });
    expect(r.strippingRounds).toBe(3);
    expect(Math.min(...r.scores)).toBeGreaterThan(0);
  });
});
