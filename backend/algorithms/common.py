"""Shared types and helpers for the link-analysis algorithms.

Conventions used by every algorithm in this package:

* ``A`` is an ``n x n`` scipy.sparse CSR adjacency matrix with ``A[i, j] != 0``
  meaning "node i links to node j" (row = source, column = target).
* ``out(i)`` is the number of distinct out-links of i (row i's nonzero count);
  a node with ``out(i) == 0`` is *dangling*.
* ``M`` is the row-stochastic transition matrix ``M[i, j] = A[i, j] / out(i)``
  for non-dangling i; dangling rows of M are zero.
"""

from __future__ import annotations

import weakref
from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp

MASS_TOLERANCE = 1e-9


@dataclass(frozen=True)
class IterativeResult:
    """Output of an iterative score computation.

    Attributes:
        scores: final score vector, length n.
        iterations: number of iterations actually performed.
        residuals: L1 residual ``||x_k - x_{k-1}||_1`` after each iteration k = 1..iterations.
        converged: True if the last residual fell below ``tol`` before ``max_iter``.
        info: algorithm-specific extras (for example the 1999 normalising constant c).
    """

    scores: np.ndarray
    iterations: int
    residuals: list[float]
    converged: bool
    info: dict[str, float] = field(default_factory=dict)


def as_csr(A: sp.spmatrix | sp.sparray | np.ndarray) -> sp.csr_matrix:
    """Validate ``A`` as a square, non-negative adjacency matrix and return a float64 CSR copy."""
    if not sp.issparse(A):
        A = sp.csr_matrix(np.asarray(A, dtype=np.float64))
    A = sp.csr_matrix(A, dtype=np.float64, copy=True)
    if A.ndim != 2 or A.shape[0] != A.shape[1]:
        raise ValueError(f"adjacency matrix must be square, got shape {A.shape}")
    A.sum_duplicates()
    A.eliminate_zeros()
    if A.nnz and A.data.min() < 0:
        raise ValueError("adjacency matrix must be non-negative")
    return A


def binary_csr(A: sp.spmatrix | sp.sparray | np.ndarray) -> sp.csr_matrix:
    """Return the link structure of ``A``: canonical CSR, int8 ones, int32 indices when possible.

    Every stored nonzero becomes one link. A large matrix that is already in this form
    (for example the subgraph loaded from .npz) is returned without copying, so callers
    never pay for a float64 copy of hundreds of millions of links.
    """
    if (
        sp.issparse(A)
        and A.format == "csr"
        and A.dtype == np.int8
        and A.shape[0] == A.shape[1]
        and A.has_canonical_format
        and (A.nnz == 0 or (A.data.min() == 1 and A.data.max() == 1))
    ):
        return A
    B = as_csr(A)
    idx_dtype = np.int32 if B.shape[0] < 2**31 else np.int64
    return sp.csr_matrix(
        (np.ones(B.nnz, dtype=np.int8), B.indices.astype(idx_dtype), B.indptr.astype(np.int64)),
        shape=B.shape,
    )


def out_degree(A: sp.csr_matrix) -> np.ndarray:
    """Weighted out-degree ``out(i) = sum_j A[i, j]`` (equals the link count for binary A)."""
    if A.dtype == np.int8:
        return np.diff(A.indptr).astype(np.float64)
    return np.asarray(A.sum(axis=1)).ravel()


# Links handled per chunk by the propagation helpers below; bounds temporary memory.
CHUNK_LINKS = 8_000_000
FAST_PULL_MAX_LINKS = 50_000_000  # below this, A^T is also kept as a float64 CSR (8 bytes per link) for faster products


def _row_chunks(indptr: np.ndarray, chunk: int) -> list[tuple[int, int]]:
    """Split rows into consecutive ranges holding at most ``chunk`` links each (one big row may exceed it)."""
    n = len(indptr) - 1
    bounds = [0]
    while bounds[-1] < n:
        lo = bounds[-1]
        hi = int(np.searchsorted(indptr, indptr[lo] + chunk, side="right")) - 1
        bounds.append(min(n, max(hi, lo + 1)))
    return list(zip(bounds[:-1], bounds[1:]))


@dataclass(frozen=True)
class InLinks:
    """Transposed link structure: the sources of node j are ``sources[indptr[j]:indptr[j+1]]`` (ascending)."""

    indptr: np.ndarray
    sources: np.ndarray
    chunks: list[tuple[int, int]]
    weights: np.ndarray | None = None  # per in-link weight, aligned with sources (weighted graphs only)
    matrix: sp.csr_matrix | None = None  # A^T as a float64 CSR for fast products; only for graphs up to FAST_PULL_MAX_LINKS

    @property
    def n(self) -> int:
        return len(self.indptr) - 1


