import type { Dangling } from "../algorithms/pagerank";

export type PlaygroundAlgorithm = "pagerank" | "hits" | "harmonic";

export interface PresetNode {
  label: string;
  x: number;
  y: number;
}

export interface Preset {
  id: string;
  name: string;
  explanation: string;
  nodes: PresetNode[];
  /** Edges by node label. */
  edges: [string, string][];
  settings: {
    algorithm: PlaygroundAlgorithm;
    alpha: number;
    dangling: Dangling;
    teleport: "uniform" | "seeds";
    seeds: string[];
  };
}

export const PRESETS: Preset[] = [
  {
    id: "paper-figure-3",
    name: "Paper Figure 3 (A/B/C)",
    explanation:
      "The worked example from Page, Brin, Motwani and Winograd's 1999 report (Figure 3). A splits its rank evenly between B and C, B passes all of its rank to C, and C passes all of its rank back to A. With α = 1, so no teleportation at all, power iteration settles at A = 0.4, B = 0.2, C = 0.4: C collects from both A and B, and A inherits everything C holds. Press Run to watch the residual fall by a constant factor each step, then lower α and see teleportation pull all three scores toward 1/3.",
    nodes: [
      { label: "A", x: 120, y: 120 },
      { label: "B", x: 480, y: 120 },
      { label: "C", x: 300, y: 380 },
    ],
    edges: [
      ["A", "B"],
      ["A", "C"],
      ["B", "C"],
      ["C", "A"],
    ],
    settings: { algorithm: "pagerank", alpha: 1, dangling: "teleport", teleport: "uniform", seeds: [] },
  },
  {
    id: "rank-sink",
    name: "Rank sink",
    explanation:
      "X and Y link only to each other, and Z feeds rank into the pair. With α = 1, rank flows into the X–Y loop and never leaves: Z drops to 0 after one step, while X and Y hand their rank back and forth forever, so the residual never shrinks and the run stops at the iteration limit. The 1999 paper calls this a rank sink and fixes it with a rank source E, today's teleport term. Set α to 0.85 and every node keeps at least (1 − α)/n of the rank, and the iteration converges.",
    nodes: [
      { label: "Z", x: 100, y: 250 },
      { label: "X", x: 340, y: 130 },
      { label: "Y", x: 540, y: 300 },
    ],
    edges: [
      ["Z", "X"],
      ["X", "Y"],
      ["Y", "X"],
    ],
    settings: { algorithm: "pagerank", alpha: 1, dangling: "teleport", teleport: "uniform", seeds: [] },
  },
  {
    id: "dangling",
    name: "Dangling node",
    explanation:
      "E has no out-links, so rank that reaches it would leave the system; once E is removed, D has no out-links either. Switch the dangling strategy and compare. Teleport returns dangling rank through the teleport vector (only to the seeds when teleport is seeded). Uniform spreads it over every node. Self-loop lets each dangling node keep its own rank, which inflates D and E. Remove & re-add, the 1999 paper's method, strips E and then D (two rounds), ranks the A–B–C core, then adds them back and runs two extra iterations, one per stripping round.",
    nodes: [
      { label: "A", x: 120, y: 120 },
      { label: "B", x: 120, y: 380 },
      { label: "C", x: 320, y: 250 },
      { label: "D", x: 480, y: 250 },
      { label: "E", x: 620, y: 250 },
    ],
    edges: [
      ["A", "B"],
      ["B", "C"],
      ["C", "A"],
      ["C", "D"],
      ["D", "E"],
    ],
    settings: { algorithm: "pagerank", alpha: 0.85, dangling: "teleport", teleport: "uniform", seeds: [] },
  },
  {
    id: "link-farm",
    name: "Link farm",
    explanation:
      "Six farm pages F1–F6 exist only to link to T, and T links back to all of them, so every bit of rank the farm receives by teleportation is recycled into T. With uniform teleport T outranks every honest page H1–H4. Now switch teleport to “chosen seed nodes”: the honest pages are already selected as seeds, which is TrustRank's idea of a vetted seed set. No honest page links into the farm, so the farm and T receive no trust at all: the rank they started with shrinks by a factor of α every iteration, and at convergence their scores are effectively 0.",
    nodes: [
      { label: "H1", x: 90, y: 110 },
      { label: "H2", x: 250, y: 70 },
      { label: "H3", x: 250, y: 220 },
      { label: "H4", x: 90, y: 260 },
      { label: "T", x: 520, y: 260 },
      { label: "F1", x: 400, y: 120 },
      { label: "F2", x: 520, y: 80 },
      { label: "F3", x: 640, y: 120 },
      { label: "F4", x: 680, y: 260 },
      { label: "F5", x: 640, y: 400 },
      { label: "F6", x: 460, y: 420 },
    ],
    edges: [
      ["H1", "H2"],
      ["H2", "H3"],
      ["H3", "H1"],
      ["H4", "H1"],
      ["H2", "H4"],
      ["H1", "H3"],
      ...(["F1", "F2", "F3", "F4", "F5", "F6"].flatMap((f) => [
        [f, "T"],
        ["T", f],
      ]) as [string, string][]),
    ],
    settings: { algorithm: "pagerank", alpha: 0.85, dangling: "teleport", teleport: "uniform", seeds: ["H1", "H2", "H3", "H4"] },
  },
  {
    id: "hub-authority",
    name: "Hub and authority",
    explanation:
      "Hubs H1–H3 each link to several of the pages A1–A3, and X links to H1. HITS is selected: an authority scores high because good hubs point to it, and a hub scores high because it points to good authorities, so A1 (linked by every hub) leads the authorities and H1 (linking to every authority) leads the hubs. Switch the algorithm to PageRank and compare: PageRank only counts incoming rank, so the hubs, which only X links to, are left with little more than the teleport floor.",
    nodes: [
      { label: "X", x: 70, y: 100 },
      { label: "H1", x: 200, y: 100 },
      { label: "H2", x: 200, y: 250 },
      { label: "H3", x: 200, y: 400 },
      { label: "A1", x: 520, y: 100 },
      { label: "A2", x: 520, y: 250 },
      { label: "A3", x: 520, y: 400 },
    ],
    edges: [
      ["X", "H1"],
      ["H1", "A1"],
      ["H1", "A2"],
      ["H1", "A3"],
      ["H2", "A1"],
      ["H2", "A2"],
      ["H3", "A1"],
      ["H3", "A3"],
    ],
    settings: { algorithm: "hits", alpha: 0.85, dangling: "teleport", teleport: "uniform", seeds: [] },
  },
];
