"""Topic-sensitive PageRank (T. H. Haveliwala, "Topic-Sensitive PageRank", WWW 2002).

Offline:   p_t = PPR(seed set of topic t)                 for each topic t
Query:     p   = sum_t w_t * p_t,   w_t >= 0, sum_t w_t = 1
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import numpy as np
import scipy.sparse as sp

from .common import IterativeResult, check_mass
from .pagerank import DanglingStrategy, personalized_pagerank


def topic_vectors(
    A: sp.spmatrix | sp.sparray | np.ndarray,
    topic_seeds: Mapping[str, Iterable[int]],
    alpha: float = 0.85,
    tol: float = 1e-8,
    max_iter: int = 200,
    dangling: DanglingStrategy = "teleport",
) -> dict[str, IterativeResult]:
    """Precompute one personalized PageRank per topic: p_t = PPR(A, S_t, alpha)."""
    return {
        topic: personalized_pagerank(A, seeds, alpha=alpha, tol=tol, max_iter=max_iter, dangling=dangling)
        for topic, seeds in topic_seeds.items()
    }


def normalize_weights(weights: Mapping[str, float]) -> dict[str, float]:
    """Rescale non-negative weights to sum to 1. Raises if all are zero or any is negative."""
    if any(w < 0 for w in weights.values()):
        raise ValueError("weights must be non-negative")
    total = float(sum(weights.values()))
    if total <= 0:
        raise ValueError("at least one weight must be positive")
    return {name: float(w) / total for name, w in weights.items()}


def blend_topics(vectors: Mapping[str, np.ndarray], weights: Mapping[str, float]) -> np.ndarray:
    """Query-time blend p = sum_t w_t p_t with weights normalised to sum 1.

    Every topic named in ``weights`` must exist in ``vectors``. Since each p_t sums to 1
    and the weights are a convex combination, the blend also sums to 1.
    """
    unknown = set(weights) - set(vectors)
    if unknown:
        raise ValueError(f"unknown topics: {sorted(unknown)}")
    w = normalize_weights(weights)
    first = next(iter(vectors.values()))
    blended = np.zeros_like(np.asarray(first, dtype=np.float64))
    for topic, weight in w.items():
        blended += weight * np.asarray(vectors[topic], dtype=np.float64)
    check_mass(blended, "topic blend")
    return blended
