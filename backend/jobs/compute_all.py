"""Run every Phase 2 algorithm on the top-N subgraph and store the results in DuckDB.

    python -m backend.jobs.compute_all [--top 1000000] [--max-iter 1000] [--tol 1e-8]

Runs (each stored under its own params_hash):
  pagerank          alpha in {0.50, 0.70, 0.85, 0.95}, dangling = teleport
  pagerank          alpha = 0.85 with dangling = uniform, self_loop, remove_readd
  trustrank         alpha = 0.85, default trusted seed list
  spam_mass         alpha = 0.85, good core = trusted seeds, gamma = 1 (score = relative mass)
  seed_distance     beta = 0.5 from the trusted seeds
  topic:<name>      personalized PageRank per topic seed list (8 topics), alpha = 0.85

Tables in data/analysis.duckdb:
  variants(params_hash, algorithm, label, params JSON, ...)
  scores(domain_key, algorithm, params_hash, score, percentile, rank)
  runs(params_hash, algorithm, iterations, residuals JSON, seconds, converged, info JSON)
  disagreements(domain_key, domain, pagerank_pct, trustrank_pct, seed_distance_pct, spread)

Each run commits in one transaction, so the job is resumable: finished runs are skipped.
The batch uses max_iter = 1000 (not the interactive default of 200) so that alpha = 0.95,
which needs roughly 360 iterations to reach tol = 1e-8, can converge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import scipy.sparse as sp
from scipy.stats import rankdata

from backend import config
from backend.algorithms import (
    pagerank, percentile_rank, personalized_pagerank, seed_distance, spam_mass, trustrank, weighted_pagerank,
)
from backend.algorithms.common import IterativeResult
from backend.seeds import topic_seeds, trusted_seeds

from .build_host_weights import weighted_path
from .build_subgraph import subgraph_path
from .fetch import keep_system_awake, peak_rss_bytes
from .load_ranks import connect_writable

log = logging.getLogger("compute_all")

SCHEMA = """
CREATE TABLE IF NOT EXISTS variants (
    params_hash VARCHAR PRIMARY KEY,
    algorithm   VARCHAR NOT NULL,
    label       VARCHAR NOT NULL,
    params      VARCHAR NOT NULL,   -- JSON
    release     VARCHAR NOT NULL,
    subgraph    VARCHAR NOT NULL,
    created_at  TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS scores (
    domain_key  VARCHAR NOT NULL,
    algorithm   VARCHAR NOT NULL,
    params_hash VARCHAR NOT NULL,
    score       DOUBLE  NOT NULL,
    percentile  DOUBLE  NOT NULL,   -- mid-rank percentile within the subgraph (ties share the average)
    rank        INTEGER NOT NULL    -- 1 = highest score; ties share the best rank
);
CREATE TABLE IF NOT EXISTS runs (
    params_hash VARCHAR NOT NULL,
    algorithm   VARCHAR NOT NULL,   -- e.g. "pagerank", "spam_mass (core PageRank)"
    iterations  INTEGER NOT NULL,
    residuals   VARCHAR NOT NULL,   -- JSON list, one L1 residual per iteration
    seconds     DOUBLE  NOT NULL,
    converged   BOOLEAN NOT NULL,
    info        VARCHAR NOT NULL    -- JSON
);
"""


@dataclass
class Variant:
    """One stored computation: an algorithm plus its parameters."""

    algorithm: str
    label: str
    params: dict[str, object]
    compute: Callable[[sp.csr_matrix], tuple[np.ndarray, list[tuple[str, IterativeResult, float]]]] = field(repr=False)

    def params_hash(self, release: str, top: int) -> str:
        blob = json.dumps({"algorithm": self.algorithm, **self.params, "release": release, "top": top}, sort_keys=True)
        return hashlib.sha1(blob.encode()).hexdigest()[:12]


def _timed(name: str, fn: Callable[[], IterativeResult]) -> tuple[IterativeResult, tuple[str, IterativeResult, float]]:
    t0 = time.perf_counter()
    result = fn()
    return result, (name, result, time.perf_counter() - t0)


def plan(
    seed_nodes: list[int], topic_nodes: dict[str, list[int]], tol: float, max_iter: int, weighted: Path | None = None
) -> list[Variant]:
    """The fixed list of Phase 2 computations."""
    common = {"tol": tol, "max_iter": max_iter}
    variants: list[Variant] = []

    def pr(alpha: float, dangling: str) -> Variant:
        def run(A: sp.csr_matrix) -> tuple[np.ndarray, list[tuple[str, IterativeResult, float]]]:
            result, rec = _timed("pagerank", lambda: pagerank(A, alpha=alpha, dangling=dangling, **common))
            return result.scores, [rec]

        return Variant("pagerank", f"PageRank α={alpha:.2f}, dangling={dangling}", {"alpha": alpha, "dangling": dangling, **common}, run)

    for alpha in (0.50, 0.70, 0.85, 0.95):
        variants.append(pr(alpha, "teleport"))
    for dangling in ("uniform", "self_loop", "remove_readd"):
        variants.append(pr(0.85, dangling))

    seed_desc = f"default trusted list ({len(seed_nodes)} seeds)"

    def trust(A: sp.csr_matrix) -> tuple[np.ndarray, list[tuple[str, IterativeResult, float]]]:
        result, rec = _timed("trustrank", lambda: trustrank(A, seed_nodes, alpha=0.85, **common))
        return result.scores, [rec]

    variants.append(Variant("trustrank", "TrustRank α=0.85", {"alpha": 0.85, "seeds": seed_desc, **common}, trust))

    def mass(A: sp.csr_matrix) -> tuple[np.ndarray, list[tuple[str, IterativeResult, float]]]:
        t0 = time.perf_counter()
        result = spam_mass(A, seed_nodes, alpha=0.85, good_fraction=1.0, dangling="teleport", **common)
        seconds = time.perf_counter() - t0
        return result.relative_mass, [
            ("spam_mass (global PageRank)", result.global_run, seconds / 2),
            ("spam_mass (core PageRank)", result.core_run, seconds / 2),
        ]

    variants.append(
        Variant(
            "spam_mass",
            "Spam mass (relative), α=0.85, γ=1",
            {"alpha": 0.85, "good_core": seed_desc, "good_fraction": 1.0, "dangling": "teleport", **common},
            mass,
        )
    )

    def distance(A: sp.csr_matrix) -> tuple[np.ndarray, list[tuple[str, IterativeResult, float]]]:
        t0 = time.perf_counter()
        result = seed_distance(A, seed_nodes, beta=0.5)
        seconds = time.perf_counter() - t0
        record = IterativeResult(scores=result.scores, iterations=result.max_distance, residuals=[], converged=True,
                                 info={"max_distance": float(result.max_distance),
                                       "unreachable": float((result.distances < 0).sum())})
        return result.scores, [("seed_distance", record, seconds)]

    variants.append(Variant("seed_distance", "Seed distance β=0.5", {"beta": 0.5, "seeds": seed_desc}, distance))

    for topic, nodes in topic_nodes.items():
        def topical(A: sp.csr_matrix, nodes: list[int] = nodes, topic: str = topic) -> tuple[np.ndarray, list[tuple[str, IterativeResult, float]]]:
            result, rec = _timed(f"topic:{topic}", lambda: personalized_pagerank(A, nodes, alpha=0.85, **common))
            return result.scores, [rec]

        variants.append(
            Variant(f"topic:{topic}", f"Topic-sensitive PageRank: {topic}",
                    {"alpha": 0.85, "seeds": f"{topic}.txt ({len(nodes)} seeds)", **common}, topical)
        )
    if weighted is not None and weighted.exists():
        def wpr(_A: sp.csr_matrix) -> tuple[np.ndarray, list[tuple[str, IterativeResult, float]]]:
            W = sp.load_npz(weighted).tocsr()
            result, rec = _timed("weighted_pagerank", lambda: weighted_pagerank(W, alpha=0.85, **common))
            return result.scores, [rec]

        variants.append(Variant("weighted_pagerank", "Weighted PageRank α=0.85 (host-level link counts)",
                                {"alpha": 0.85, "dangling": "teleport", "weights": "host-level links", **common}, wpr))
    return variants


def resolve_seeds(con: duckdb.DuckDBPyConnection, domains: list[str], what: str) -> list[int]:
    """Node ids of seed domains present in the subgraph (logs the missing ones)."""
    rows = dict(con.execute(
        f"SELECT domain, node FROM subgraph_nodes WHERE domain IN ({', '.join('?' for _ in domains)})", domains
    ).fetchall())
    missing = [d for d in domains if d not in rows]
    if missing:
        log.warning("%s: %d seeds not in the subgraph: %s", what, len(missing), ", ".join(missing[:10]))
    return sorted(rows[d] for d in domains if d in rows)


def store(con: duckdb.DuckDBPyConnection, variant: Variant, h: str, scores: np.ndarray,
          records: list[tuple[str, IterativeResult, float]], release: str, top: int) -> None:
    """Write one variant's scores, percentiles, ranks and convergence records atomically."""
    n = scores.size
    data = {
        "node": np.arange(n, dtype=np.int32),
        "score": scores.astype(np.float64),
        "percentile": percentile_rank(scores),
        "rank": rankdata(-scores, method="min").astype(np.int32),
    }
    con.execute("BEGIN")
    con.execute("DELETE FROM scores WHERE params_hash = ?", [h])
    con.execute("DELETE FROM runs WHERE params_hash = ?", [h])
    con.register("new_scores", data)
    con.execute(
        """
        INSERT INTO scores
        SELECT n.domain_key, ?, ?, s.score, s.percentile, s.rank
        FROM new_scores s JOIN subgraph_nodes n USING (node)
        """,
        [variant.algorithm, h],
    )
    con.unregister("new_scores")
    for name, result, seconds in records:
        con.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)",
            [h, name, result.iterations, json.dumps(result.residuals), seconds, result.converged, json.dumps(result.info)],
        )
    con.execute(
        "INSERT OR REPLACE INTO variants VALUES (?, ?, ?, ?, ?, ?, ?)",
        [h, variant.algorithm, variant.label, json.dumps(variant.params), release, f"top{top}", datetime.now(timezone.utc)],
    )
    con.execute("COMMIT")


