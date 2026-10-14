"""Weight each subgraph link by the number of host-level links between the two domains.

    python -m backend.jobs.build_host_weights [--top 1000000]

1. Host -> domain: a host belongs to the registered domain whose reversed key is the longest dot-separated
   prefix of its reversed name. Matching uses the subgraph's keys (2 to 5 labels). A match on a key that is itself
   the parent of other registered domains (for example ``uk.co``) is re-checked against all 118M domain keys: if
   the next-longer prefix is a registered domain, the host belongs to that (non-subgraph) domain and is dropped.
2. Stream every host edge part once and count links per (source domain, target domain), self-links dropped.
3. Save ``data/subgraph_top<N>_weighted.npz`` (CSR, float32 link counts, same node ids as the binary subgraph).

Each of the 48 vertex and 192 edge parts is downloaded, ingested and deleted before the next, so the 17.5 GB host
graph never sits on disk; finished parts are recorded and skipped on restart.
"""

from __future__ import annotations

import argparse
import gzip
import io
import logging
import time
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import scipy.sparse as sp

from backend import config

from .build_subgraph import subgraph_path
from .fetch import USER_AGENT, download, keep_system_awake, peak_rss_bytes
from .load_ranks import connect_writable

log = logging.getLogger("build_host_weights")
DATA_ROOT = "https://data.commoncrawl.org/"
MAX_LABELS = 5


def weighted_path(top: int) -> Path:
    return config.DATA_DIR / f"subgraph_top{top}_weighted.npz"


def part_list(release: str, kind: str) -> list[str]:
    """Relative paths of the host vertex or edge parts, from the release's ``.paths.gz`` listing."""
    url = f"{config.CC_BASE}/{release}/host/{release}-host-{kind}.paths.gz"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=120) as r:
        return gzip.GzipFile(fileobj=io.BytesIO(r.read())).read().decode().split()


def fetch_part(rel_path: str) -> Path:
    dest = config.RAW_DIR / "host" / Path(rel_path).name
    return download(DATA_ROOT + rel_path, dest)


def _key(n: int) -> str:
    return f"array_to_string(list_slice(parts, 1, {n}), '.')"


