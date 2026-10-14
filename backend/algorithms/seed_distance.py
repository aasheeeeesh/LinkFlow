"""Seed distance: an open approximation inspired by an attribute *name* in the 2024 leak.

The 2024 Google Content Warehouse API documentation leak lists an attribute named
"pagerank_ns" described as "PageRank-NearestSeeds". The leak documents the name only;
how Google computes it is unknown. This module is Linkflow Lab's own definition:

    d(x)     = minimum number of forward links from any seed to x (BFS)
    score(x) = beta ** d(x)   if x is reachable from the seed set, else 0
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp

from .common import binary_csr, gather_rows


@dataclass(frozen=True)
class SeedDistanceResult:
    """Attributes:
    scores: beta ** d, 0 for unreachable nodes.
    distances: hop distance d from the nearest seed, -1 for unreachable nodes.
    max_distance: largest finite distance found.
    """

    scores: np.ndarray
    distances: np.ndarray
    max_distance: int


def seed_distance(
    A: sp.spmatrix | sp.sparray | np.ndarray,
    seeds: Iterable[int],
    beta: float = 0.5,
) -> SeedDistanceResult:
    """Multi-source BFS over forward links; ``score = beta ** d`` (0 if unreachable).

    Args:
        A: n x n adjacency matrix (row i links to column j).
        seeds: seed node indices (distance 0, score 1).
        beta: per-hop decay, 0 < beta <= 1.
    """
    if not 0.0 < beta <= 1.0:
        raise ValueError("beta must be in (0, 1]")
    B = binary_csr(A)
    n = B.shape[0]
    frontier = np.unique(np.asarray(list(seeds), dtype=np.int64))
    if frontier.size == 0:
        raise ValueError("seed set is empty")
    if frontier.min() < 0 or frontier.max() >= n:
        raise ValueError(f"seed indices must lie in [0, {n - 1}]")

    dist = np.full(n, -1, dtype=np.int64)
    dist[frontier] = 0
    depth = 0
    while frontier.size:
        neighbors = np.unique(gather_rows(B.indptr, B.indices, frontier))
        frontier = neighbors[dist[neighbors] < 0]
        if frontier.size:
            depth += 1
            dist[frontier] = depth

    scores = np.zeros(n)
    reached = dist >= 0
    scores[reached] = beta ** dist[reached].astype(np.float64)
    return SeedDistanceResult(scores=scores, distances=dist, max_distance=depth)
