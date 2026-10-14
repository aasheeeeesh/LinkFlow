"""PageRank by power iteration, with selectable dangling-node strategies.

Main update (all strategies except where noted):

    p_{k+1} = alpha * (M^T p_k + (sum_{d dangling} p_k[d]) * w) + (1 - alpha) * v

where M is the row-stochastic link matrix (dangling rows zero), v the teleport
distribution and w the distribution that receives dangling mass.

References:
    L. Page, S. Brin, R. Motwani, T. Winograd. "The PageRank Citation Ranking:
    Bringing Order to the Web." Stanford InfoLab Technical Report 1999-66, 1999.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

import numpy as np
import scipy.sparse as sp

from .common import (
    CHUNK_LINKS,
    IterativeResult,
    _row_chunks,
    as_csr,
    binary_csr,
    cached_in_links,
    in_links,
    check_mass,
    gather_rows,
    out_degree,
    pull,
    seed_vector,
    teleport_vector,
)

DanglingStrategy = Literal["teleport", "uniform", "self_loop", "remove_readd"]
DANGLING_STRATEGIES: tuple[DanglingStrategy, ...] = ("teleport", "uniform", "self_loop", "remove_readd")

# Per-iteration sanity bound: before renormalising away float drift, the raw iterate
# must already sum to 1 this closely, otherwise rank is leaking and that is a bug.
_LEAK_BOUND = 1e-6


def _validate(alpha: float, tol: float, max_iter: int) -> None:
    if not 0.0 <= alpha <= 1.0:
        raise ValueError(f"alpha must be in [0, 1], got {alpha}")
    if tol <= 0:
        raise ValueError("tol must be positive")
    if max_iter < 1:
        raise ValueError("max_iter must be at least 1")


def _power_iteration(
    A: sp.csr_matrix,
    alpha: float,
    tol: float,
    max_iter: int,
    v: np.ndarray,
    dangling: Literal["teleport", "uniform", "self_loop"],
    x0: np.ndarray | None = None,
    fixed_iterations: bool = False,
) -> IterativeResult:
    """Run ``p_{k+1} = alpha (M^T p_k + dangling_mass_k w) + (1 - alpha) v`` on weighted CSR ``A``.

    With ``dangling="self_loop"`` the dangling term is ``alpha * p_k[d]`` added back to
    each dangling node d itself (a self-link). With ``fixed_iterations`` the loop runs
    exactly ``max_iter`` times regardless of ``tol``.
    """
    n = A.shape[0]
    out = out_degree(A)
    is_dangling = out == 0
    inv_out = np.zeros(n)
    inv_out[~is_dangling] = 1.0 / out[~is_dangling]
    # Sources of each node's in-links (no float copy of A); weighted graphs also carry per-link weights.
    links = in_links(A, weighted=True) if A.dtype != np.int8 else cached_in_links(A)
    w = v if dangling == "teleport" else np.full(n, 1.0 / n)

    x = np.full(n, 1.0 / n) if x0 is None else np.asarray(x0, dtype=np.float64).copy()
    residuals: list[float] = []
    converged = False
    for _ in range(max_iter):
        x_next = alpha * pull(links, x * inv_out)  # alpha * M^T x
        if dangling == "self_loop":
            x_next[is_dangling] += alpha * x[is_dangling]
        else:
            x_next += alpha * x[is_dangling].sum() * w
        x_next += (1.0 - alpha) * v

        total = x_next.sum()
        if abs(total - 1.0) > _LEAK_BOUND:
            raise AssertionError(f"rank leaked during iteration: iterate sums to {total!r}")
        x_next /= total  # remove floating-point drift only

        residual = float(np.abs(x_next - x).sum())
        residuals.append(residual)
        x = x_next
        if not fixed_iterations and residual < tol:
            converged = True
            break

    return IterativeResult(scores=x, iterations=len(residuals), residuals=residuals, converged=converged)


def strip_dangling(A: sp.csr_matrix) -> tuple[np.ndarray, int]:
    """Repeatedly remove dangling nodes (and links into them) until none remain.

    Returns ``(core, rounds)``: the sorted indices of the surviving nodes and the
    number of stripping rounds. Each round removes every node that is dangling at
    that moment; removing them can make their predecessors dangling, hence rounds.
    """
    B = binary_csr(A)
    n = B.shape[0]
    links = cached_in_links(B)
    outdeg = np.diff(B.indptr).astype(np.int64)
    alive = np.ones(n, dtype=bool)
    rounds = 0
    frontier = np.flatnonzero(outdeg == 0)
    while frontier.size:
        rounds += 1
        alive[frontier] = False
        predecessors = gather_rows(links.indptr, links.sources, frontier)  # one entry per link i -> f
        outdeg -= np.bincount(predecessors, minlength=n)
        frontier = np.flatnonzero(alive & (outdeg == 0))
    return np.flatnonzero(alive), rounds


def induced_subgraph(A: sp.csr_matrix, nodes: np.ndarray, chunk: int = CHUNK_LINKS) -> sp.csr_matrix:
    """Binary CSR of the subgraph induced by sorted ``nodes``, built row-chunk by row-chunk.

    Equivalent to ``A[nodes][:, nodes]`` without scipy's intermediate full-size copies.
    """
    B = binary_csr(A)
    n = B.shape[0]
    nodes = np.asarray(nodes, dtype=np.int64)
    new_id = np.full(n, -1, dtype=np.int64)
    new_id[nodes] = np.arange(nodes.size)
    keep_row = np.zeros(n, dtype=bool)
    keep_row[nodes] = True
    pieces: list[np.ndarray] = []
    counts = np.zeros(nodes.size, dtype=np.int64)
    for r0, r1 in _row_chunks(B.indptr, chunk):
        rows = np.arange(r0, r1)[keep_row[r0:r1]]
        if rows.size == 0:
            continue
        targets = gather_rows(B.indptr, B.indices, rows)
        row_of = np.repeat(rows, np.diff(B.indptr)[rows])
        mapped = new_id[targets]
        kept = mapped >= 0
        pieces.append(mapped[kept].astype(B.indices.dtype))
        counts[new_id[rows]] = np.bincount(row_of[kept] - r0, minlength=r1 - r0)[rows - r0]
    indptr = np.zeros(nodes.size + 1, dtype=np.int64)
    np.cumsum(counts, out=indptr[1:])
    indices = np.concatenate(pieces) if pieces else np.zeros(0, dtype=B.indices.dtype)
    return sp.csr_matrix((np.ones(indices.size, dtype=np.int8), indices, indptr), shape=(nodes.size, nodes.size))


def _remove_readd(
    A: sp.csr_matrix, alpha: float, tol: float, max_iter: int, v: np.ndarray
) -> IterativeResult:
    """Page et al. 1999, section 2.7: strip dangling nodes, rank the rest, add them back.

    1. Strip dangling nodes iteratively (``rounds`` passes) leaving a core with no
       dangling nodes.
    2. Compute PageRank on the core subgraph with v restricted to the core
       (renormalised; uniform over the core if v has no mass there).
    3. Re-insert stripped nodes with score 0 and run exactly ``rounds`` further
       iterations on the full graph. During these iterations dangling mass is
       re-injected through v, matching the paper's step that re-adds lost rank via E.
    """
    n = A.shape[0]
    core, rounds = strip_dangling(A)
    x0 = np.zeros(n)
    core_residuals: list[float] = []
    core_iterations = 0
    core_converged = True
    if core.size:
        v_core = v[core]
        v_core = v_core / v_core.sum() if v_core.sum() > 0 else np.full(core.size, 1.0 / core.size)
        A_core = induced_subgraph(A, core)
        core_result = _power_iteration(A_core, alpha, tol, max_iter, v_core, "teleport")
        x0[core] = core_result.scores
        core_residuals = core_result.residuals
        core_iterations = core_result.iterations
        core_converged = core_result.converged
    else:
        x0 = v.copy()

    if rounds:
        readd = _power_iteration(A, alpha, tol, rounds, v, "teleport", x0=x0, fixed_iterations=True)
        scores, readd_residuals = readd.scores, readd.residuals
    else:
        scores, readd_residuals = x0, []

    return IterativeResult(
        scores=scores,
        iterations=core_iterations + len(readd_residuals),
        residuals=core_residuals + readd_residuals,
        converged=core_converged,
        info={
            "stripping_rounds": float(rounds),
            "core_nodes": float(core.size),
            "core_iterations": float(core_iterations),
        },
    )


def pagerank(
    A: sp.spmatrix | sp.sparray | np.ndarray,
    alpha: float = 0.85,
    tol: float = 1e-8,
    max_iter: int = 200,
    teleport: np.ndarray | None = None,
    dangling: DanglingStrategy = "teleport",
) -> IterativeResult:
    """PageRank by power iteration on an unweighted directed graph.

    Formula:
        p_{k+1} = alpha * (M^T p_k + dangling_mass_k * w) + (1 - alpha) * v,
        dangling_mass_k = sum of p_k over dangling nodes, M[i, j] = 1/out(i) if i -> j.

    Args:
        A: n x n adjacency matrix (row i links to column j). Stored values are ignored;
            any nonzero entry counts as one link.
        alpha: damping factor (probability of following a link), 0 <= alpha <= 1.
        tol: stop when the L1 residual ||p_k - p_{k-1}||_1 < tol.
        max_iter: maximum number of iterations.
        teleport: teleport distribution v (non-negative, rescaled to sum 1);
            None means uniform v_i = 1/n.
        dangling: how rank held by dangling nodes is redistributed:
            "teleport"     w = v;
            "uniform"      w_i = 1/n;
            "self_loop"    each dangling node links to itself;
            "remove_readd" Page et al. (1999) section 2.7 strip / rank / re-add procedure.

    Returns:
        IterativeResult with scores summing to 1, iteration count and per-iteration
        L1 residuals.
    """
    _validate(alpha, tol, max_iter)
    if dangling not in DANGLING_STRATEGIES:
        raise ValueError(f"dangling must be one of {DANGLING_STRATEGIES}, got {dangling!r}")
    B = binary_csr(A)
    v = teleport_vector(B.shape[0], teleport)
    if dangling == "remove_readd":
        result = _remove_readd(B, alpha, tol, max_iter, v)
    else:
        result = _power_iteration(B, alpha, tol, max_iter, v, dangling)
    check_mass(result.scores, f"pagerank[{dangling}]")
    return result


def weighted_pagerank(
    A: sp.spmatrix | sp.sparray | np.ndarray,
    alpha: float = 0.85,
    tol: float = 1e-8,
    max_iter: int = 200,
    teleport: np.ndarray | None = None,
    dangling: Literal["teleport", "uniform", "self_loop"] = "teleport",
) -> IterativeResult:
    """PageRank with transition probabilities proportional to edge weight.

    Formula: p_{k+1} = alpha (W^T p_k + dangling_mass_k w) + (1 - alpha) v with
    W[i, j] = A[i, j] / sum_k A[i, k]. Linkflow Lab's weight is the number of host-level links between
    two domains. A canonical float32/float64/integer CSR matrix is used without copying.
    """
    _validate(alpha, tol, max_iter)
    if dangling not in ("teleport", "uniform", "self_loop"):
        raise ValueError("weighted_pagerank supports dangling = teleport, uniform or self_loop")
    if (
        sp.issparse(A) and A.format == "csr" and A.has_canonical_format and A.shape[0] == A.shape[1]
        and A.dtype in (np.float32, np.float64, np.int32, np.int64)
    ):
        W = A if A.dtype in (np.float32, np.float64) else A.astype(np.float32)
        if W.nnz and W.data.min() < 0:
            raise ValueError("weights must be non-negative")
    else:
        W = as_csr(A)
    W.eliminate_zeros()
    v = teleport_vector(W.shape[0], teleport)
    result = _power_iteration(W, alpha, tol, max_iter, v, dangling)
    check_mass(result.scores, "weighted pagerank")
    return result


def alpha_from_e_norm(e_norm: float) -> float:
    """Damping factor equivalent to the 1999 rank source of size ``||E||_1``.

    On a graph without dangling nodes, R' = c(A R' + E) with ||R'||_1 = 1 forces
    c = 1 / (1 + ||E||_1), and the equation becomes the standard update with
    alpha = c and v = E / ||E||_1.
    """
    if e_norm <= 0:
        raise ValueError("||E||_1 must be positive")
    return 1.0 / (1.0 + e_norm)


def e_norm_from_alpha(alpha: float) -> float:
    """Inverse of :func:`alpha_from_e_norm`: ``||E||_1 = (1 - alpha) / alpha``."""
    if not 0.0 < alpha <= 1.0:
        raise ValueError("alpha must be in (0, 1]")
    return (1.0 - alpha) / alpha


def pagerank_1999(
    A: sp.spmatrix | sp.sparray | np.ndarray,
    e_norm: float = 0.15,
    E: np.ndarray | None = None,
    tol: float = 1e-8,
    max_iter: int = 200,
) -> IterativeResult:
    """The 1999 tech-report formulation ``R' = c (A R' + E)`` with ``||R'||_1 = 1``.

    Here the paper's A is our M^T (A_{u,v} = 1/N_v if v -> u) and E is a "source of rank"
    vector. Because ||R'||_1 = 1, the equation is R' = c (A + E 1^T) R': R' is the
    dominant eigenvector of A + E 1^T and c is the reciprocal of its eigenvalue.
    It is solved by power iteration:

        y_k = A R_k + E * ||R_k||_1,   R_{k+1} = y_k / ||y_k||_1,   c = 1 / ||y_k||_1.

    Dangling nodes are left as the paper's raw equation has them (their columns of A
    are zero); c absorbs the lost mass. Without dangling nodes c = 1 / (1 + ||E||_1),
    so ||E||_1 = 0.15 corresponds to alpha = 1/1.15 ~= 0.8696 and alpha = 0.85
    corresponds to ||E||_1 = 0.15/0.85 ~= 0.1765.

    Args:
        A: n x n adjacency matrix (row i links to column j).
        e_norm: ||E||_1, used when E is None (E uniform with this total).
        E: explicit non-negative rank source vector; overrides e_norm.
        tol: stop when ||R_k - R_{k-1}||_1 < tol.
        max_iter: maximum iterations.

    Returns:
        IterativeResult; ``info`` holds ``c``, ``e_norm`` and the equivalent alpha
        for a graph without dangling nodes.
    """
    if max_iter < 1 or tol <= 0:
        raise ValueError("tol must be positive and max_iter at least 1")
    B = binary_csr(A)
    n = B.shape[0]
    if E is None:
        if e_norm <= 0:
            raise ValueError("||E||_1 must be positive")
        E_vec = np.full(n, e_norm / n)
    else:
        E_vec = np.asarray(E, dtype=np.float64).ravel()
        if E_vec.shape != (n,) or (E_vec < 0).any() or E_vec.sum() <= 0:
            raise ValueError("E must be a non-negative length-n vector with positive mass")
    e_total = float(E_vec.sum())

    out = out_degree(B)
    inv_out = np.zeros(n)
    inv_out[out > 0] = 1.0 / out[out > 0]
    links = cached_in_links(B)

    R = np.full(n, 1.0 / n)
    residuals: list[float] = []
    converged = False
    c = float("nan")
    for _ in range(max_iter):
        y = pull(links, R * inv_out) + E_vec * R.sum()
        norm = y.sum()
        c = 1.0 / norm
        R_next = y / norm
        residual = float(np.abs(R_next - R).sum())
        residuals.append(residual)
        R = R_next
        if residual < tol:
            converged = True
            break

    check_mass(R, "pagerank_1999")
    return IterativeResult(
        scores=R,
        iterations=len(residuals),
        residuals=residuals,
        converged=converged,
        info={"c": c, "e_norm": e_total, "alpha_equivalent": alpha_from_e_norm(e_total)},
    )


def personalized_pagerank(
    A: sp.spmatrix | sp.sparray | np.ndarray,
    seeds: Iterable[int],
    alpha: float = 0.85,
    tol: float = 1e-8,
    max_iter: int = 200,
    dangling: DanglingStrategy = "teleport",
) -> IterativeResult:
    """Personalized PageRank: :func:`pagerank` with v uniform over a seed set S.

    Formula: p = alpha (M^T p + dangling_mass w) + (1 - alpha) v,  v_i = 1/|S| for i in S.
    With the default ``dangling="teleport"`` dangling mass also returns to the seeds.
    """
    B = binary_csr(A)
    v = seed_vector(B.shape[0], seeds)
    return pagerank(B, alpha=alpha, tol=tol, max_iter=max_iter, teleport=v, dangling=dangling)


def trustrank(
    A: sp.spmatrix | sp.sparray | np.ndarray,
    trusted_seeds: Iterable[int],
    alpha: float = 0.85,
    tol: float = 1e-8,
    max_iter: int = 200,
    dangling: DanglingStrategy = "teleport",
) -> IterativeResult:
    """TrustRank (Gyongyi, Garcia-Molina, Pedersen, VLDB 2004).

    Trust propagates from a manually vetted seed set of reputable nodes:
        t = alpha (M^T t + dangling_mass w) + (1 - alpha) d,  d_i = 1/|S| for i in S.
    This is personalized PageRank whose seeds are the trusted set. The paper ran a fixed
    20 iterations; here we iterate to ``tol``.
    """
    return personalized_pagerank(
        A, trusted_seeds, alpha=alpha, tol=tol, max_iter=max_iter, dangling=dangling
    )