def build(
    top: int, release: str, memory_limit: str,
    vertex_parts: list[str], edge_parts: list[str], fetch: Callable[[str], Path] = fetch_part,
) -> dict[str, object]:
    started = time.perf_counter()
    con = connect_writable(config.ANALYSIS_DB_PATH, wait_seconds=300)
    con.execute(f"SET memory_limit = '{memory_limit}'")
    config.DUCKDB_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory = '{config.DUCKDB_TEMP_DIR.as_posix()}'")
    con.execute("SET max_temp_directory_size = '15GiB'")
    con.execute(f"ATTACH '{config.DB_PATH.as_posix()}' AS ranks (READ_ONLY)")
    con.execute("CREATE TABLE IF NOT EXISTS host_parts_done (part VARCHAR)")
    con.execute("CREATE TABLE IF NOT EXISTS host_nodes (host_id BIGINT, node INTEGER, host VARCHAR, key VARCHAR, parent BOOLEAN)")
    con.execute("CREATE TABLE IF NOT EXISTS host_pairs (src INTEGER, dst INTEGER, n BIGINT)")
    con.execute("CREATE TABLE IF NOT EXISTS host_meta (key VARCHAR, value VARCHAR)")
    done = {r[0] for r in con.execute("SELECT part FROM host_parts_done").fetchall()}
    if "parents" not in done:
        # Subgraph domains that are the parent of other registered domains (public-suffix-like nodes).
        con.execute("BEGIN")
        con.execute(
            """
            CREATE OR REPLACE TABLE parent_keys AS
            SELECT DISTINCT p AS key FROM (
                SELECT array_to_string(list_slice(string_split(domain_key, '.'), 1, len(string_split(domain_key, '.')) - 1), '.') AS p
                FROM ranks.domain_ranks WHERE release = ?) WHERE p IN (SELECT domain_key FROM subgraph_nodes)
            """,
            [release],
        )
        con.execute("INSERT INTO host_parts_done VALUES ('parents')")
        con.execute("COMMIT")

    def run_parts(parts: list[str], ingest: Callable[[Path], None]) -> None:
        todo = [p for p in parts if p not in done]
        with ThreadPoolExecutor(max_workers=1) as pool:
            nxt = pool.submit(fetch, todo[0]) if todo else None
            for i, part in enumerate(todo):
                local = nxt.result()
                nxt = pool.submit(fetch, todo[i + 1]) if i + 1 < len(todo) else None
                con.execute("BEGIN")
                ingest(local)
                con.execute("INSERT INTO host_parts_done VALUES (?)", [part])
                con.execute("COMMIT")
                if local.is_relative_to(config.RAW_DIR):
                    local.unlink()
                if (i + 1) % 10 == 0 or i + 1 == len(todo):
                    log.info("%d of %d parts done (peak RSS %.1f GB)", len(parts) - len(todo) + i + 1, len(parts), peak_rss_bytes() / 1e9)

    # Candidate keys are computed first (NULL when the host has too few labels) so every join is a plain
    # equi-join; a one-sided condition inside LEFT JOIN ... ON makes DuckDB fall back to a nested-loop join.
    cols = ", ".join(f"CASE WHEN len(parts) >= {n} THEN {_key(n)} END AS c{n}" for n in range(MAX_LABELS, 1, -1))
    candidates = " ".join(f"LEFT JOIN subgraph_nodes k{n} ON k{n}.domain_key = v.c{n}" for n in range(MAX_LABELS, 1, -1))
    node = "coalesce(" + ", ".join(f"k{n}.node" for n in range(MAX_LABELS, 1, -1)) + ")"
    key = "coalesce(" + ", ".join(f"k{n}.domain_key" for n in range(MAX_LABELS, 1, -1)) + ")"

    def ingest_vertices(f: Path) -> None:
        con.execute(
            f"""
            INSERT INTO host_nodes
            SELECT id, node, CASE WHEN parent THEN host END, CASE WHEN parent THEN key END, parent FROM (
                SELECT v.id, v.host, {node} AS node, {key} AS key, {key} IN (SELECT key FROM parent_keys) AS parent
                FROM (SELECT id, host, {cols} FROM (SELECT id, host, string_split(host, '.') AS parts
                      FROM read_csv('{f.as_posix()}', delim = '\t', header = false, quote = '', escape = '',
                                    columns = {{'id': 'BIGINT', 'host': 'VARCHAR'}}))) v
                {candidates}
            ) WHERE node IS NOT NULL
            """
        )

    t0 = time.perf_counter()
    run_parts(vertex_parts, ingest_vertices)
    if "verified" not in done:
        # Drop hosts matched to a parent key when the next-longer prefix is itself a registered domain.
        con.execute("BEGIN")
        con.execute(
            """
            DELETE FROM host_nodes WHERE parent AND host_id IN (
                SELECT h.host_id FROM host_nodes h
                JOIN ranks.domain_ranks r
                  ON r.domain_key = array_to_string(list_slice(string_split(h.host, '.'), 1, len(string_split(h.key, '.')) + 1), '.')
                WHERE h.parent AND len(string_split(h.host, '.')) > len(string_split(h.key, '.')) AND r.release = ?)
            """,
            [release],
        )
        con.execute("INSERT INTO host_parts_done VALUES ('verified')")
        con.execute("COMMIT")
    hosts = con.execute("SELECT count(*) FROM host_nodes").fetchone()[0]
    log.info("mapped %s hosts to subgraph domains in %.0fs", f"{hosts:,}", time.perf_counter() - t0)

    def ingest_edges(f: Path) -> None:
        con.execute(
            f"""
            INSERT INTO host_pairs
            SELECT s.node, d.node, count(*)
            FROM read_csv('{f.as_posix()}', delim = '\t', header = false, quote = '', escape = '',
                          columns = {{'from_id': 'BIGINT', 'to_id': 'BIGINT'}}) e
            JOIN host_nodes s ON e.from_id = s.host_id
            JOIN host_nodes d ON e.to_id = d.host_id
            WHERE s.node <> d.node
            GROUP BY 1, 2
            """
        )

    t0 = time.perf_counter()
    run_parts(edge_parts, ingest_edges)
    log.info("streamed all host edge parts in %.0fs", time.perf_counter() - t0)

    n = con.execute("SELECT count(*) FROM subgraph_nodes").fetchone()[0]
    counts = con.execute("SELECT src, dst, sum(n) AS links FROM host_pairs GROUP BY 1, 2 ORDER BY 1, 2").fetchnumpy()
    W = sp.csr_matrix(
        (counts["links"].astype(np.float32), (counts["src"].astype(np.int64), counts["dst"].astype(np.int32))), shape=(n, n)
    )
    W.indices = W.indices.astype(np.int32)
    W.sort_indices()
    sp.save_npz(weighted_path(top), W, compressed=False)
    binary = sp.load_npz(subgraph_path(top))
    overlap = (binary.astype(bool).multiply(W.astype(bool))).nnz
    stats: dict[str, object] = {
        "hosts_mapped": hosts, "weighted_links": int(W.nnz), "binary_links": int(binary.nnz),
        "links_in_both": int(overlap), "total_host_links": float(W.data.sum()),
        "seconds": round(time.perf_counter() - started, 1), "peak_rss_bytes": peak_rss_bytes(),
    }
    con.execute("DELETE FROM host_meta")
    con.executemany("INSERT INTO host_meta VALUES (?, ?)", [(k, str(v)) for k, v in stats.items()])
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
    build(args.top, args.release, args.memory_limit,
          part_list(args.release, "vertices"), part_list(args.release, "edges"))


if __name__ == "__main__":
    main()
