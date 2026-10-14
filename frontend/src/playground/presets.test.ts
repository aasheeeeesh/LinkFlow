/** The claims made in each preset's explanation, checked against the algorithms. */
import { describe, expect, it } from "vitest";
import type { Graph } from "../algorithms/graph";
import { hits } from "../algorithms/hits";
import { pagerank } from "../algorithms/pagerank";
import { PRESETS, type Preset } from "./presets";

function build(id: string): { p: Preset; g: Graph; at: (label: string) => number } {
  const p = PRESETS.find((x) => x.id === id)!;
  const index = new Map(p.nodes.map((n, i) => [n.label, i]));
  const g: Graph = { n: p.nodes.length, edges: p.edges.map(([s, t]) => [index.get(s)!, index.get(t)!] as [number, number]) };
  return { p, g, at: (label) => index.get(label)! };
}

describe("preset explanations match the math", () => {
  it("every preset has a unique id, edges between known nodes and an explanation", () => {
    expect(new Set(PRESETS.map((p) => p.id)).size).toBe(PRESETS.length);
    for (const p of PRESETS) {
      const labels = new Set(p.nodes.map((n) => n.label));
      for (const [s, t] of p.edges) expect(labels.has(s) && labels.has(t)).toBe(true);
      expect(p.explanation.length).toBeGreaterThan(100);
    }
  });

  it("Paper Figure 3: A = 0.4, B = 0.2, C = 0.4 at alpha 1", () => {
    const { g, at } = build("paper-figure-3");
    const r = pagerank(g, { alpha: 1 });
    expect(r.converged).toBe(true);
    expect(r.scores[at("A")]).toBeCloseTo(0.4, 6);
    expect(r.scores[at("B")]).toBeCloseTo(0.2, 6);
    expect(r.scores[at("C")]).toBeCloseTo(0.4, 6);
  });

  it("Rank sink: Z drops to 0 and the run hits the iteration limit; alpha 0.85 converges with floor (1-α)/n", () => {
    const { g, at } = build("rank-sink");
    const sink = pagerank(g, { alpha: 1, maxIter: 200 });
    expect(sink.scores[at("Z")]).toBe(0);
    expect(sink.converged).toBe(false);
    expect(sink.iteration).toBe(200);
    const damped = pagerank(g, { alpha: 0.85 });
    expect(damped.converged).toBe(true);
    for (const s of damped.scores) expect(s).toBeGreaterThanOrEqual(0.15 / 3 - 1e-12);
  });

  it("Dangling node: remove & re-add strips two rounds and the core is A-B-C", () => {
    const { g } = build("dangling");
    const r = pagerank(g, { dangling: "remove_readd" });
    expect(r.strippingRounds).toBe(2);
    expect(r.coreSize).toBe(3);
    const selfLoop = pagerank(g, { dangling: "self_loop" });
    const teleport = pagerank(g, { dangling: "teleport" });
    const { at } = build("dangling");
    expect(selfLoop.scores[at("E")]).toBeGreaterThan(teleport.scores[at("E")]); // self-loop inflates E
  });

  it("Link farm: T outranks every honest page with uniform teleport, and is effectively 0 with honest seeds", () => {
    const { p, g, at } = build("link-farm");
    const uniform = pagerank(g, { alpha: 0.85 });
    const honest = ["H1", "H2", "H3", "H4"].map(at);
    for (const h of honest) expect(uniform.scores[at("T")]).toBeGreaterThan(uniform.scores[h]);
    const trusted = pagerank(g, { alpha: 0.85, seeds: p.settings.seeds.map(at) });
    expect(trusted.converged).toBe(true);
    // The fixed point is exactly 0; the iterate keeps only start-up mass that shrinks by α per step.
    expect(trusted.scores[at("T")]).toBeLessThan(1e-8);
    for (const f of ["F1", "F2", "F3", "F4", "F5", "F6"]) expect(trusted.scores[at(f)]).toBeLessThan(1e-8);
  });

  it("Hub and authority: A1 leads authorities, H1 leads hubs", () => {
    const { g, at } = build("hub-authority");
    const r = hits(g);
    const maxIdx = (x: Float64Array) => x.indexOf(Math.max(...x));
    expect(maxIdx(r.authorities)).toBe(at("A1"));
    expect(maxIdx(r.hubs)).toBe(at("H1"));
  });
});
