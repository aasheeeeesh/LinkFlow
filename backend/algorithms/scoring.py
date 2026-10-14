"""Percentile ranks and the transparent composite score.

    percentile(x) = 100 * (#{y : s(y) < s(x)} + (#{y : s(y) = s(x)} - 1) / 2) / (n - 1)
                    (tied scores share the average percentile of their group)
    composite(x)  = sum_a w_a * percentile_a(x),   w_a >= 0, sum_a w_a = 1
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from scipy.stats import rankdata

from .topic_sensitive import normalize_weights


def percentile_rank(scores: np.ndarray) -> np.ndarray:
    """Mid-rank percentile in [0, 100]: tied scores get the average percentile of their group.

    A unique top score gets 100 and a unique bottom score 0. Large blocks of ties (for example
    the three distances of seed distance) land in the middle of their block instead of at its
    bottom. The Common Crawl percentiles are stored with the same definition (:func:`midrank_sql`).
    """
    s = np.asarray(scores, dtype=np.float64)
    n = s.size
    if n == 0:
        return np.zeros(0)
    if n == 1:
        return np.full(1, 100.0)
    return 100.0 * (rankdata(s, method="average") - 1) / (n - 1)


def midrank_sql(column: str, partition: str = "") -> str:
    """SQL for the same mid-rank percentile over ``column`` (optionally within ``partition``)."""
    part = f"PARTITION BY {partition} " if partition else ""
    by_value = f"PARTITION BY {partition + ', ' if partition else ''}{column}"
    total = f"count(*) OVER ({part.strip()})"
    return (
        f"CASE WHEN {total} = 1 THEN 100.0 ELSE "
        f"100.0 * ((rank() OVER ({part}ORDER BY {column}) - 1) "
        f"+ (count(*) OVER ({by_value}) - 1) / 2.0) / ({total} - 1) END"
    )


@dataclass(frozen=True)
class CompositePart:
    """One algorithm's share of the composite: contribution = weight * percentile."""

    algorithm: str
    percentile: float
    weight: float
    contribution: float


@dataclass(frozen=True)
class CompositeScore:
    """The composite and its full per-algorithm breakdown (never reported alone)."""

    composite: float
    parts: list[CompositePart]


def composite_score(percentiles: Mapping[str, float], weights: Mapping[str, float]) -> CompositeScore:
    """Weighted sum of per-algorithm percentiles with weights normalised to sum to 1.

    Algorithms with weight 0 still appear in the breakdown with contribution 0.
    """
    missing = set(weights) - set(percentiles)
    if missing:
        raise ValueError(f"no percentile for: {sorted(missing)}")
    w = normalize_weights(weights)
    parts = [
        CompositePart(algorithm=a, percentile=float(percentiles[a]), weight=w[a], contribution=w[a] * float(percentiles[a]))
        for a in weights
    ]
    return CompositeScore(composite=sum(p.contribution for p in parts), parts=parts)
