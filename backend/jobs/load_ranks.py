"""Load Common Crawl's domain rank file into DuckDB.

    python -m backend.jobs.load_ranks [--release cc-main-2026-may-jun-jul] [--file PATH]

Steps: download (resumable) -> verify the header -> detect reversed notation on a sample
-> stream the gzip through DuckDB's CSV reader into ``domain_ranks`` (sorted by domain, which
serves domain lookups without a separate index; see ``finish``) -> ``releases`` metadata row
-> small ``top_domains`` table. Re-running skips the stream when the release is already loaded.
The multi-GB file is never held in memory; DuckDB reads it as a stream and spills
sorts to ``data/duckdb_tmp``.
"""

from __future__ import annotations

import argparse
import gzip
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from backend import config
from backend.algorithms.scoring import midrank_sql
from backend.domains import detect_reversed

from .fetch import download, peak_rss_bytes

log = logging.getLogger("load_ranks")

EXPECTED_COLUMNS = ["#harmonicc_pos", "#harmonicc_val", "#pr_pos", "#pr_val", "#host_rev", "#n_hosts"]
CSV_COLUMNS = {
    "harmonicc_pos": "BIGINT",
    "harmonicc_val": "DOUBLE",
    "pr_pos": "BIGINT",
    "pr_val": "DOUBLE",
    "host_rev": "VARCHAR",
    "n_hosts": "BIGINT",
}
TOP_N = 1000
SAMPLE_LINES = 20_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS domain_ranks (
    domain_key          VARCHAR NOT NULL,   -- key exactly as in the Common Crawl file
    domain              VARCHAR NOT NULL,   -- normal notation, e.g. example.com
    harmonic_centrality DOUBLE  NOT NULL,
    hc_rank             BIGINT  NOT NULL,
    pagerank            DOUBLE  NOT NULL,
    pr_rank             BIGINT  NOT NULL,
    hc_percentile       DOUBLE  NOT NULL,   -- mid-rank percentile of harmonic_centrality
    pr_percentile       DOUBLE  NOT NULL,   -- mid-rank percentile of pagerank
    n_hosts             BIGINT  NOT NULL,
    release             VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS releases (
    release           VARCHAR PRIMARY KEY,
    source_url        VARCHAR NOT NULL,
    file_bytes        BIGINT  NOT NULL,
    domains           BIGINT  NOT NULL,
    reversed_notation BOOLEAN NOT NULL,
    loaded_at         TIMESTAMP NOT NULL
);
"""


# Which percentile definition each stored column uses; recompute_percentiles relies on it.
PERCENTILE_METHOD_SCHEMA = "CREATE TABLE IF NOT EXISTS percentile_method (release VARCHAR, col VARCHAR, method VARCHAR)"


class FormatError(RuntimeError):
    """The rank file does not have the documented layout (see docs/DATA.md)."""


class DatabaseBusy(RuntimeError):
    """Another process (usually the API server) has the database open."""


def connect_writable(db_path: Path, wait_seconds: float = 0) -> duckdb.DuckDBPyConnection:
    """Open the database for writing, explaining the usual cause when it is locked.

    With ``wait_seconds`` > 0 a lock held by another process (for example an API request
    reading the analysis database) is retried every 10 s for up to that long.
    """
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            return duckdb.connect(str(db_path))
        except duckdb.IOException as exc:
            if time.monotonic() < deadline:
                log.warning("%s is locked by another process; retrying in 10 s", db_path.name)
                time.sleep(10)
                continue
            raise DatabaseBusy(
                f"{db_path} is open in another process, probably the API server. Stop it "
                "(for example `docker compose stop app`) and run this job again."
            ) from exc


def read_header_and_sample(path: Path, n: int = SAMPLE_LINES) -> tuple[list[str], list[str]]:
    """Return the header columns and the domain keys of the first ``n`` data rows."""
    keys: list[str] = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        header = f.readline().rstrip("\n").split("\t")
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != len(EXPECTED_COLUMNS):
                raise FormatError(f"data row has {len(parts)} fields, expected {len(EXPECTED_COLUMNS)}: {line!r}")
            keys.append(parts[4])
            if len(keys) >= n:
                break
    return header, keys


def load(path: Path, db_path: Path, release: str, source_url: str, memory_limit: str) -> dict[str, object]:
    """Stream ``path`` into ``domain_ranks`` for ``release``, replacing earlier rows of that release."""
    started = time.perf_counter()
    header, sample = read_header_and_sample(path)
    if header != EXPECTED_COLUMNS:
        raise FormatError(f"unexpected header {header}; expected {EXPECTED_COLUMNS}. Update docs/DATA.md and the parser.")
    reversed_notation = detect_reversed(sample)
    log.info("header OK; reversed notation detected: %s (e.g. %s)", reversed_notation, sample[:3])
    domain_expr = (
        "array_to_string(list_reverse(string_split(host_rev, '.')), '.')" if reversed_notation else "host_rev"
    )

    config.DUCKDB_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = connect_writable(db_path)
    con.execute(f"SET memory_limit = '{memory_limit}'")
    con.execute(f"SET temp_directory = '{config.DUCKDB_TEMP_DIR.as_posix()}'")
    con.execute("SET preserve_insertion_order = false")
    con.execute(SCHEMA)

    con.execute("BEGIN")
    con.execute("DELETE FROM domain_ranks WHERE release = ?", [release])
    t0 = time.perf_counter()
    con.execute(
        f"""
        INSERT INTO domain_ranks
        SELECT host_rev,
               {domain_expr} AS domain,
               harmonicc_val, harmonicc_pos, pr_val, pr_pos,
               {midrank_sql("harmonicc_val")},
               {midrank_sql("pr_val")},
               n_hosts,
               ?
        FROM read_csv(?, delim = '\t', header = false, skip = 1, quote = '', escape = '',
                      compression = 'gzip', columns = {CSV_COLUMNS!r})
        ORDER BY domain
        """,
        [release, str(path)],
    )
    log.info("streamed rank file into DuckDB in %.0fs", time.perf_counter() - t0)

    stats = con.execute(
        """
        SELECT count(*), count(DISTINCT domain), min(hc_rank), max(hc_rank), min(pr_rank), max(pr_rank),
               sum(pagerank)
        FROM domain_ranks WHERE release = ?
        """,
        [release],
    ).fetchone()
    rows, distinct, hc_min, hc_max, pr_min, pr_max, pr_sum = stats
    log.info(
        "rows=%s distinct domains=%s hc_rank=[%s, %s] pr_rank=[%s, %s] sum(pagerank)=%.6f",
        f"{rows:,}", f"{distinct:,}", hc_min, hc_max, pr_min, pr_max, pr_sum,
    )
    if rows == 0 or hc_min != 1 or pr_min != 1 or hc_max != rows or pr_max != rows:
        raise FormatError("rank positions are not 1..N; refusing to commit")

    con.execute(PERCENTILE_METHOD_SCHEMA)
    con.execute("DELETE FROM percentile_method WHERE release = ?", [release])
    con.executemany("INSERT INTO percentile_method VALUES (?, ?, 'midrank')", [[release, "pr_percentile"], [release, "hc_percentile"]])
    con.execute(
        "INSERT OR REPLACE INTO releases VALUES (?, ?, ?, ?, ?, ?)",
        [release, source_url, path.stat().st_size, rows, reversed_notation, datetime.now(timezone.utc)],
    )
    con.execute("COMMIT")
    return finish(con, db_path, release, started)


def finish(con: duckdb.DuckDBPyConnection, db_path: Path, release: str, started: float) -> dict[str, object]:
    """Steps after the rows are committed: the small top table and a checkpoint.

    There is deliberately no index on ``domain``. DuckDB builds ART indexes in memory and one
    over ~118M domain strings did not fit in a 3 GB limit. Rows are inserted sorted by domain,
    so DuckDB's per-row-group min/max statistics already confine an equality lookup to a
    single row group (measured at 6-8 ms per lookup on the full release).
    """
    con.execute(
        f"""
        CREATE OR REPLACE TABLE top_domains AS
        SELECT * FROM domain_ranks WHERE pr_rank <= {TOP_N} OR hc_rank <= {TOP_N}
        """
    )
    con.execute("CHECKPOINT")
    rows, reversed_notation = con.execute(
        "SELECT domains, reversed_notation FROM releases WHERE release = ?", [release]
    ).fetchone()
    con.close()
    result = {
        "release": release,
        "rows": rows,
        "reversed_notation": reversed_notation,
        "seconds": round(time.perf_counter() - started, 1),
        "peak_rss_bytes": peak_rss_bytes(),
        "db_bytes": db_path.stat().st_size,
    }
    log.info("done: %s", result)
    return result


def already_loaded(db_path: Path, release: str, file_bytes: int) -> bool:
    """True when ``release`` was committed earlier from a file of the same size."""
    if not db_path.exists():
        return False
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute("SELECT file_bytes FROM releases WHERE release = ?", [release]).fetchone()
    except duckdb.CatalogException:
        row = None
    finally:
        con.close()
    return row is not None and row[0] == file_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", default=config.RELEASE)
    parser.add_argument("--file", type=Path, help="use an already downloaded rank file")
    parser.add_argument("--db", type=Path, default=config.DB_PATH)
    parser.add_argument("--memory-limit", default=config.DUCKDB_MEMORY_LIMIT)
    parser.add_argument("--force", action="store_true", help="reload even if this release is already loaded")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    filename = config.ranks_filename(args.release)
    url = config.domain_url(args.release, filename)
    try:
        path = args.file or download(url, config.RAW_DIR / filename)
        if not args.force and already_loaded(args.db, args.release, path.stat().st_size):
            log.info("release %s is already loaded from this file; running the remaining steps only", args.release)
            con = connect_writable(args.db)
            con.execute(f"SET memory_limit = '{args.memory_limit}'")
            finish(con, args.db, args.release, time.perf_counter())
            return
        load(path, args.db, args.release, url, args.memory_limit)
    except (FormatError, DatabaseBusy) as exc:
        log.error("%s", exc)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
