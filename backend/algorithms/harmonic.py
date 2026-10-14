"""Exact harmonic centrality (Boldi & Vigna, "Axioms for Centrality", Internet
Mathematics 10(3-4), 2014; the measure Common Crawl ranks domains by).

    H(x) = sum over y != x of 1 / d(y, x),   with 1/inf = 0

d(y, x) is the length of the shortest directed path from y to x, so H rewards being
reachable in few hops from many nodes (incoming distances).
"""

from __future__ import annotations

import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import shortest_path

from .common import binary_csr

EXACT_HARMONIC_MAX_NODES = 50_000


def harmonic_centrality(
    A: sp.spmatrix | sp.sparray | np.ndarray,
    max_nodes: int = EXACT_HARMONIC_MAX_NODES,
    chunk_size: int = 256,
) -> np.ndarray:
    """Exact harmonic centrality by one BFS per source node.

    Sources are processed in chunks so memory stays at ``chunk_size * n`` distances.
    Graphs with more than ``max_nodes`` nodes are refused; for the full web graph use
    Common Crawl's precomputed values instead.
    """
    B = binary_csr(A)
    n = B.shape[0]
    if n > max_nodes:
        raise ValueError(
            f"exact harmonic centrality is limited to {max_nodes:,} nodes; this graph has {n:,}"
        )
    B.setdiag(0)
    B.eliminate_zeros()
    H = np.zeros(n)
    for start in range(0, n, chunk_size):
        sources = np.arange(start, min(start + chunk_size, n))
        dist = shortest_path(B, method="D", directed=True, unweighted=True, indices=sources)
        with np.errstate(divide="ignore"):
            inv = np.where(np.isfinite(dist) & (dist > 0), 1.0 / dist, 0.0)
        H += inv.sum(axis=0)
    return H
