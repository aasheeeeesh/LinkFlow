"""Read-only access to the Phase 2 analysis database (subgraph, scores, runs)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import duckdb

from .db import DataNotLoaded

ANALYSIS_HINT = "Run: python -m backend.jobs.build_subgraph and python -m backend.jobs.compute_all"
EXPLAIN_LIMIT = 25


class Analysis:
    """Read-only access to data/analysis.duckdb, one short-lived connection per query."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._meta: dict[str, Any] | None = None

    def _query(self, sql: str, params: list[Any] | None = None, one: bool = False) -> Any:
        """Run one read-only query on a short-lived connection.

        The connection is closed right away so the batch jobs, which write this database, are
        never blocked for longer than a single request.
        """
        if not self.path.exists():
            raise DataNotLoaded(f"The subgraph analysis has not been computed yet. {ANALYSIS_HINT}")
        try:
            con = duckdb.connect(str(self.path), read_only=True)
        except duckdb.IOException as exc:
            raise DataNotLoaded(
                "The analysis database is being written by a running computation. Try again when it has finished."
            ) from exc
        try:
            cur = con.execute(sql, params or [])
            return cur.fetchone() if one else cur.fetchall()
        finally:
            con.close()

    def meta(self) -> dict[str, Any]:
        """Subgraph statistics and the list of stored variants."""
        if self._meta is None:
            try:
                stats = dict(self._query("SELECT key, value FROM subgraph_meta"))
                variants = self._query("SELECT params_hash, algorithm, label, params FROM variants ORDER BY algorithm, label")
            except duckdb.CatalogException as exc:
                raise DataNotLoaded(f"The subgraph analysis is incomplete. {ANALYSIS_HINT}") from exc
            if not variants:
                raise DataNotLoaded(f"No algorithm results are stored yet. {ANALYSIS_HINT}")
            self._meta = {
                "release": stats.get("release"),
                "top": int(stats.get("top", 0)),
                "nodes": int(stats.get("nodes", 0)),
                "edges": int(stats.get("edges", 0)),
                "variants": [
                    {"params_hash": h, "algorithm": a, "label": label, "params": json.loads(p)}
                    for h, a, label, p in variants
                ],
            }
        return self._meta

    def variant(self, params_hash: str) -> dict[str, Any] | None:
        return next((v for v in self.meta()["variants"] if v["params_hash"] == params_hash), None)

    def default_pagerank(self) -> dict[str, Any]:
        """The reference PageRank variant: alpha = 0.85, dangling = teleport."""
        for v in self.meta()["variants"]:
            if v["algorithm"] == "pagerank" and v["params"].get("alpha") == 0.85 and v["params"].get("dangling") == "teleport":
                return v
        raise DataNotLoaded(f"The reference PageRank run is missing. {ANALYSIS_HINT}")

    def node(self, domain: str) -> tuple | None:
        return self._query(
            "SELECT node, domain_key, domain, hc_rank, out_degree, in_degree FROM subgraph_nodes WHERE domain = ?",
            [domain],
            one=True,
        )

    def scores(self, domain_key: str) -> list[tuple]:
        return self._query("SELECT params_hash, score, percentile, rank FROM scores WHERE domain_key = ?", [domain_key])

    def explain(self, node: int, params_hash: str, limit: int = EXPLAIN_LIMIT) -> dict[str, Any]:
        """In-link contributions to one node's PageRank: share(v) = alpha * p(v) / out(v)."""
        contributors = self._query(
            """
            SELECT n.domain, n.node, s.score, n.out_degree, s.score / n.out_degree AS share_per_alpha
            FROM subgraph_edges e
            JOIN subgraph_nodes n ON n.node = e.src
            JOIN scores s ON s.domain_key = n.domain_key AND s.params_hash = ?
            WHERE e.dst = ?
            ORDER BY share_per_alpha DESC, n.domain
            """,
            [params_hash, node],
        )
        dangling_mass = self._query(
            """
            SELECT coalesce(sum(s.score), 0) FROM scores s JOIN subgraph_nodes n USING (domain_key)
            WHERE s.params_hash = ? AND n.out_degree = 0
            """,
            [params_hash],
            one=True,
        )[0]
        top = contributors[:limit]
        ids = [node] + [c[1] for c in top]
        placeholders = ", ".join("?" for _ in ids)
        among = self._query(
            f"SELECT src, dst FROM subgraph_edges WHERE dst IN ({placeholders}) AND src IN ({placeholders})",
            ids + ids,
        )
        return {
            "contributors": contributors,
            "top": top,
            "edges": among,
            "dangling_mass": float(dangling_mass),
        }

    def convergence(self) -> list[tuple]:
        return self._query(
            """
            SELECT r.params_hash, r.algorithm, v.label, r.iterations, r.residuals, r.seconds, r.converged, r.info
            FROM runs r JOIN variants v USING (params_hash)
            ORDER BY v.algorithm, v.label, r.algorithm
            """
        )

    def disagreements(self, limit: int) -> list[tuple]:
        return self._query(
            """
            SELECT domain, pagerank_pct, trustrank_pct, seed_distance_pct, spread
            FROM disagreements ORDER BY spread DESC LIMIT ?
            """,
            [limit],
        )
