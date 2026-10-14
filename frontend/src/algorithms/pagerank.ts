/**
 * PageRank by power iteration, stepwise, for the in-browser Playground.
 * Port of backend/algorithms/pagerank.py; tested against fixtures exported from it.
 *
 *   p_{k+1} = alpha * (M^T p_k + dangling_mass_k * w) + (1 - alpha) * v
 */
import { adjacency, l1, sum, type Adjacency, type Graph } from "./graph";

export type Dangling = "teleport" | "uniform" | "self_loop" | "remove_readd";
export const DANGLING_STRATEGIES: Dangling[] = ["teleport", "uniform", "self_loop", "remove_readd"];

export interface PageRankParams {
  alpha: number;
  tol: number;
  maxIter: number;
  dangling: Dangling;
  /** Teleport seed nodes; null or empty means uniform teleport. */
  seeds: number[] | null;
}

export const DEFAULT_PARAMS: PageRankParams = { alpha: 0.85, tol: 1e-8, maxIter: 200, dangling: "teleport", seeds: null };

export interface PageRankState {
  scores: Float64Array;
  /** Iterations performed so far (core + re-add passes for remove_readd). */
  iteration: number;
  residuals: number[];
  converged: boolean;
  done: boolean;
  /** remove_readd only: which pass is running and what stripping found. */
  phase: "main" | "core" | "readd";
  strippingRounds: number;
  coreSize: number;
}

/** Uniform over seeds, or uniform over all nodes when there are no seeds. */
export function teleportVector(n: number, seeds: number[] | null): Float64Array {
  const v = new Float64Array(n);
  const unique = seeds ? [...new Set(seeds)].filter((s) => s >= 0 && s < n) : [];
  if (unique.length === 0) v.fill(1 / n);
  else for (const s of unique) v[s] = 1 / unique.length;
  return v;
}

/** One power-iteration step on adjacency `adj`; returns the renormalised next iterate. */
function powerStep(
  adj: Adjacency,
  x: Float64Array,
  alpha: number,
  v: Float64Array,
  dangling: "teleport" | "uniform" | "self_loop",
): Float64Array {
  const n = adj.n;
  const next = new Float64Array(n);
  let danglingMass = 0;
  for (let i = 0; i < n; i++) {
    const outs = adj.out[i];
    if (outs.length === 0) {
      danglingMass += x[i];
      if (dangling === "self_loop") next[i] += alpha * x[i];
      continue;
    }
    const share = (alpha * x[i]) / outs.length;
    for (const j of outs) next[j] += share;
  }
  for (let j = 0; j < n; j++) {
    if (dangling === "teleport") next[j] += alpha * danglingMass * v[j];
    else if (dangling === "uniform") next[j] += (alpha * danglingMass) / n;
    next[j] += (1 - alpha) * v[j];
  }
  const total = sum(next);
  for (let j = 0; j < n; j++) next[j] /= total; // float drift only
  return next;
}

/** Repeatedly strip dangling nodes. Returns surviving node ids and the number of rounds. */
export function stripDangling(adj: Adjacency): { core: number[]; rounds: number } {
  const n = adj.n;
  const outdeg = adj.out.map((o) => o.length);
  const alive = new Array<boolean>(n).fill(true);
  let frontier = [...Array(n).keys()].filter((i) => outdeg[i] === 0);
  let rounds = 0;
  while (frontier.length) {
    rounds++;
    for (const f of frontier) alive[f] = false;
    for (const f of frontier) for (const p of adj.inn[f]) outdeg[p]--;
    frontier = [...Array(n).keys()].filter((i) => alive[i] && outdeg[i] === 0);
  }
  return { core: [...Array(n).keys()].filter((i) => alive[i]), rounds };
}

function subgraph(adj: Adjacency, nodes: number[]): Adjacency {
  const index = new Map(nodes.map((node, i) => [node, i]));
  const edges: [number, number][] = [];
  for (const s of nodes) for (const t of adj.out[s]) if (index.has(t)) edges.push([index.get(s)!, index.get(t)!]);
  return adjacency({ n: nodes.length, edges });
}

