"""Build the top-N subgraph of the Common Crawl domain graph.

    python -m backend.jobs.build_subgraph --top 1000000

1. Take the top N domains by Common Crawl harmonic centrality from ``domain_ranks``.
2. Stream the vertex file once to find their Common Crawl vertex ids.
3. Stream ALL edges once, keeping only links whose two endpoints are both in the set
   (self-links dropped), via DuckDB's out-of-core join; the 10 GB file is never in memory.
4. Write the result as a scipy CSR matrix (``data/subgraph_top<N>.npz``, rows = source,
   binary) and the node id -> domain mapping to ``subgraph_nodes`` in ``data/analysis.duckdb``,
   plus ``subgraph_edges`` sorted by target for the "explain" queries.

Node ids follow Common Crawl's vertex order (reversed-domain order), so the edge stream is
already sorted by source. Logs edges kept, timings and peak memory.
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import duckdb
import numpy as np

from backend import config

from .fetch import keep_system_awake, peak_rss_bytes
from .load_ranks import FormatError, connect_writable

log = logging.getLogger("build_subgraph")

CHUNK_NODES = 50_000


def subgraph_path(top: int) -> Path:
    return config.DATA_DIR / f"subgraph_top{top}.npz"


def graph_file(release: str, name: str) -> Path:
    return config.RAW_DIR / f"{release}-domain-{name}.txt.gz"


def build(top: int, release: str, memory_limit: str) -> dict[str, object]:
    """Run the four steps above and return the logged statistics."""
    started = time.perf_counter()
    vertices, edges = graph_file(release, "vertices"), graph_file(release, "edges")
    for f in (vertices, edges):
        if not f.exists():
            raise FileNotFoundError(f"{f} is missing; run python -m backend.jobs.download_graph first")

    config.DUCKDB_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    con = connect_writable(config.ANALYSIS_DB_PATH, wait_seconds=300)
    con.execute(f"SET memory_limit = '{memory_limit}'")
    con.execute(f"SET temp_directory = '{config.DUCKDB_TEMP_DIR.as_posix()}'")
    con.execute(f"ATTACH '{config.DB_PATH.as_posix()}' AS ranks (READ_ONLY)")

    t0 = time.perf_counter()
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE top_domains AS
        SELECT domain_key, domain, hc_rank, harmonic_centrality, pagerank AS cc_pagerank
        FROM ranks.domain_ranks WHERE release = ? AND hc_rank <= ?
        """,
        [release, top],
    )
    wanted = con.execute("SELECT count(*) FROM top_domains").fetchone()[0]
    con.execute(
        f"""
        CREATE OR REPLACE TABLE subgraph_nodes AS
        SELECT CAST(row_number() OVER (ORDER BY v.cc_id) - 1 AS INTEGER) AS node,
               v.cc_id, t.domain_key, t.domain, t.hc_rank, t.harmonic_centrality, t.cc_pagerank
        FROM read_csv('{vertices.as_posix()}', delim = '\t', header = false, quote = '', escape = '',
                      compression = 'gzip',
                      columns = {{'cc_id': 'BIGINT', 'key': 'VARCHAR', 'n_hosts': 'BIGINT'}}) v
        JOIN top_domains t ON v.key = t.domain_key
        ORDER BY node
        """
    )
    n = con.execute("SELECT count(*) FROM subgraph_nodes").fetchone()[0]
    log.info("mapped %s of %s top domains to vertex ids in %.0fs", f"{n:,}", f"{wanted:,}", time.perf_counter() - t0)
    if n != wanted:
        raise FormatError(f"only {n:,} of the top {wanted:,} rank-file domains appear in the vertex file")

    t0 = time.perf_counter()
    con.execute(
        f"""
        CREATE OR REPLACE TABLE subgraph_edges AS
        SELECT s.node AS src, d.node AS dst
        FROM read_csv('{edges.as_posix()}', delim = '\t', header = false, quote = '', escape = '',
                      compression = 'gzip', columns = {{'from_id': 'BIGINT', 'to_id': 'BIGINT'}}) e
        JOIN subgraph_nodes s ON e.from_id = s.cc_id
        JOIN subgraph_nodes d ON e.to_id = d.cc_id
        WHERE e.from_id <> e.to_id
        ORDER BY dst, src
        """
    )
    n_edges = con.execute("SELECT count(*) FROM subgraph_edges").fetchone()[0]
    log.info("streamed all edges in %.0fs: kept %s links among %s domains", time.perf_counter() - t0, f"{n_edges:,}", f"{n:,}")

    t0 = time.perf_counter()
    out_deg = np.zeros(n, dtype=np.int64)
    counts = con.execute("SELECT src, count(*) FROM subgraph_edges GROUP BY src").fetchnumpy()
    out_deg[counts["src"]] = counts["count_star()"]
    in_counts = con.execute("SELECT dst, count(*) FROM subgraph_edges GROUP BY dst").fetchnumpy()
    in_deg = np.zeros(n, dtype=np.int64)
    in_deg[in_counts["dst"]] = in_counts["count_star()"]
    con.register("degrees", {"node": np.arange(n, dtype=np.int32), "out_degree": out_deg, "in_degree": in_deg})
    con.execute(
        """
        CREATE OR REPLACE TABLE subgraph_nodes AS
        SELECT n.*, d.out_degree, d.in_degree FROM subgraph_nodes n JOIN degrees d USING (node) ORDER BY node
        """
    )
    con.unregister("degrees")
    indptr = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(out_deg, out=indptr[1:])
    out = subgraph_path(top)
    tmp_indices = out.with_suffix(".indices.tmp")
    indices = np.lib.format.open_memmap(tmp_indices, mode="w+", dtype=np.int32, shape=(int(n_edges),))
    for lo in range(0, n, CHUNK_NODES):
        hi = min(n, lo + CHUNK_NODES)
        chunk = con.execute(
            "SELECT dst FROM subgraph_edges WHERE src >= ? AND src < ? ORDER BY src, dst", [lo, hi]
        ).fetchnumpy()["dst"]
        indices[indptr[lo] : indptr[hi]] = chunk
    indices.flush()
    data = np.ones(int(n_edges), dtype=np.int8)
    np.savez(out, indices=indices, indptr=indptr, format=np.array("csr"), shape=np.array([n, n]), data=data)
    del indices, data
    tmp_indices.unlink()
    log.info("wrote %s in %.0fs", out.name, time.perf_counter() - t0)

    stats: dict[str, object] = {
        "release": release,
        "top": top,
        "nodes": n,
        "edges": int(n_edges),
        "dangling_nodes": int((out_deg == 0).sum()),
        "seconds": round(time.perf_counter() - started, 1),
        "peak_rss_bytes": peak_rss_bytes(),
        "npz_bytes": out.stat().st_size,
    }
    con.execute("CREATE OR REPLACE TABLE subgraph_meta (key VARCHAR, value VARCHAR)")
    con.executemany("INSERT INTO subgraph_meta VALUES (?, ?)", [(k, str(v)) for k, v in stats.items()])
    con.execute("CHECKPOINT")
    con.close()
    log.info("done: %s", stats)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top", type=int, default=1_000_000)
    parser.add_argument("--release", default=config.RELEASE)
    parser.add_argument("--memory-limit", default=config.DUCKDB_MEMORY_LIMIT)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    keep_system_awake()
    try:
        build(args.top, args.release, args.memory_limit)
    except (FormatError, FileNotFoundError) as exc:
        log.error("%s", exc)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
