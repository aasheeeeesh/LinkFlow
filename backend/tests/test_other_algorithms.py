"""Spam mass, seed distance, harmonic centrality, topic blending, percentiles, composite."""

from __future__ import annotations

import networkx as nx
import numpy as np
import pytest

from backend.algorithms import (
    blend_topics,
    composite_score,
    harmonic_centrality,
    percentile_rank,
    seed_distance,
    spam_mass,
)
from backend.tests.graphs import from_edges, random_digraph, to_array


def _planted_link_farm(rng: np.random.Generator) -> tuple[np.ndarray, list[int], int, list[int]]:
    """A 200-node good region plus a 100-node farm all pointing at one target.

    Nothing in the good region links into the farm or the target.
    """
    n_good, n_farm = 200, 100
    good, _ = random_digraph(rng, n_good, mean_out=6.0, dangling_share=0.1)
    target = n_good + n_farm
    n = target + 1
    edges = list(zip(*good.nonzero()))
    farm = list(range(n_good, n_good + n_farm))
    edges += [(f, target) for f in farm]
    core = rng.choice(n_good, size=40, replace=False).tolist()
    return from_edges(n, [(int(s), int(t)) for s, t in edges]), core, target, farm


def test_spam_mass_flags_planted_link_farm_target() -> None:
    rng = np.random.default_rng(2006)
    A, core, target, farm = _planted_link_farm(rng)
    result = spam_mass(A, core, alpha=0.85)
    assert result.relative_mass[target] > 0.9
    assert result.flagged[target]
    assert (result.relative_mass <= 1 + 1e-12).all()
    assert abs(result.pagerank.sum() - 1) < 1e-9
    # Good-core members are explained by the core and are not flagged.
    assert result.relative_mass[core].mean() < 0.5
    assert not result.flagged[core].any()


@pytest.mark.parametrize("dangling", ["teleport", "uniform", "self_loop"])
def test_spam_mass_exact_core_contribution_is_bounded_by_pagerank(dangling: str) -> None:
    rng = np.random.default_rng(2006)
    A, core, target, _ = _planted_link_farm(rng)
    n = A.shape[0]
    result = spam_mass(A, core, good_fraction=len(core) / n, dangling=dangling, tol=1e-12, max_iter=1000)
    # gamma = |core|/n is the exact core-jump share of the linear system, so 0 <= M <= p.
    assert (result.absolute_mass >= -1e-10).all()
    assert (result.absolute_mass <= result.pagerank + 1e-10).all()


def test_spam_mass_teleport_matches_linear_system() -> None:
    """The rescaled teleport runs reproduce the paper's linear PageRank system exactly."""
    import scipy.sparse as sp
    from scipy.sparse.linalg import spsolve

    rng = np.random.default_rng(77)
    A, core, _, _ = _planted_link_farm(rng)
    n, alpha = A.shape[0], 0.85
    out = np.asarray(A.sum(axis=1)).ravel()
    inv = np.divide(1.0, out, out=np.zeros(n), where=out > 0)
    MT = (sp.diags(inv) @ A).T.tocsc()
    system = (sp.identity(n, format="csc") - alpha * MT)
    u = np.full(n, 1.0 / n)
    w = np.zeros(n)
    w[core] = 1.0 / len(core)
    p_lin = (1 - alpha) * spsolve(system, u)
    p_plus_lin = (1 - alpha) * spsolve(system, w)
    expected = 1 - p_plus_lin / p_lin

    result = spam_mass(A, core, alpha=alpha, good_fraction=1.0, tol=1e-13, max_iter=2000)
    np.testing.assert_allclose(result.relative_mass, expected, atol=1e-8)


def test_spam_mass_rejects_remove_readd() -> None:
    A = from_edges(3, [(0, 1), (1, 2)])
    with pytest.raises(ValueError):
        spam_mass(A, [0], dangling="remove_readd")  # type: ignore[arg-type]


def test_seed_distance_bfs() -> None:
    # 0 -> 1 -> 2 -> 3, 4 isolated, 5 -> 0 (not reachable from seed 0)
    A = from_edges(6, [(0, 1), (1, 2), (2, 3), (5, 0)])
    result = seed_distance(A, [0], beta=0.5)
    assert result.distances.tolist() == [0, 1, 2, 3, -1, -1]
    np.testing.assert_allclose(result.scores, [1, 0.5, 0.25, 0.125, 0, 0])
    assert result.max_distance == 3


def test_seed_distance_uses_nearest_seed() -> None:
    A = from_edges(5, [(0, 1), (1, 2), (2, 3), (4, 3)])
    result = seed_distance(A, [0, 4], beta=0.5)
    assert result.distances.tolist() == [0, 1, 2, 1, 0]


@pytest.mark.parametrize("seed", range(5))
def test_harmonic_matches_networkx(seed: int) -> None:
    rng = np.random.default_rng(500 + seed)
    n = int(rng.integers(30, 250))
    A, G = random_digraph(rng, n, mean_out=3.0)
    ours = harmonic_centrality(A, chunk_size=37)
    ref = to_array(nx.harmonic_centrality(G), n)
    np.testing.assert_allclose(ours, ref, atol=1e-9)


def test_harmonic_refuses_large_graphs() -> None:
    A = from_edges(10, [(0, 1)])
    with pytest.raises(ValueError):
        harmonic_centrality(A, max_nodes=5)


def test_topic_blend_is_convex_combination() -> None:
    vectors = {"science": np.array([0.5, 0.5, 0.0]), "sport": np.array([0.0, 0.0, 1.0])}
    blended = blend_topics(vectors, {"science": 3, "sport": 1})  # normalised to 0.75 / 0.25
    np.testing.assert_allclose(blended, [0.375, 0.375, 0.25])
    with pytest.raises(ValueError):
        blend_topics(vectors, {"science": 0, "sport": 0})
    with pytest.raises(ValueError):
        blend_topics(vectors, {"cooking": 1})


def test_percentile_rank_ties_and_range() -> None:
    pct = percentile_rank(np.array([0.1, 0.4, 0.4, 0.9, 0.0]))
    np.testing.assert_allclose(pct, [25.0, 62.5, 62.5, 100.0, 0.0])  # the tied pair shares the mid-rank
    assert percentile_rank(np.array([3.0])).tolist() == [100.0]


def test_composite_keeps_breakdown_and_normalises_weights() -> None:
    result = composite_score({"pagerank": 90.0, "trustrank": 40.0, "seed": 10.0}, {"pagerank": 2, "trustrank": 2, "seed": 0})
    assert result.composite == pytest.approx(65.0)
    assert [p.algorithm for p in result.parts] == ["pagerank", "trustrank", "seed"]
    assert sum(p.weight for p in result.parts) == pytest.approx(1.0)
    assert result.parts[2].contribution == 0.0


def test_midrank_sql_matches_python() -> None:
    import duckdb

    from backend.algorithms.scoring import midrank_sql

    values = np.array([3.0, 1.0, 1.0, 2.0, 5.0, 1.0, 5.0])
    con = duckdb.connect()
    con.register("t", {"i": np.arange(values.size), "v": values, "g": np.zeros(values.size, dtype=np.int64)})
    for partition in ("", "g"):
        rows = con.execute(f"SELECT i, {midrank_sql('v', partition)} FROM t ORDER BY i").fetchall()
        np.testing.assert_allclose([p for _, p in rows], percentile_rank(values))
    assert con.execute(f"SELECT {midrank_sql('v')} FROM (SELECT 1.0 AS v)").fetchone()[0] == 100.0
