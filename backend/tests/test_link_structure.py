"""Memory-lean link helpers used on the 1M-domain subgraph, checked against plain scipy."""

from __future__ import annotations

import numpy as np
import pytest
import scipy.sparse as sp

from backend.algorithms.common import binary_csr, cached_in_links, gather_rows, in_links, pull
from backend.algorithms.pagerank import induced_subgraph, pagerank
from backend.tests.graphs import from_edges, random_digraph


@pytest.mark.parametrize("chunk", [1, 3, 7, 1000])
@pytest.mark.parametrize("seed", range(4))
def test_in_links_and_pull_match_scipy_transpose(chunk: int, seed: int) -> None:
    rng = np.random.default_rng(seed)
    A, _ = random_digraph(rng, 60, mean_out=3.0, dangling_share=0.3)
    B = binary_csr(A)
    links = in_links(B, chunk=chunk)
    T = B.T.tocsr().astype(np.float64)
    T.sort_indices()
    np.testing.assert_array_equal(links.indptr, T.indptr)
    np.testing.assert_array_equal(links.sources, T.indices)  # ascending sources per target
    x = rng.random(60)
    np.testing.assert_allclose(pull(links, x), T @ x, rtol=1e-12, atol=1e-15)


def test_pull_with_empty_leading_and_trailing_rows() -> None:
    # Nodes 0 and 4 have no in-links; node 2 has three.
    A = from_edges(5, [(0, 2), (1, 2), (3, 2), (2, 1), (4, 3)])
    links = in_links(binary_csr(A), chunk=2)
    y = pull(links, np.array([1.0, 10.0, 100.0, 1000.0, 10000.0]))
    np.testing.assert_allclose(y, [0, 100, 1011, 10000, 0])


def test_gather_rows() -> None:
    indptr = np.array([0, 2, 2, 5])
    indices = np.array([7, 8, 1, 2, 3])
    assert gather_rows(indptr, indices, np.array([2, 0])).tolist() == [1, 2, 3, 7, 8]
    assert gather_rows(indptr, indices, np.array([1])).tolist() == []
    assert gather_rows(indptr, indices, np.array([], dtype=int)).tolist() == []


@pytest.mark.parametrize("chunk", [1, 4, 100])
def test_induced_subgraph_matches_scipy_indexing(chunk: int) -> None:
    rng = np.random.default_rng(3)
    A, _ = random_digraph(rng, 80, mean_out=4.0)
    nodes = np.sort(rng.choice(80, size=37, replace=False))
    ours = induced_subgraph(A, nodes, chunk=chunk)
    ref = binary_csr(A)[nodes][:, nodes].tocsr()
    ref.sort_indices()
    assert (ours != ref).nnz == 0
    assert ours.has_canonical_format


def test_binary_csr_does_not_copy_an_already_binary_matrix() -> None:
    A = binary_csr(from_edges(4, [(0, 1), (1, 2)]))
    assert binary_csr(A) is A


def test_cache_is_not_fooled_by_a_different_matrix_of_the_same_shape() -> None:
    A = binary_csr(from_edges(3, [(0, 1)]))
    B = binary_csr(from_edges(3, [(1, 2)]))
    assert cached_in_links(A).indptr.tolist() == [0, 0, 1, 1]
    assert cached_in_links(B).indptr.tolist() == [0, 0, 0, 1]
    assert cached_in_links(A) is cached_in_links(A)


def test_pagerank_accepts_a_large_style_int8_matrix() -> None:
    """The subgraph job writes int8 data and int32 indices; pagerank must take it as is."""
    rng = np.random.default_rng(9)
    A, _ = random_digraph(rng, 200)
    lean = sp.csr_matrix((np.ones(A.nnz, dtype=np.int8), A.indices.astype(np.int32), A.indptr), shape=A.shape)
    lean.sort_indices()
    np.testing.assert_allclose(pagerank(lean, tol=1e-12).scores, pagerank(A, tol=1e-12).scores, atol=1e-12)
