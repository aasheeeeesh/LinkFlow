/**
 * Exact harmonic centrality, H(x) = sum over y != x of 1 / d(y, x), by one BFS per source.
 * Port of backend/algorithms/harmonic.py.
 */
import { adjacency, type Graph } from "./graph";

export function harmonicCentrality(graph: Graph): Float64Array {
  const adj = adjacency(graph);
  const n = adj.n;
  const H = new Float64Array(n);
  const dist = new Int32Array(n);
  const queue = new Int32Array(n);
  for (let source = 0; source < n; source++) {
    dist.fill(-1);
    dist[source] = 0;
    let head = 0;
    let tail = 0;
    queue[tail++] = source;
    while (head < tail) {
      const u = queue[head++];
      for (const w of adj.out[u]) {
        if (dist[w] === -1) {
          dist[w] = dist[u] + 1;
          H[w] += 1 / dist[w];
          queue[tail++] = w;
        }
      }
    }
  }
  return H;
}