/** A PageRank computation that can be advanced one iteration at a time. */
export class PageRankRun {
  readonly params: PageRankParams;
  private readonly adj: Adjacency;
  private readonly v: Float64Array;
  private state: PageRankState;
  // remove_readd bookkeeping
  private core: number[] = [];
  private coreAdj: Adjacency | null = null;
  private coreV: Float64Array | null = null;
  private coreX: Float64Array | null = null;
  private readdLeft = 0;

  constructor(graph: Graph, params: PageRankParams) {
    if (graph.n === 0) throw new Error("graph has no nodes");
    if (!(params.alpha >= 0 && params.alpha <= 1)) throw new Error("alpha must be in [0, 1]");
    this.params = params;
    this.adj = adjacency(graph);
    this.v = teleportVector(graph.n, params.seeds);
    const uniform = new Float64Array(graph.n).fill(1 / graph.n);
    this.state = {
      scores: uniform,
      iteration: 0,
      residuals: [],
      converged: false,
      done: false,
      phase: "main",
      strippingRounds: 0,
      coreSize: graph.n,
    };
    if (params.dangling === "remove_readd") this.initRemoveReadd();
  }

  private initRemoveReadd(): void {
    const { core, rounds } = stripDangling(this.adj);
    this.core = core;
    this.readdLeft = rounds;
    this.state = { ...this.state, strippingRounds: rounds, coreSize: core.length };
    if (core.length === 0) {
      // Everything was stripped (a DAG): start the re-add passes from v.
      this.state = { ...this.state, phase: "readd", scores: Float64Array.from(this.v), converged: true };
      if (rounds === 0) this.state = { ...this.state, done: true };
      return;
    }
    this.coreAdj = subgraph(this.adj, core);
    let vc = Float64Array.from(core.map((i) => this.v[i]));
    const mass = sum(vc);
    vc = mass > 0 ? vc.map((x) => x / mass) : new Float64Array(core.length).fill(1 / core.length);
    this.coreV = vc;
    this.coreX = new Float64Array(core.length).fill(1 / core.length);
    this.state = { ...this.state, phase: "core", scores: this.expandCore(this.coreX) };
  }

  private expandCore(xc: Float64Array): Float64Array {
    const full = new Float64Array(this.adj.n);
    this.core.forEach((node, i) => (full[node] = xc[i]));
    return full;
  }

  get current(): PageRankState {
    return this.state;
  }

  /** Advance one iteration. No-op once done. */
  step(): PageRankState {
    const s = this.state;
    if (s.done) return s;
    const { alpha, tol, maxIter, dangling } = this.params;

    if (s.phase === "core") {
      const next = powerStep(this.coreAdj!, this.coreX!, alpha, this.coreV!, "teleport");
      const r = l1(next, this.coreX!);
      this.coreX = next;
      const coreIters = s.iteration + 1;
      const converged = r < tol;
      const coreFinished = converged || coreIters >= maxIter;
      this.state = {
        ...s,
        scores: this.expandCore(next),
        iteration: coreIters,
        residuals: [...s.residuals, r],
        converged,
        phase: coreFinished ? "readd" : "core",
        done: coreFinished && this.readdLeft === 0,
      };
      return this.state;
    }

    if (s.phase === "readd") {
      const next = powerStep(this.adj, s.scores, alpha, this.v, "teleport");
      const r = l1(next, s.scores);
      this.readdLeft--;
      this.state = {
        ...s,
        scores: next,
        iteration: s.iteration + 1,
        residuals: [...s.residuals, r],
        done: this.readdLeft <= 0,
      };
      return this.state;
    }

    const next = powerStep(this.adj, s.scores, alpha, this.v, dangling as "teleport" | "uniform" | "self_loop");
    const r = l1(next, s.scores);
    const converged = r < tol;
    this.state = {
      ...s,
      scores: next,
      iteration: s.iteration + 1,
      residuals: [...s.residuals, r],
      converged,
      done: converged || s.iteration + 1 >= maxIter,
    };
    return this.state;
  }

  /** Iterate until converged or out of iterations. */
  runToEnd(): PageRankState {
    while (!this.state.done) this.step();
    return this.state;
  }
}

export function pagerank(graph: Graph, params: Partial<PageRankParams> = {}): PageRankState {
  return new PageRankRun(graph, { ...DEFAULT_PARAMS, ...params }).runToEnd();
}
