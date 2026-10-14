"""Read-only DuckDB access for the API."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import duckdb

RANK_COLUMNS = (
    "domain, domain_key, release, n_hosts, harmonic_centrality, hc_rank, hc_percentile, "
    "pagerank, pr_rank, pr_percentile"
)


LOAD_HINT = "Run: python -m backend.jobs.load_ranks"


class DataNotLoaded(RuntimeError):
    """The database is missing, has no rank data yet, or is locked by a running load job."""


@dataclass(frozen=True)
class ReleaseInfo:
    release: str
    source_url: str
    domains: int
    loaded_at: str


class Database:
    """Lazily opened read-only connection; each call uses its own cursor (thread-safe)."""

    def __init__(self, path: Path, preferred_release: str) -> None:
        self.path = path
        self.preferred_release = preferred_release
        self._con: duckdb.DuckDBPyConnection | None = None
        self._lock = threading.Lock()
        self._release: ReleaseInfo | None = None

    def cursor(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            if self._con is None:
                if not self.path.exists():
                    raise DataNotLoaded(f"No database at {self.path}. {LOAD_HINT}")
                try:
                    self._con = duckdb.connect(str(self.path), read_only=True)
                except duckdb.IOException as exc:
                    raise DataNotLoaded(
                        "The database is locked by another process, probably a running load job. "
                        "Try again when it has finished."
                    ) from exc
            return self._con.cursor()

    def release(self) -> ReleaseInfo:
        """The release served by the API: the configured one if loaded, else the newest."""
        if self._release is None:
            try:
                row = self.cursor().execute(
                    """
                    SELECT release, source_url, domains, CAST(loaded_at AS VARCHAR)
                    FROM releases
                    ORDER BY release = ? DESC, loaded_at DESC
                    LIMIT 1
                    """,
                    [self.preferred_release],
                ).fetchone()
            except duckdb.CatalogException as exc:
                raise DataNotLoaded(f"The rank tables are missing. {LOAD_HINT}") from exc
            if row is None:
                raise DataNotLoaded(f"No release has been loaded yet. {LOAD_HINT}")
            self._release = ReleaseInfo(*row)
        return self._release

    def lookup(self, domains: list[str]) -> dict[str, tuple]:
        """Rank rows keyed by domain for the served release (missing domains are absent)."""
        if not domains:
            return {}
        release = self.release().release
        placeholders = ", ".join("?" for _ in domains)
        rows = self.cursor().execute(
            f"SELECT {RANK_COLUMNS} FROM domain_ranks WHERE release = ? AND domain IN ({placeholders})",
            [release, *domains],
        ).fetchall()
        return {row[0]: row for row in rows}

    def top(self, metric: str, limit: int) -> list[tuple]:
        """Top domains of the served release by ``pr_rank`` or ``hc_rank``."""
        rank_col = {"pagerank": "pr_rank", "harmonic": "hc_rank"}[metric]
        return self.cursor().execute(
            f"SELECT {RANK_COLUMNS} FROM top_domains WHERE release = ? AND {rank_col} <= ? ORDER BY {rank_col}",
            [self.release().release, limit],
        ).fetchall()
