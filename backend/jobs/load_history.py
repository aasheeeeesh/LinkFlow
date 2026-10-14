"""Load earlier releases' domain ranks into data/history.duckdb for the rank-history chart.

    python -m backend.jobs.load_history [--convert-from OLD.duckdb]

For each release in ``config.HISTORY_RELEASES`` (taken from Common Crawl's official listing), wait until
``download_graph --history`` has finished its rank file, check the header, and store only what the chart needs:

    history(cur_pos, release_pos, hc_rank, pr_rank)

``cur_pos`` is the domain's harmonic-centrality position in the *current* release (unique, 1..N), so no domain
strings are stored: about 9 bytes per row instead of 34. Domains absent from the current release are skipped (they
have no domain page). Rows are sorted by ``cur_pos`` within each release so point lookups use DuckDB's zone maps.
The raw file is deleted after loading. Already loaded releases are skipped.

``--convert-from`` converts releases stored by the first version of this job (one row per domain string) instead
of downloading them again.
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import duckdb

from backend import config

from .fetch import keep_system_awake, remote_size
from .load_ranks import EXPECTED_COLUMNS, FormatError, connect_writable, read_header_and_sample

log = logging.getLogger("load_history")

BUCKETS = 8

SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    cur_pos INTEGER NOT NULL, release_pos TINYINT NOT NULL, hc_rank INTEGER NOT NULL, pr_rank INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS history_releases (release VARCHAR, position INTEGER, domains BIGINT, matched BIGINT);
CREATE TABLE IF NOT EXISTS history_meta (key VARCHAR PRIMARY KEY, value VARCHAR);
"""


def current_release(con: duckdb.DuckDBPyConnection) -> str:
    """The release the API serves: the configured one if loaded, else the newest (same rule as the API)."""
    row = con.execute(
        "SELECT release FROM ranks.releases ORDER BY release = ? DESC, loaded_at DESC LIMIT 1", [config.RELEASE]
    ).fetchone()
    if row is None:
        raise FormatError("Load the current release first: python -m backend.jobs.load_ranks")
    return row[0]


def rank_file_source(path: Path) -> str:
    """SQL relation over a Common Crawl rank file: key = #host_rev, hc_rank = #harmonicc_pos, pr_rank = #pr_pos."""
    return f"""
        SELECT host_rev AS key, harmonicc_pos AS hc_rank, pr_pos AS pr_rank
        FROM read_csv('{path.as_posix()}', delim = '\t', header = false, skip = 1, quote = '', escape = '',
                      compression = 'gzip', columns = {{'harmonicc_pos': 'BIGINT', 'harmonicc_val': 'DOUBLE',
                      'pr_pos': 'BIGINT', 'pr_val': 'DOUBLE', 'host_rev': 'VARCHAR', 'n_hosts': 'BIGINT'}})"""


def load_release(
    con: duckdb.DuckDBPyConnection, source: str, release: str, position: int, current: str, domains: int | None = None
) -> int:
    """Insert one release from ``source`` (columns key, hc_rank, pr_rank) keyed by current position; return rows kept.

    cur_pos(d) = current-release #harmonicc_pos of domain d. The source is staged once, then joined in BUCKETS
    hash partitions of the key so each hash table holds ~1/BUCKETS of the 120M domain strings (a single join
    exceeds a 4 GB memory limit). Each partition is inserted sorted by cur_pos, so a point lookup reads about one
    row group per partition. ``domains`` defaults to the largest position in the source (positions run 1..N).
    """
    con.execute("BEGIN")
    con.execute("DELETE FROM history WHERE release_pos = ?", [position])
    con.execute(f"CREATE OR REPLACE TABLE staging AS {source}")
    if domains is None:
        domains = con.execute("SELECT max(hc_rank) FROM staging").fetchone()[0]
    for b in range(BUCKETS):
        con.execute(
            f"""
            INSERT INTO history
            SELECT c.hc_rank, ?, s.hc_rank, s.pr_rank
            FROM (SELECT key, hc_rank, pr_rank FROM staging WHERE hash(key) % {BUCKETS} = {b}) s
            JOIN (SELECT domain_key, hc_rank FROM ranks.domain_ranks
                  WHERE release = ? AND hash(domain_key) % {BUCKETS} = {b}) c ON c.domain_key = s.key
            ORDER BY c.hc_rank
            """,
            [position, current],
        )
    con.execute("DROP TABLE staging")
    matched = con.execute("SELECT count(*) FROM history WHERE release_pos = ?", [position]).fetchone()[0]
    con.execute("DELETE FROM history_releases WHERE release = ?", [release])
    con.execute("INSERT INTO history_releases VALUES (?, ?, ?, ?)", [release, position, domains, matched])
    con.execute("INSERT OR REPLACE INTO history_meta VALUES ('current_release', ?)", [current])
    con.execute("COMMIT")
    return matched


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep-raw", action="store_true", help="do not delete rank files after loading")
    parser.add_argument("--convert-from", type=Path, help="history database written by the first version of this job")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    keep_system_awake()
    run(keep_raw=args.keep_raw, convert_from=args.convert_from)


def run(keep_raw: bool = False, convert_from: Path | None = None) -> None:
    """Load every history release not loaded yet, waiting for each rank file to finish downloading."""
    con = connect_writable(config.HISTORY_DB_PATH, wait_seconds=300)
    con.execute(f"SET memory_limit = '{config.DUCKDB_MEMORY_LIMIT}'")
    config.DUCKDB_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory = '{config.DUCKDB_TEMP_DIR.as_posix()}'")
    con.execute("SET max_temp_directory_size = '10GiB'")
    con.execute(f"ATTACH '{config.DB_PATH.as_posix()}' AS ranks (READ_ONLY)")
    con.execute(SCHEMA)
    current = current_release(con)
    stored = con.execute("SELECT value FROM history_meta WHERE key = 'current_release'").fetchone()
    if stored is not None and stored[0] != current:  # cur_pos refers to another release: start again
        con.execute("DELETE FROM history")
        con.execute("DELETE FROM history_releases")
    loaded = {r[0] for r in con.execute("SELECT release FROM history_releases").fetchall()}
    old: dict[str, int] = {}
    if convert_from is not None and convert_from.exists():
        con.execute(f"ATTACH '{convert_from.as_posix()}' AS old (READ_ONLY)")
        old = dict(con.execute("SELECT release, domains FROM old.history_releases").fetchall())
    for position, release in enumerate(config.HISTORY_RELEASES, 1):
        if release in loaded:
            log.info("%s already loaded", release)
            continue
        t0 = time.perf_counter()
        path = config.RAW_DIR / config.ranks_filename(release)
        if release in old:
            source = f"SELECT domain_key AS key, hc_rank, pr_rank FROM old.history WHERE release = '{release}'"
            matched = load_release(con, source, release, position, current, domains=old[release])
        else:
            total = remote_size(config.domain_url(release, config.ranks_filename(release)))
            while not (path.exists() and path.stat().st_size == total):
                time.sleep(60)
            header, _ = read_header_and_sample(path, n=10)
            if header != EXPECTED_COLUMNS:
                raise FormatError(f"{path.name}: unexpected header {header}")
            matched = load_release(con, rank_file_source(path), release, position, current)
        con.execute("CHECKPOINT")
        log.info("%s: %s domains also in %s, loaded in %.0fs", release, f"{matched:,}", current, time.perf_counter() - t0)
        if not keep_raw and path.exists():
            path.unlink()
    con.close()
    log.info("history complete")


if __name__ == "__main__":
    main()
