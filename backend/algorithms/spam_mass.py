"""Spam mass estimation (Gyongyi, Berkhin, Garcia-Molina, Pedersen, VLDB 2006).

    p        = PageRank with uniform teleport u
    p_plus   = gamma * PR(core-only jump vector), on the same scale as p
    M        = p - p_plus                   (absolute spam mass)
    m        = M / p                        (relative spam mass, <= 1)

A node is flagged as "likely link-spam supported" when m > threshold.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

import numpy as np
import scipy.sparse as sp

from .common import IterativeResult, binary_csr, out_degree
from .pagerank import pagerank, personalized_pagerank

SpamDangling = Literal["teleport", "uniform", "self_loop"]


@dataclass(frozen=True)
class SpamMassResult:
    """Spam-mass estimates for every node.

    Attributes:
        pagerank: global PageRank p (sums to 1).
        core_pagerank: estimated good contribution p_plus, on the same scale as p.
        absolute_mass: M = p - p_plus (negative when the core over-explains a node).
        relative_mass: m = M / p.
        flagged: m > threshold.
        threshold: the relative-mass cut-off used for ``flagged``.
        good_fraction: gamma, the share of the graph assumed good.
        global_run: convergence record of the global PageRank run.
        core_run: convergence record of the core-personalized run.
    """

    pagerank: np.ndarray
    core_pagerank: np.ndarray
    absolute_mass: np.ndarray
    relative_mass: np.ndarray
    flagged: np.ndarray
    threshold: float
    good_fraction: float
    global_run: IterativeResult
    core_run: IterativeResult


def _linear_scale(scores: np.ndarray, is_dangling: np.ndarray, alpha: float, dangling: SpamDangling) -> float:
    """Factor k with L0(v) = k * PR(v), where L0(v) = (1 - alpha)(I - alpha M^T)^{-1} v.

    For "teleport" the fixed point satisfies p = alpha M^T p + (alpha delta + 1 - alpha) v
    with delta the dangling mass of p, so k = (1 - alpha) / (1 - alpha + alpha delta).
    "uniform" and "self_loop" already solve a linear, mass-preserving system: k = 1.
    """
    if dangling != "teleport":
        return 1.0
    delta = float(scores[is_dangling].sum())
    return (1.0 - alpha) / (1.0 - alpha + alpha * delta)


def spam_mass(
    A: sp.spmatrix | sp.sparray | np.ndarray,
    good_core: Iterable[int],
    alpha: float = 0.85,
    threshold: float = 0.7,
    good_fraction: float = 1.0,
    tol: float = 1e-8,
    max_iter: int = 200,
    dangling: SpamDangling = "teleport",
) -> SpamMassResult:
    """Estimate how much of each node's PageRank is not explained by a trusted good core.

    The paper works with the linear PageRank system L0(v) = (1 - alpha)(I - alpha M^T)^{-1} v,
    where dangling rows of M are zero; L0 is linear in the jump vector v. The core-based
    estimate uses the jump vector w = gamma * (uniform over the core):

        p_lin      = L0(u)
        p_plus_lin = L0(w) = gamma * L0(v_core)
        m          = 1 - p_plus_lin / p_lin

    Teleport-dangling PageRank equals L0 up to a scalar (see ``_linear_scale``), so we
    compute both runs with :func:`pagerank`, map them onto the L0 scale and report
    p, p_plus and M rescaled so that p sums to 1. "uniform" and "self_loop" give other
    linear systems and are offered for comparison; "remove_readd" is not linear.

    Choice of gamma (``good_fraction``):
        1 (default)        p_plus is the core-personalized PageRank itself: the whole
                           graph is assumed good unless the core fails to explain it.
        |core| / n         the exact contribution of jumps into the core, so 0 <= M <= p;
                           strongly overstates mass when the core is small.
        estimated good     the paper's scaled estimator: the expected share of good
        share              nodes in the graph.

    Args:
        A: n x n adjacency matrix.
        good_core: indices of the known-good core (the paper's V-tilde-plus).
        alpha: damping factor, 0 <= alpha < 1.
        threshold: relative mass above which a node is flagged.
        good_fraction: gamma in (0, 1].
        tol, max_iter: passed to the two PageRank runs.
        dangling: "teleport" (paper's formulation), "uniform" or "self_loop".
    """
    if dangling not in ("teleport", "uniform", "self_loop"):
        raise ValueError("spam_mass needs a linear dangling strategy: 'teleport', 'uniform' or 'self_loop'")
    if not 0.0 <= alpha < 1.0:
        raise ValueError("spam_mass requires 0 <= alpha < 1")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be in [0, 1]")
    if not 0.0 < good_fraction <= 1.0:
        raise ValueError("good_fraction must be in (0, 1]")
    B = binary_csr(A)
    n = B.shape[0]
    core = np.unique(np.asarray(list(good_core), dtype=np.int64))
    is_dangling = out_degree(B) == 0

    global_run = pagerank(B, alpha=alpha, tol=tol, max_iter=max_iter, dangling=dangling)
    core_run = personalized_pagerank(B, core, alpha=alpha, tol=tol, max_iter=max_iter, dangling=dangling)

    p = global_run.scores
    k_global = _linear_scale(p, is_dangling, alpha, dangling)
    k_core = _linear_scale(core_run.scores, is_dangling, alpha, dangling)
    p_plus = good_fraction * (k_core / k_global) * core_run.scores
    absolute = p - p_plus
    relative = np.divide(absolute, p, out=np.zeros(n), where=p > 0)
    return SpamMassResult(
        pagerank=p,
        core_pagerank=p_plus,
        absolute_mass=absolute,
        relative_mass=relative,
        flagged=relative > threshold,
        threshold=threshold,
        good_fraction=good_fraction,
        global_run=global_run,
        core_run=core_run,
    )
