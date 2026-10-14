"""Graph builders shared by the algorithm tests."""

from __future__ import annotations

import networkx as nx
import numpy as np
import scipy.sparse as sp


def from_edges(n: int, edges: list[tuple[int, int]]) -> sp.csr_matrix:
    """CSR adjacency (row = source) for n nodes and a list of directed edges."""
    if not edges:
        return sp.csr_matrix((n, n))
    src, dst = zip(*edges)
    A = sp.csr_matrix((np.ones(len(edges)), (src, dst)), shape=(n, n))
    A.sum_duplicates()
    A.data[:] = 1.0
    return A


def random_digraph(
    rng: np.random.Generator,
    n: int,
    mean_out: float = 5.0,
    dangling_share: float = 0.2,
    self_loops: bool = False,
) -> tuple[sp.csr_matrix, nx.DiGraph]:
    """Random directed graph with roughly ``dangling_share`` of nodes having no out-links.

    Returns the CSR matrix and an equivalent networkx DiGraph whose nodes are 0..n-1.
    """
    m = int(n * mean_out)
    src = rng.integers(0, n, size=m)
    dst = rng.integers(0, n, size=m)
    keep = np.ones(m, dtype=bool)
    if not self_loops:
        keep &= src != dst
    dangling = rng.random(n) < dangling_share
    keep &= ~dangling[src]
    edges = sorted(set(zip(src[keep].tolist(), dst[keep].tolist())))
    G = nx.DiGraph()
    G.add_nodes_from(range(n))
    G.add_edges_from(edges)
    return from_edges(n, edges), G


def to_array(d: dict[int, float], n: int) -> np.ndarray:
    """Order a networkx score dict by node id."""
    return np.array([d[i] for i in range(n)])
