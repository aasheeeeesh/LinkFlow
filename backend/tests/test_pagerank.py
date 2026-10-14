"""PageRank: agreement with networkx, the 1999 paper example, rank sinks, mass conservation."""

from __future__ import annotations

import networkx as nx
import numpy as np
import pytest

from backend.algorithms import (
    DANGLING_STRATEGIES,
    alpha_from_e_norm,
    blend_topics,
    e_norm_from_alpha,
    pagerank,
    pagerank_1999,
    personalized_pagerank,
    strip_dangling,
    topic_vectors,
    trustrank,
)
from backend.tests.graphs import from_edges, random_digraph, to_array

TIGHT = dict(tol=1e-13, max_iter=2000)
NX_TIGHT = dict(tol=1e-14, max_iter=2000)

# 20 random directed graphs with 100..2000 nodes, fixed seeds for reproducibility.
GRAPH_CASES = [(seed, int(n)) for seed, n in enumerate(np.linspace(100, 2000, 20).round())]


@pytest.mark.parametrize("seed,n", GRAPH_CASES)
def test_matches_networkx_for_every_supported_dangling_strategy(seed: int, n: int) -> None:
    rng = np.random.default_rng(seed)
    A, G = random_digraph(rng, n)
    alpha = 0.85
    seeds = rng.choice(n, size=max(3, n // 50), replace=False).tolist()
    personalization = {i: (1.0 if i in set(seeds) else 0.0) for i in range(n)}
    uniform = {i: 1.0 / n for i in range(n)}

    # teleport: dangling mass follows v (networkx dangling=None), uniform v
    ours = pagerank(A, alpha=alpha, dangling="teleport", **TIGHT).scores
    ref = to_array(nx.pagerank(G, alpha=alpha, **NX_TIGHT), n)
    assert np.abs(ours - ref).sum() < 1e-6

    # teleport with a seeded v (personalized): dangling mass returns to the seeds
    ours = personalized_pagerank(A, seeds, alpha=alpha, dangling="teleport", **TIGHT).scores
    ref = to_array(nx.pagerank(G, alpha=alpha, personalization=personalization, **NX_TIGHT), n)
    assert np.abs(ours - ref).sum() < 1e-6

    # uniform: dangling mass spread over all nodes even when v is seeded
    ours = personalized_pagerank(A, seeds, alpha=alpha, dangling="uniform", **TIGHT).scores
    ref = to_array(
        nx.pagerank(G, alpha=alpha, personalization=personalization, dangling=uniform, **NX_TIGHT), n
    )
    assert np.abs(ours - ref).sum() < 1e-6

    # self_loop: networkx has no flag, so give dangling nodes an explicit self-link
    G_loops = G.copy()
    G_loops.add_edges_from((d, d) for d in range(n) if G.out_degree(d) == 0)
    ours = personalized_pagerank(A, seeds, alpha=alpha, dangling="self_loop", **TIGHT).scores
    ref = to_array(nx.pagerank(G_loops, alpha=alpha, personalization=personalization, **NX_TIGHT), n)
    assert np.abs(ours - ref).sum() < 1e-6


def test_paper_figure_3_steady_state() -> None:
    """Page et al. 1999, Figure 3: A->B, A->C, B->C, C->A with no teleport."""
    A, B, C = 0, 1, 2
    graph = from_edges(3, [(A, B), (A, C), (B, C), (C, A)])
    result = pagerank(graph, alpha=1.0, tol=1e-12, max_iter=1000)
    assert result.converged
    np.testing.assert_allclose(result.scores, [0.4, 0.2, 0.4], atol=1e-6)


def test_rank_sink_accumulates_without_teleport_and_not_with_it() -> None:
    """Two nodes linking only to each other, fed by a third node (paper's rank sink)."""
    X, Y, Z = 0, 1, 2
    graph = from_edges(3, [(Z, X), (X, Y), (Y, X)])

    no_teleport = pagerank(graph, alpha=1.0, max_iter=200)
    assert no_teleport.scores[Z] == pytest.approx(0.0, abs=1e-12)
    assert no_teleport.scores[X] + no_teleport.scores[Y] == pytest.approx(1.0, abs=1e-12)
    # The 2-cycle is periodic, so pure power iteration oscillates and never converges.
    assert not no_teleport.converged

    damped = pagerank(graph, alpha=0.85)
    assert damped.converged
    assert (damped.scores > 0).all()
    assert damped.scores[Z] == pytest.approx(0.15 / 3, abs=1e-9)


def _assert_sums_to_one(scores: np.ndarray) -> None:
    assert abs(scores.sum() - 1.0) < 1e-9


@pytest.mark.parametrize("dangling", DANGLING_STRATEGIES)
@pytest.mark.parametrize("alpha", [0.0, 0.5, 0.85, 0.95, 1.0])
def test_every_pagerank_variant_sums_to_one(dangling: str, alpha: float) -> None:
    rng = np.random.default_rng(42)
    A, _ = random_digraph(rng, 300, dangling_share=0.3)
    seeds = [1, 5, 9]
    _assert_sums_to_one(pagerank(A, alpha=alpha, dangling=dangling).scores)
    _assert_sums_to_one(personalized_pagerank(A, seeds, alpha=alpha, dangling=dangling).scores)
    _assert_sums_to_one(trustrank(A, seeds, alpha=alpha, dangling=dangling).scores)


def test_other_variants_sum_to_one() -> None:
    rng = np.random.default_rng(7)
    A, _ = random_digraph(rng, 400, dangling_share=0.3)
    _assert_sums_to_one(pagerank_1999(A).scores)
    vectors = topic_vectors(A, {"a": [1, 2], "b": [3, 4, 5], "c": [100]})
    blended = blend_topics({t: r.scores for t, r in vectors.items()}, {"a": 0.2, "b": 0.5, "c": 0.3})
    _assert_sums_to_one(blended)
    for result in vectors.values():
        _assert_sums_to_one(result.scores)


def test_residuals_recorded_per_iteration() -> None:
    rng = np.random.default_rng(3)
    A, _ = random_digraph(rng, 500)
    result = pagerank(A, tol=1e-10)
    assert result.converged
    assert len(result.residuals) == result.iterations
    assert result.residuals[-1] < 1e-10
    assert all(r >= 0 for r in result.residuals)


def test_teleport_uniform_equals_uniform_dangling_when_v_uniform() -> None:
    rng = np.random.default_rng(11)
    A, _ = random_digraph(rng, 300, dangling_share=0.4)
    a = pagerank(A, dangling="teleport", tol=1e-12).scores
    b = pagerank(A, dangling="uniform", tol=1e-12).scores
    assert np.abs(a - b).sum() < 1e-10


def test_strip_dangling_counts_rounds_on_a_chain() -> None:
    # 0 <-> 1 is a core; 1 -> 2 -> 3 -> 4 is a chain ending in dangling node 4.
    graph = from_edges(5, [(0, 1), (1, 0), (1, 2), (2, 3), (3, 4)])
    core, rounds = strip_dangling(graph)
    assert core.tolist() == [0, 1]
    assert rounds == 3  # 4, then 3, then 2


def test_remove_readd_runs_extra_iterations_equal_to_rounds() -> None:
    graph = from_edges(5, [(0, 1), (1, 0), (1, 2), (2, 3), (3, 4)])
    result = pagerank(graph, dangling="remove_readd")
    rounds = int(result.info["stripping_rounds"])
    assert rounds == 3
    assert result.iterations == int(result.info["core_iterations"]) + rounds
    assert (result.scores > 0).all()  # re-added nodes received rank in the extra passes
    _assert_sums_to_one(result.scores)


def test_remove_readd_on_a_dag_strips_everything() -> None:
    graph = from_edges(4, [(0, 1), (1, 2), (2, 3)])
    result = pagerank(graph, dangling="remove_readd")
    assert result.info["core_nodes"] == 0
    assert result.info["stripping_rounds"] == 4
    _assert_sums_to_one(result.scores)


def test_1999_formulation_maps_to_alpha() -> None:
    rng = np.random.default_rng(5)
    A, _ = random_digraph(rng, 400, dangling_share=0.0)
    A = (A + from_edges(400, [(i, (i + 1) % 400) for i in range(400)])).tocsr()  # ring: no dangling
    assert (np.diff(A.indptr) > 0).all()
    assert alpha_from_e_norm(0.15) == pytest.approx(1 / 1.15)
    assert e_norm_from_alpha(0.85) == pytest.approx(0.15 / 0.85)

    paper = pagerank_1999(A, e_norm=0.15, tol=1e-13, max_iter=2000)
    assert paper.info["c"] == pytest.approx(1 / 1.15, abs=1e-9)
    modern = pagerank(A, alpha=1 / 1.15, tol=1e-13, max_iter=2000)
    assert np.abs(paper.scores - modern.scores).sum() < 1e-9

    paper_085 = pagerank_1999(A, e_norm=e_norm_from_alpha(0.85), tol=1e-13, max_iter=2000)
    modern_085 = pagerank(A, alpha=0.85, tol=1e-13, max_iter=2000)
    assert np.abs(paper_085.scores - modern_085.scores).sum() < 1e-9


def test_alpha_zero_returns_teleport_vector() -> None:
    rng = np.random.default_rng(9)
    A, _ = random_digraph(rng, 100)
    result = personalized_pagerank(A, [2, 4], alpha=0.0)
    expected = np.zeros(100)
    expected[[2, 4]] = 0.5
    np.testing.assert_allclose(result.scores, expected, atol=1e-12)


@pytest.mark.parametrize(
    "kwargs",
    [dict(alpha=1.5), dict(alpha=-0.1), dict(tol=0), dict(max_iter=0), dict(dangling="bogus")],
)
def test_invalid_arguments_raise(kwargs: dict) -> None:
    graph = from_edges(2, [(0, 1)])
    with pytest.raises(ValueError):
        pagerank(graph, **kwargs)


def test_seed_validation() -> None:
    graph = from_edges(3, [(0, 1)])
    with pytest.raises(ValueError):
        personalized_pagerank(graph, [])
    with pytest.raises(ValueError):
        personalized_pagerank(graph, [7])


@pytest.mark.parametrize("seed", range(6))
def test_weighted_pagerank_matches_networkx(seed: int) -> None:
    import scipy.sparse as sp

    from backend.algorithms import weighted_pagerank

    rng = np.random.default_rng(300 + seed)
    A, G = random_digraph(rng, int(rng.integers(100, 800)), dangling_share=0.2)
    weights = rng.integers(1, 50, size=A.nnz).astype(np.float32)
    W = sp.csr_matrix((weights, A.indices, A.indptr), shape=A.shape)
    rows = np.repeat(np.arange(A.shape[0]), np.diff(A.indptr))
    for i, j, w in zip(rows, A.indices, weights):
        G[int(i)][int(j)]["weight"] = float(w)
    ours = weighted_pagerank(W, alpha=0.85, tol=1e-13, max_iter=2000).scores
    ref = to_array(nx.pagerank(G, alpha=0.85, weight="weight", tol=1e-14, max_iter=2000), A.shape[0])
    assert np.abs(ours - ref).sum() < 1e-6
    assert abs(ours.sum() - 1) < 1e-9
    # Unit weights reduce to plain PageRank.
    ones = sp.csr_matrix((np.ones(A.nnz, dtype=np.float32), A.indices, A.indptr), shape=A.shape)
    assert np.abs(weighted_pagerank(ones, tol=1e-12).scores - pagerank(A, tol=1e-12).scores).sum() < 1e-8