def finish(con: duckdb.DuckDBPyConnection, release: str, top: int, hashes: dict[str, str]) -> None:
    """Sort scores by domain for fast lookups and precompute the disagreements table."""
    con.execute("CREATE OR REPLACE TABLE scores AS SELECT * FROM scores ORDER BY domain_key, params_hash")
    con.execute(
        """
        CREATE OR REPLACE TABLE disagreements AS
        WITH p AS (
            SELECT domain_key,
                   max(percentile) FILTER (WHERE params_hash = ?) AS pagerank_pct,
                   max(percentile) FILTER (WHERE params_hash = ?) AS trustrank_pct,
                   max(percentile) FILTER (WHERE params_hash = ?) AS seed_distance_pct
            FROM scores WHERE params_hash IN (?, ?, ?)
            GROUP BY domain_key
        )
        SELECT p.domain_key, n.domain, pagerank_pct, trustrank_pct, seed_distance_pct,
               greatest(pagerank_pct, trustrank_pct, seed_distance_pct)
                 - least(pagerank_pct, trustrank_pct, seed_distance_pct) AS spread
        FROM p JOIN subgraph_nodes n USING (domain_key)
        ORDER BY spread DESC, n.hc_rank
        LIMIT 10000
        """,
        [hashes["pagerank"], hashes["trustrank"], hashes["seed_distance"]] * 2,
    )
    con.execute("CHECKPOINT")