def in_links(A: sp.csr_matrix, chunk: int = CHUNK_LINKS, weighted: bool = False) -> InLinks:
    """Build the in-link structure of a binary CSR matrix.

    Up to FAST_PULL_MAX_LINKS links: scipy's transpose, plus A^T as a float64 CSR for fast products.
    Above: a chunked counting sort using one index per link plus O(chunk) temporaries, never a float copy.
    """
    n = A.shape[0]
    if A.nnz <= FAST_PULL_MAX_LINKS:
        # Small enough to afford a float copy: scipy's C transpose; sources come out ascending within each target.
        T = sp.csr_matrix((A.data, A.indices, A.indptr), shape=A.shape).T.tocsr()
        sources = T.indices.astype(np.int32 if n < 2**31 else np.int64, copy=False)
        in_ptr = T.indptr.astype(np.int64, copy=False)
        weights = T.data.astype(np.float64 if A.dtype == np.float64 else np.float32) if weighted else None
        data = T.data.astype(np.float64) if weighted else np.ones(sources.size)
        matrix = sp.csr_matrix((data, sources, in_ptr), shape=(n, n))
        return InLinks(indptr=in_ptr, sources=sources, chunks=_row_chunks(in_ptr, chunk), weights=weights, matrix=matrix)
    out_ptr, targets = A.indptr, A.indices
    in_ptr = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(np.bincount(targets, minlength=n), out=in_ptr[1:])
    sources = np.empty(len(targets), dtype=np.int32 if n < 2**31 else np.int64)
    weights = np.empty(len(targets), dtype=np.float64 if A.dtype == np.float64 else np.float32) if weighted else None
    next_free = in_ptr[:-1].copy()
    for r0, r1 in _row_chunks(out_ptr, chunk):
        e0, e1 = out_ptr[r0], out_ptr[r1]
        if e0 == e1:
            continue
        dst = targets[e0:e1]
        src = np.repeat(np.arange(r0, r1, dtype=sources.dtype), np.diff(out_ptr[r0 : r1 + 1]))
        order = np.argsort(dst, kind="stable")  # stable: sources stay ascending within a target
        d, s = dst[order], src[order]
        starts = np.concatenate(([0], np.flatnonzero(np.diff(d)) + 1))
        sizes = np.diff(np.concatenate((starts, [len(d)])))
        rank = np.arange(len(d)) - np.repeat(starts, sizes)
        sources[next_free[d] + rank] = s
        if weights is not None:
            weights[next_free[d] + rank] = A.data[e0:e1][order]
        next_free[d[starts]] += sizes
    return InLinks(indptr=in_ptr, sources=sources, chunks=_row_chunks(in_ptr, chunk), weights=weights)


_links_cache: dict[str, object] = {}


def cached_in_links(A: sp.csr_matrix) -> InLinks:
    """:func:`in_links` for binary CSR ``A``, reusing the last result when ``A`` is the same matrix.

    The batch job runs about twenty algorithms on one large graph; building the transpose
    once instead of twenty times saves minutes. Only one entry is kept (bounded memory).
    """
    ref = _links_cache.get("indices")
    if ref is not None and ref() is A.indices and _links_cache.get("shape") == (A.shape, A.nnz):
        return _links_cache["links"]  # type: ignore[return-value]
    links = in_links(A)
    _links_cache.update(indices=weakref.ref(A.indices), shape=(A.shape, A.nnz), links=links)
    return links


def pull(links: InLinks, x: np.ndarray) -> np.ndarray:
    """``y[j] = sum of x[i] over the in-links i -> j``, i.e. ``A^T x`` for binary A, chunk by chunk."""
    if links.matrix is not None:
        return links.matrix @ x
    y = np.zeros(links.n)
    ptr = links.indptr
    for r0, r1 in links.chunks:
        e0, e1 = ptr[r0], ptr[r1]
        if e0 == e1:
            continue
        nonempty = np.flatnonzero(ptr[r0 + 1 : r1 + 1] > ptr[r0:r1])
        values = x[links.sources[e0:e1]]
        if links.weights is not None:
            values = values * links.weights[e0:e1]
        y[r0 + nonempty] = np.add.reduceat(values, ptr[r0 + nonempty] - e0)
    return y


def gather_rows(indptr: np.ndarray, indices: np.ndarray, rows: np.ndarray) -> np.ndarray:
    """Concatenate ``indices[indptr[r]:indptr[r+1]]`` for every row r in ``rows`` without a Python loop."""
    rows = np.asarray(rows, dtype=np.int64)
    if rows.size == 0:
        return np.zeros(0, dtype=indices.dtype)
    starts, ends = indptr[rows], indptr[rows + 1]
    lengths = ends - starts
    total = int(lengths.sum())
    if total == 0:
        return np.zeros(0, dtype=indices.dtype)
    offsets = np.repeat(starts - np.concatenate(([0], np.cumsum(lengths)[:-1])), lengths)
    return indices[np.arange(total) + offsets]


def teleport_vector(n: int, teleport: np.ndarray | None) -> np.ndarray:
    """Build the teleport distribution v.

    ``None`` gives the uniform vector ``v_i = 1/n``. Otherwise ``teleport`` must be a
    non-negative length-n vector with positive sum; it is rescaled to sum to 1.
    """
    if n == 0:
        raise ValueError("graph has no nodes")
    if teleport is None:
        return np.full(n, 1.0 / n)
    v = np.asarray(teleport, dtype=np.float64).ravel()
    if v.shape != (n,):
        raise ValueError(f"teleport vector must have length {n}, got {v.shape[0]}")
    if (v < 0).any():
        raise ValueError("teleport vector must be non-negative")
    total = v.sum()
    if total <= 0:
        raise ValueError("teleport vector must have positive mass")
    return v / total


def seed_vector(n: int, seeds: Iterable[int]) -> np.ndarray:
    """Uniform probability vector over a seed set: ``v_i = 1/|S|`` for i in S, else 0."""
    idx = np.unique(np.asarray(list(seeds), dtype=np.int64))
    if idx.size == 0:
        raise ValueError("seed set is empty")
    if idx.min() < 0 or idx.max() >= n:
        raise ValueError(f"seed indices must lie in [0, {n - 1}]")
    v = np.zeros(n)
    v[idx] = 1.0 / idx.size
    return v


def check_mass(scores: np.ndarray, what: str) -> None:
    """Assert that a probability vector sums to 1 within ``MASS_TOLERANCE``."""
    total = float(scores.sum())
    if abs(total - 1.0) > MASS_TOLERANCE:
        raise AssertionError(f"{what} scores sum to {total!r}, expected 1 within {MASS_TOLERANCE}")
