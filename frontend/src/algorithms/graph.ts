/** A small directed graph: nodes 0..n-1, each edge [source, target] at most once. */
export interface Graph {
  n: number;
  edges: ReadonlyArray<readonly [number, number]>;
}

/** Out- and in-neighbour lists derived from a {@link Graph}. */
export interface Adjacency {
  n: number;
  out: number[][];
  inn: number[][];
}

export function adjacency(g: Graph): Adjacency {
  const out: number[][] = Array.from({ length: g.n }, () => []);
  const inn: number[][] = Array.from({ length: g.n }, () => []);
  const seen = new Set<string>();
  for (const [s, t] of g.edges) {
    if (s < 0 || t < 0 || s >= g.n || t >= g.n) throw new Error(`edge ${s}->${t} outside 0..${g.n - 1}`);
    const key = `${s}>${t}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out[s].push(t);
    inn[t].push(s);
  }
  return { n: g.n, out, inn };
}

/** Sum of a vector. */
export function sum(x: ArrayLike<number>): number {
  let s = 0;
  for (let i = 0; i < x.length; i++) s += x[i];
  return s;
}

/** L1 distance between two vectors. */
export function l1(a: ArrayLike<number>, b: ArrayLike<number>): number {
  let s = 0;
  for (let i = 0; i < a.length; i++) s += Math.abs(a[i] - b[i]);
  return s;
}
