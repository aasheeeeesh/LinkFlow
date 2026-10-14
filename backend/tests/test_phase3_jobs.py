"""Host-level link weights and rank history on small graphs in Common Crawl's file layout."""

from __future__ import annotations

import gzip
from pathlib import Path

import duckdb
import numpy as np
import pytest
import scipy.sparse as sp

from backend import config
from backend.jobs import build_host_weights, build_subgraph, load_history
from backend.jobs.load_ranks import load
from backend.tests.test_load_and_api import write_rank_file

RELEASE = "test-release"
# Top 3 by harmonic centrality: uk.co (a parent of other registered domains), com.alpha, org.beta.
DOMAINS = [("uk.co", 9e6, 0.3, 1), ("com.alpha", 8e6, 0.3, 1), ("org.beta", 7e6, 0.2, 1), ("uk.co.shop", 1e6, 0.2, 1)]


def _gz(path: Path, lines: list[str]) -> Path:
    with gzip.open(path, "wt", newline="") as f:
        f.writelines(line + "\n" for line in lines)
    return path


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir()
    for name, value in {"DATA_DIR": tmp_path, "RAW_DIR": raw, "DB_PATH": tmp_path / "r.duckdb",
                        "ANALYSIS_DB_PATH": tmp_path / "a.duckdb", "HISTORY_DB_PATH": tmp_path / "h.duckdb",
                        "DUCKDB_TEMP_DIR": tmp_path / "tmp"}.items():
        monkeypatch.setattr(config, name, value)
    load(write_rank_file(tmp_path / "ranks.txt.gz", DOMAINS), config.DB_PATH, RELEASE, "u", "1GB")
    keys = sorted(k for k, *_ in DOMAINS)
    ids = {k: i for i, k in enumerate(keys)}
    _gz(raw / f"{RELEASE}-domain-vertices.txt.gz", [f"{ids[k]}\t{k}\t1" for k in keys])
    links = [("com.alpha", "org.beta"), ("org.beta", "com.alpha"), ("uk.co", "com.alpha")]
    _gz(raw / f"{RELEASE}-domain-edges.txt.gz", [f"{ids[s]}\t{ids[t]}" for s, t in sorted(links, key=lambda e: (ids[e[0]], ids[e[1]]))])
    build_subgraph.build(3, RELEASE, "1GB")
    return tmp_path


def test_host_weights_count_host_links_and_skip_hosts_of_other_domains(env: Path) -> None:
    hosts = ["com.alpha", "com.alpha.www", "org.beta.news", "uk.co.nic", "uk.co.shop.www"]
    vparts = [_gz(env / "v0.gz", [f"{i}\t{h}" for i, h in enumerate(hosts[:3])]),
              _gz(env / "v1.gz", [f"{i + 3}\t{h}" for i, h in enumerate(hosts[3:])])]
    # alpha->beta twice (two alpha hosts), beta->alpha once, co.uk->alpha once,
    # shop->alpha must be dropped (uk.co.shop is a registered domain outside the subgraph),
    # alpha->alpha (between two alpha hosts) is a self-link.
    eparts = [_gz(env / "e0.gz", ["0\t2", "1\t2", "1\t0"]), _gz(env / "e1.gz", ["2\t1", "3\t0", "4\t0"])]
    stats = build_host_weights.build(3, RELEASE, "1GB", [str(p) for p in vparts], [str(p) for p in eparts], fetch=Path)
    con = duckdb.connect(str(config.ANALYSIS_DB_PATH), read_only=True)
    node = dict(con.execute("SELECT domain, node FROM subgraph_nodes").fetchall())
    W = sp.load_npz(build_host_weights.weighted_path(3))
    assert W[node["alpha.com"], node["beta.org"]] == 2
    assert W[node["beta.org"], node["alpha.com"]] == 1
    assert W[node["co.uk"], node["alpha.com"]] == 1  # uk.co.nic is a host of co.uk itself
    assert W.nnz == 3 and stats["hosts_mapped"] == 4
    assert W.dtype == np.float32 and W.has_canonical_format
    # A restart finds every part done and recomputes nothing.
    assert con.execute("SELECT count(*) FROM host_parts_done").fetchone()[0] == 6
    con.close()


OLD_DOMAINS = [("com.alpha", 9.5e6, 0.5, 1), ("uk.co", 9e6, 0.3, 1), ("net.gone", 8e6, 0.1, 1), ("org.beta", 7e6, 0.2, 1)]
# Current positions (test-release): uk.co 1, com.alpha 2, org.beta 3, uk.co.shop 4. net.gone is not current: skipped.
EXPECTED_HISTORY = [(1, 1, 2, 2), (2, 1, 1, 1), (3, 1, 4, 3)]  # (cur_pos, release_pos, hc_rank, pr_rank)


def test_history_loader(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old = "old-release"
    path = write_rank_file(config.RAW_DIR / config.ranks_filename(old), OLD_DOMAINS)
    monkeypatch.setattr(config, "HISTORY_RELEASES", (old,))
    monkeypatch.setattr(load_history, "remote_size", lambda url: path.stat().st_size)
    load_history.run()
    con = duckdb.connect(str(config.HISTORY_DB_PATH), read_only=True)
    assert con.execute("SELECT * FROM history ORDER BY cur_pos").fetchall() == EXPECTED_HISTORY
    assert con.execute("SELECT position, domains, matched FROM history_releases").fetchall() == [(1, 4, 3)]
    assert con.execute("SELECT value FROM history_meta WHERE key = 'current_release'").fetchone() == (RELEASE,)
    con.close()
    assert not path.exists()  # raw file deleted after loading
    load_history.run()  # second run: nothing to do, no error


def test_history_converts_the_first_storage_format(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old_db = env / "history_v1.duckdb"
    con = duckdb.connect(str(old_db))
    con.execute("CREATE TABLE history (domain_key VARCHAR, release VARCHAR, hc_rank INTEGER, pr_rank INTEGER, "
                "harmonic_centrality FLOAT, pagerank DOUBLE)")
    con.execute("CREATE TABLE history_releases (release VARCHAR, position INTEGER, domains BIGINT)")
    positions = {"com.alpha": (1, 1), "uk.co": (2, 2), "net.gone": (3, 4), "org.beta": (4, 3)}
    con.executemany("INSERT INTO history VALUES (?, 'old-release', ?, ?, 0, 0)", [(k, *v) for k, v in positions.items()])
    con.execute("INSERT INTO history_releases VALUES ('old-release', 1, 4)")
    con.close()
    monkeypatch.setattr(config, "HISTORY_RELEASES", ("old-release",))
    monkeypatch.setattr(load_history, "remote_size", lambda url: pytest.fail("converted releases are not downloaded"))
    load_history.run(convert_from=old_db)
    con = duckdb.connect(str(config.HISTORY_DB_PATH), read_only=True)
    assert con.execute("SELECT * FROM history ORDER BY cur_pos").fetchall() == EXPECTED_HISTORY
    assert con.execute("SELECT position, domains, matched FROM history_releases").fetchall() == [(1, 4, 3)]
    con.close()
