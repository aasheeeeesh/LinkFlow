/**
 * HITS hubs and authorities (Kleinberg 1999), stepwise. Port of backend/algorithms/hits.py.
 *
 *   a_{k+1} = A^T h_k, L2-normalised;   h_{k+1} = A a_{k+1}, L2-normalised
 */
import { adjacency, l1, type Adjacency, type Graph } from "./graph";

export interface HitsState {
  hubs: Float64Array;
  authorities: Float64Array;
  iteration: number;
  residuals: number[];
  converged: boolean;
  done: boolean;
}

function normalizeL2(x: Float64Array): Float64Array {
  let s = 0;
  for (const v of x) s += v * v;
  const norm = Math.sqrt(s);
  return norm > 0 ? x.map((v) => v / norm) : x;
}

export class HitsRun {
  private readonly adj: Adjacency;
  private state: HitsState;

  constructor(
    graph: Graph,
    readonly tol = 1e-8,
    readonly maxIter = 100,
  ) {
    if (graph.n === 0) throw new Error("graph has no nodes");
    this.adj = adjacency(graph);
    this.state = {
      hubs: new Float64Array(graph.n).fill(1 / Math.sqrt(graph.n)),
      authorities: new Float64Array(graph.n),
      iteration: 0,
      residuals: [],
      converged: false,
      done: false,
    };
  }

  get current(): HitsState {
    return this.state;
  }

  step(): HitsState {
    const s = this.state;
    if (s.done) return s;
    const n = this.adj.n;
    const a = new Float64Array(n);
    for (let j = 0; j < n; j++) for (const i of this.adj.inn[j]) a[j] += s.hubs[i];
    const aN = normalizeL2(a);
    const h = new Float64Array(n);
    for (let i = 0; i < n; i++) for (const j of this.adj.out[i]) h[i] += aN[j];
    const hN = normalizeL2(h);
    const r = l1(aN, s.authorities) + l1(hN, s.hubs);
    const converged = r < this.tol;
    this.state = {
      hubs: hN,
      authorities: aN,
      iteration: s.iteration + 1,
      residuals: [...s.residuals, r],
      converged,
      done: converged || s.iteration + 1 >= this.maxIter,
    };
    return this.state;
  }

  runToEnd(): HitsState {
    while (!this.state.done) this.step();
    return this.state;
  }
}

export function hits(graph: Graph, tol = 1e-8, maxIter = 100): HitsState {
  return new HitsRun(graph, tol, maxIter).runToEnd();
}
