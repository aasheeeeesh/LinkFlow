"""Recompute every stored percentile with the mid-rank definition, without rerunning algorithms.

    python -m backend.tools.recompute_percentiles

Rewrites ``domain_ranks.hc_percentile`` / ``pr_percentile`` (and ``top_domains``) in the rank database
and ``scores.percentile`` (and ``disagreements``) in the analysis database. Stop the API first:
both databases are rewritten in place.
"""

from __future__ import annotations

import logging
import time

from backend import config
from backend.algorithms.scoring import midrank_sql
from backend.jobs.compute_all import finish
from backend.jobs.fetch import keep_system_awake
from backend.jobs.load_ranks import PERCENTILE_METHOD_SCHEMA, TOP_N, connect_writable

log = logging.getLogger("recompute_percentiles")


def recompute_ranks() -> None:
    """Shift tied rows in place: mid-rank = old "strictly lower" percentile + 100 * (ties - 1) / 2 / (n - 1).

    The stored percentiles came from ``percent_rank()`` (ties at their lowest position), so only rows whose
    value is shared need changing. No re-sort of the 118M-row table: per-value tie counts come from one
    aggregate and only the tied rows are updated. Temporary disk use is capped at 20 GiB.
    """
    con = connect_writable(config.DB_PATH)
    con.execute(f"SET memory_limit = '{config.DUCKDB_MEMORY_LIMIT}'")
    con.execute(f"SET temp_directory = '{config.DUCKDB_TEMP_DIR.as_posix()}'")
    con.execute("SET max_temp_directory_size = '20GiB'")
    con.execute("SET preserve_insertion_order = false")
    con.execute(PERCENTILE_METHOD_SCHEMA)
    done = set(con.execute("SELECT release, col FROM percentile_method WHERE method = 'midrank'").fetchall())
    for release, n in con.execute("SELECT release, count(*) FROM domain_ranks GROUP BY release").fetchall():
        for value_col, pct_col in (("pagerank", "pr_percentile"), ("harmonic_centrality", "hc_percentile")):
            if (release, pct_col) in done:  # a shift must never be applied twice
                log.info("%s %s: already mid-rank, skipping", release, pct_col)
                continue
            t0 = time.perf_counter()
            con.execute("BEGIN")
            con.execute(
                f"""
                CREATE OR REPLACE TEMP TABLE ties AS
                SELECT {value_col} AS v, count(*) AS c FROM domain_ranks
                WHERE release = ? GROUP BY {value_col} HAVING count(*) > 1
                """,
                [release],
            )
            groups, rows = con.execute("SELECT count(*), coalesce(sum(c), 0) FROM ties").fetchone()
            con.execute(
                f"""
                UPDATE domain_ranks SET {pct_col} = {pct_col} + 100.0 * (ties.c - 1) / 2.0 / ({n} - 1)
                FROM ties WHERE domain_ranks.release = ? AND domain_ranks.{value_col} = ties.v
                """,
                [release],
            )
            con.execute("INSERT INTO percentile_method VALUES (?, ?, 'midrank')", [release, pct_col])
            con.execute("COMMIT")
            log.info("%s %s: shifted %s tied rows in %s tie groups in %.0fs",
                     release, pct_col, f"{rows:,}", f"{groups:,}", time.perf_counter() - t0)
    con.execute(
        f"CREATE OR REPLACE TABLE top_domains AS SELECT * FROM domain_ranks WHERE pr_rank <= {TOP_N} OR hc_rank <= {TOP_N}"
    )
    con.execute("CHECKPOINT")
    con.close()


def recompute_scores() -> None:
    if not config.ANALYSIS_DB_PATH.exists():
        log.info("no analysis database yet; skipping")
        return
    con = connect_writable(config.ANALYSIS_DB_PATH)
    con.execute(f"SET memory_limit = '{config.DUCKDB_MEMORY_LIMIT}'")
    t0 = time.perf_counter()
    con.execute(
        f"""
        CREATE OR REPLACE TABLE scores AS
        SELECT domain_key, algorithm, params_hash, score, {midrank_sql("score", "params_hash")} AS percentile, rank
        FROM scores
        """
    )
    variants = con.execute("SELECT params_hash, algorithm, params FROM variants").fetchall()
    hashes = {}
    for h, algorithm, params in variants:
        if algorithm in ("trustrank", "seed_distance"):
            hashes[algorithm] = h
        elif algorithm == "pagerank" and '"alpha": 0.85' in params and '"dangling": "teleport"' in params:
            hashes["pagerank"] = h
    release, top = con.execute(
        "SELECT max(value) FILTER (WHERE key = 'release'), max(value) FILTER (WHERE key = 'top') FROM subgraph_meta"
    ).fetchone()
    finish(con, release, int(top), hashes)  # re-sorts scores and rebuilds disagreements
    log.info("analysis database: percentiles and disagreements recomputed in %.0fs", time.perf_counter() - t0)
    con.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    keep_system_awake()
    recompute_scores()  # small (18M rows) and the part that fixes seed distance: do it first
    recompute_ranks()


if __name__ == "__main__":
    main()
