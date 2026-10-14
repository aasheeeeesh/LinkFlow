"""HITS hubs and authorities (J. Kleinberg, "Authoritative Sources in a Hyperlinked
Environment", Journal of the ACM 46(5), 1999).

    a_{k+1} = A^T h_k,       a_{k+1} <- a_{k+1} / ||a_{k+1}||_2
    h_{k+1} = A a_{k+1},     h_{k+1} <- h_{k+1} / ||h_{k+1}||_2
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp

from .common import binary_csr

KLEINBERG_IN_CAP = 50


@dataclass(frozen=True)
class HITSResult:
    """Attributes:
    hubs, authorities: L2-normalised score vectors.
    iterations: iterations performed.
    residuals: ||a_k - a_{k-1}||_1 + ||h_k - h_{k-1}||_1 per iteration.
    converged: residual fell below tol.
    """

    hubs: np.ndarray
    authorities: np.ndarray
    iterations: int
    residuals: list[float]
    converged: bool


def _l2_normalize(x: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(x)
    return x / norm if norm > 0 else x


def hits(
    A_sub: sp.spmatrix | sp.sparray | np.ndarray,
    tol: float = 1e-8,
    max_iter: int = 100,
) -> HITSResult:
    """Kleinberg's mutually reinforcing hub/authority iteration on a (query) subgraph.

    Formula: a = A^T h, h = A a, each L2-normalised every step, starting from
    h_0 = 1/sqrt(n). Converges to the principal left/right singular vectors of A
    when the top singular value is simple.
    """
    if tol <= 0 or max_iter < 1:
        raise ValueError("tol must be positive and max_iter at least 1")
    B = binary_csr(A_sub)
    n = B.shape[0]
    BT = B.T.tocsr()
    h = np.full(n, 1.0 / np.sqrt(n)) if n else np.zeros(0)
    a = np.zeros(n)
    residuals: list[float] = []
    converged = False
    for _ in range(max_iter):
        a_next = _l2_normalize(BT @ h)
        h_next = _l2_normalize(B @ a_next)
        residual = float(np.abs(a_next - a).sum() + np.abs(h_next - h).sum())
        residuals.append(residual)
        a, h = a_next, h_next
        if residual < tol:
            converged = True
            break
    return HITSResult(hubs=h, authorities=a, iterations=len(residuals), residuals=residuals, converged=converged)


def build_base_set(
    A: sp.spmatrix | sp.sparray | np.ndarray,
    root: Iterable[int],
    max_in_per_root: int = KLEINBERG_IN_CAP,
    in_priority: np.ndarray | None = None,
) -> np.ndarray:
    """Kleinberg's base set: root set + all out-neighbours + up to d in-neighbours per root.

    Kleinberg allowed "an arbitrary set" of at most d in-neighbours per root page. To be
    deterministic we keep the d in-neighbours with the highest ``in_priority`` (for example
    PageRank), breaking ties by lower node index; without priorities, the d lowest indices.

    Returns:
        Sorted array of node indices in the base set.
    """
    B = binary_csr(A)
    n = B.shape[0]
    root_idx = np.unique(np.asarray(list(root), dtype=np.int64))
    if root_idx.size and (root_idx.min() < 0 or root_idx.max() >= n):
        raise ValueError(f"root indices must lie in [0, {n - 1}]")
    BT = B.T.tocsr()
    members: list[np.ndarray] = [root_idx, np.unique(B[root_idx].indices)]
    for r in root_idx:
        preds = BT.indices[BT.indptr[r] : BT.indptr[r + 1]]
        if preds.size > max_in_per_root:
            if in_priority is None:
                preds = np.sort(preds)[:max_in_per_root]
            else:
                order = np.lexsort((preds, -np.asarray(in_priority)[preds]))
                preds = preds[order[:max_in_per_root]]
        members.append(preds)
    return np.unique(np.concatenate(members))


def base_subgraph(A: sp.spmatrix | sp.sparray | np.ndarray, nodes: np.ndarray) -> sp.csr_matrix:
    """Induced subgraph on ``nodes`` with self-links removed (Kleinberg drops intrinsic links)."""
    B = binary_csr(A)[nodes][:, nodes].tocsr()
    B.setdiag(0)
    B.eliminate_zeros()
    return B