def compute(top: int, release: str, tol: float, max_iter: int, memory_limit: str) -> None:
    """Run (or resume) every variant on the stored top-``top`` subgraph."""
    started = time.perf_counter()
    t0 = time.perf_counter()
    A = sp.load_npz(subgraph_path(top)).tocsr()
    log.info("loaded subgraph: %s nodes, %s links in %.0fs (peak RSS %.1f GB)",
             f"{A.shape[0]:,}", f"{A.nnz:,}", time.perf_counter() - t0, peak_rss_bytes() / 1e9)

    con = connect_writable(config.ANALYSIS_DB_PATH, wait_seconds=300)
    con.execute(f"SET memory_limit = '{memory_limit}'")
    con.execute(SCHEMA)
    seeds = resolve_seeds(con, trusted_seeds(), "trusted")
    topics = {t: resolve_seeds(con, d, f"topic {t}") for t, d in topic_seeds().items()}
    variants = plan(seeds, topics, tol, max_iter, weighted=weighted_path(top))
    done = {r[0] for r in con.execute("SELECT params_hash FROM variants").fetchall()}

    hashes: dict[str, str] = {}
    for i, variant in enumerate(variants, 1):
        h = variant.params_hash(release, top)
        if variant.algorithm in ("trustrank", "seed_distance") or (
            variant.algorithm == "pagerank" and variant.params["alpha"] == 0.85 and variant.params["dangling"] == "teleport"
        ):
            hashes[variant.algorithm] = h
        if h in done:
            log.info("[%d/%d] %s: already stored (%s), skipping", i, len(variants), variant.label, h)
            continue
        t0 = time.perf_counter()
        scores, records = variant.compute(A)
        store(con, variant, h, scores, records, release, top)
        iters = ", ".join(f"{name}: {rec.iterations} it{' (not converged)' if not rec.converged else ''}" for name, rec, _ in records)
        log.info("[%d/%d] %s done in %.0fs (%s); peak RSS %.1f GB",
                 i, len(variants), variant.label, time.perf_counter() - t0, iters, peak_rss_bytes() / 1e9)

    finish(con, release, top, hashes)
    con.close()
    log.info("all %d variants stored in %.0f min; peak RSS %.1f GB",
             len(variants), (time.perf_counter() - started) / 60, peak_rss_bytes() / 1e9)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top", type=int, default=1_000_000)
    parser.add_argument("--release", default=config.RELEASE)
    parser.add_argument("--tol", type=float, default=1e-8)
    parser.add_argument("--max-iter", type=int, default=1000)
    parser.add_argument("--memory-limit", default=config.DUCKDB_MEMORY_LIMIT)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    keep_system_awake()
    compute(args.top, args.release, args.tol, args.max_iter, args.memory_limit)


if __name__ == "__main__":
    main()
