"""HITS: agreement with networkx and Kleinberg base-set construction."""

from __future__ import annotations

import networkx as nx
import numpy as np
import pytest

from backend.algorithms import base_subgraph, build_base_set, hits
from backend.tests.graphs import from_edges, random_digraph, to_array


@pytest.mark.parametrize("seed", range(10))
def test_matches_networkx(seed: int) -> None:
    rng = np.random.default_rng(1000 + seed)
    n = int(rng.integers(60, 400))
    A, G = random_digraph(rng, n, mean_out=6.0, dangling_share=0.1)
    ours = hits(A, tol=1e-14, max_iter=20000)
    assert ours.converged
    ref_h, ref_a = nx.hits(G, max_iter=20000, tol=1e-14)
    # networkx normalises to sum 1; ours are L2-normalised. Compare directions.
    hubs = ours.hubs / ours.hubs.sum()
    auth = ours.authorities / ours.authorities.sum()
    assert np.abs(hubs - to_array(ref_h, n)).max() < 1e-6
    assert np.abs(auth - to_array(ref_a, n)).max() < 1e-6


def test_l2_normalised_and_residuals() -> None:
    rng = np.random.default_rng(1)
    A, _ = random_digraph(rng, 200)
    result = hits(A)
    assert np.linalg.norm(result.hubs) == pytest.approx(1.0)
    assert np.linalg.norm(result.authorities) == pytest.approx(1.0)
    assert len(result.residuals) == result.iterations


def test_star_authority() -> None:
    # Nodes 1..4 all point at 0: 0 is the only authority, 1..4 are equal hubs.
    graph = from_edges(5, [(i, 0) for i in range(1, 5)])
    result = hits(graph)
    assert result.authorities.argmax() == 0
    assert result.authorities[1:].max() == pytest.approx(0.0)
    np.testing.assert_allclose(result.hubs[1:], 0.5)


def test_base_set_caps_in_neighbours_per_root() -> None:
    # 100 nodes point at root 0; root 0 points at 200 and 201.
    edges = [(i, 0) for i in range(1, 101)] + [(0, 200), (0, 201)]
    graph = from_edges(202, edges)
    priority = np.arange(202, dtype=float)  # higher index = higher priority
    base = build_base_set(graph, [0], max_in_per_root=50, in_priority=priority)
    expected = {0, 200, 201} | set(range(51, 101))
    assert set(base.tolist()) == expected

    base_default = build_base_set(graph, [0], max_in_per_root=50)
    assert set(base_default.tolist()) == {0, 200, 201} | set(range(1, 51))


def test_base_subgraph_drops_self_links() -> None:
    graph = from_edges(3, [(0, 0), (0, 1), (1, 2)])
    sub = base_subgraph(graph, np.array([0, 1]))
    assert sub.shape == (2, 2)
    assert sub.diagonal().sum() == 0
    assert sub[0, 1] == 1
