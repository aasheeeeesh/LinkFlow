"""The rank loader on a small file in the real Common Crawl layout, and the HTTP API on top."""

from __future__ import annotations

import gzip
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.main import NOT_FOUND_MESSAGE, create_app
from backend.domains import InvalidDomain, detect_reversed, flip, normalize_query, parent_domains
from backend.jobs.load_ranks import DatabaseBusy, FormatError, connect_writable, load

HEADER = "#harmonicc_pos\t#harmonicc_val\t#pr_pos\t#pr_val\t#host_rev\t#n_hosts"
# (reversed key, harmonic centrality, pagerank, hosts). Ties on pagerank for the last two.
DOMAINS = [
    ("com.example", 9.0e6, 0.30, 12),
    ("org.wikipedia", 8.5e6, 0.25, 300),
    ("uk.co.bbc", 8.0e6, 0.20, 40),
    ("de.xn--bcher-kva", 5.0e6, 0.10, 2),
    ("net.sample", 3.0e6, 0.05, 1),
    ("io.github", 2.0e6, 0.05, 900),
    ("uk.co", 1.0e6, 0.06, 5),  # Common Crawl's graph really contains a co.uk node
]


def write_rank_file(path: Path, rows: list[tuple[str, float, float, int]] = DOMAINS, header: str = HEADER) -> Path:
    by_pr = sorted(rows, key=lambda r: -r[2])
    pr_pos = {r[0]: i + 1 for i, r in enumerate(by_pr)}
    lines = [header]
    for i, (key, hc, pr, hosts) in enumerate(sorted(rows, key=lambda r: -r[1])):
        lines.append(f"{i + 1}\t{hc!r}\t{pr_pos[key]}\t{pr!r}\t{key}\t{hosts}")
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines) + "\n")
    return path


@pytest.fixture(scope="module")
def db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("ranks")
    rank_file = write_rank_file(tmp / "ranks.txt.gz")
    db = tmp / "test.duckdb"
    load(rank_file, db, "test-release", "https://example.invalid/ranks.txt.gz", "1GB")
    return db


@pytest.fixture(scope="module")
def client(db_path: Path, tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    return TestClient(create_app(db_path=db_path, static_dir=tmp_path_factory.mktemp("nostatic")))


def test_domain_lookup_normalises_reversed_keys(client: TestClient) -> None:
    r = client.get("/api/domain/example.com")
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "example.com"
    assert body["domain_key"] == "com.example"
    assert body["release"] == "test-release"
    assert body["harmonic_centrality"] == {"value": 9.0e6, "rank": 1, "percentile": 100.0}
    assert body["pagerank"]["rank"] == 1
    assert body["pagerank"]["percentile"] == 100.0
    assert body["total_domains"] == len(DOMAINS)


def test_lookup_accepts_urls_www_and_idn(client: TestClient) -> None:
    r = client.get("/api/domain/www.bbc.co.uk")
    assert r.status_code == 200
    assert r.json()["domain"] == "bbc.co.uk"
    assert r.json()["matched_from"] == "www.bbc.co.uk"
    r = client.get("/api/domain/bücher.de")
    assert r.status_code == 200
    assert r.json()["domain_key"] == "de.xn--bcher-kva"


def test_percentiles_share_ties(client: TestClient) -> None:
    a = client.get("/api/domain/sample.net").json()["pagerank"]
    b = client.get("/api/domain/github.io").json()["pagerank"]
    # Mid-rank: the two lowest of 7 domains tie at ranks 1 and 2, so both get 100 * 0.5 / 6.
    assert a["percentile"] == pytest.approx(100 * 0.5 / 6) and b["percentile"] == a["percentile"]
    assert a["rank"] != b["rank"]  # Common Crawl's positions break ties; percentiles do not


def test_unknown_domain_404_with_message_and_suggestions(client: TestClient) -> None:
    r = client.get("/api/domain/nonexistent.org")
    assert r.status_code == 404
    assert r.json()["detail"] == NOT_FOUND_MESSAGE
    r = client.get("/api/domain/news.example.com")
    assert r.status_code == 404
    assert r.json()["suggestions"] == ["example.com"]
    # Only the most specific existing parent is suggested, not the co.uk node as well.
    assert client.get("/api/domain/news.bbc.co.uk").json()["suggestions"] == ["bbc.co.uk"]


def test_lookup_accepts_full_urls_with_encoded_slashes(client: TestClient) -> None:
    r = client.get("/api/domain/https%3A%2F%2Fwww.example.com%2Fsome%2Fpath%3Fq%3D1")
    assert r.status_code == 200
    assert r.json()["domain"] == "example.com"
    r = client.get("/api/domain/https://www.example.com/some/path")
    assert r.status_code == 200


def test_invalid_domain_400(client: TestClient) -> None:
    r = client.get("/api/domain/not a domain!")
    assert r.status_code == 400


def test_compare(client: TestClient) -> None:
    r = client.get("/api/compare", params={"d": "example.com, wikipedia.org,missing.com,bad domain"})
    assert r.status_code == 200
    body = r.json()
    assert [x["domain"] for x in body["results"]] == ["example.com", "wikipedia.org"]
    assert [x["domain"] for x in body["not_found"]] == ["missing.com"]
    assert [x["query"] for x in body["invalid"]] == ["bad domain"]


def test_compare_lists_each_domain_once(client: TestClient) -> None:
    r = client.get("/api/compare", params={"d": "example.com,EXAMPLE.com,www.example.com,https://example.com/x,missing.com,Missing.com"})
    body = r.json()
    assert [x["domain"] for x in body["results"]] == ["example.com"]
    assert [x["domain"] for x in body["not_found"]] == ["missing.com"]


def _hold_database(path: Path, read_only: bool) -> subprocess.Popen:
    """Open ``path`` in a separate process (DuckDB locks are per process) until killed."""
    code = (
        "import sys, time, duckdb\n"
        f"con = duckdb.connect(sys.argv[1], read_only={read_only})\n"
        "print('ready', flush=True)\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE, text=True)
    assert proc.stdout is not None and proc.stdout.readline().strip() == "ready"
    return proc


def test_api_reports_a_locked_database_as_503(tmp_path: Path) -> None:
    rank_file = write_rank_file(tmp_path / "ranks.txt.gz")
    db = tmp_path / "locked.duckdb"
    load(rank_file, db, "test-release", "u", "1GB")
    writer = _hold_database(db, read_only=False)  # e.g. a load job in progress
    try:
        r = TestClient(create_app(db_path=db, static_dir=tmp_path)).get("/api/domain/example.com")
        assert r.status_code == 503
        assert "locked" in r.json()["detail"]
    finally:
        writer.kill()
        writer.wait()


def test_loader_explains_a_database_held_by_the_api(tmp_path: Path) -> None:
    rank_file = write_rank_file(tmp_path / "ranks.txt.gz")
    db = tmp_path / "held.duckdb"
    load(rank_file, db, "test-release", "u", "1GB")
    reader = _hold_database(db, read_only=True)  # e.g. the API server
    try:
        with pytest.raises(DatabaseBusy, match="another process"):
            connect_writable(db)
    finally:
        reader.kill()
        reader.wait()


def test_compare_limits(client: TestClient) -> None:
    eleven = ",".join(f"d{i}.com" for i in range(11))
    assert client.get("/api/compare", params={"d": eleven}).status_code == 400
    assert client.get("/api/compare", params={"d": " , "}).status_code == 400


def test_top(client: TestClient) -> None:
    r = client.get("/api/top", params={"metric": "harmonic", "limit": 3})
    assert [x["domain"] for x in r.json()["results"]] == ["example.com", "wikipedia.org", "bbc.co.uk"]
    r = client.get("/api/top", params={"metric": "pagerank", "limit": 100})
    assert [x["pagerank"]["rank"] for x in r.json()["results"]] == list(range(1, len(DOMAINS) + 1))
    assert client.get("/api/top", params={"metric": "bogus"}).status_code == 422
    assert client.get("/api/top", params={"limit": 0}).status_code == 422


def test_meta_and_unknown_api_path(client: TestClient) -> None:
    assert client.get("/api/meta").json()["domains"] == len(DOMAINS)
    assert client.get("/api/nope").status_code == 404


def test_serves_built_frontend_with_spa_fallback(db_path: Path, tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "index.html").write_text("<!doctype html><title>Linkflow Lab</title>")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path.parent / "secret.txt").write_text("outside the static root")
    c = TestClient(create_app(db_path=db_path, static_dir=tmp_path))
    assert "Linkflow Lab" in c.get("/").text
    assert c.get("/").headers["cache-control"] == "no-cache"  # a stale index.html would request deleted chunks
    assert "Linkflow Lab" in c.get("/domain/example.com").text  # client-side route
    assert c.get("/assets/app.js").text == "console.log(1)"
    assert c.get("/favicon.svg").text == "<svg/>"
    assert "outside" not in c.get("/..%2Fsecret.txt").text
    r = c.get("/api/does-not-exist")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert c.get("/api/domain/example.com").json()["domain"] == "example.com"


def test_missing_database_returns_503(tmp_path: Path) -> None:
    c = TestClient(create_app(db_path=tmp_path / "absent.duckdb", static_dir=tmp_path))
    r = c.get("/api/domain/example.com")
    assert r.status_code == 503
    assert "load_ranks" in r.json()["detail"]


def test_loader_rejects_unexpected_header(tmp_path: Path) -> None:
    bad = write_rank_file(tmp_path / "bad.txt.gz", header="#pr_pos\t#pr_val\t#harmonicc_pos\t#harmonicc_val\t#host_rev\t#n_hosts")
    with pytest.raises(FormatError):
        load(bad, tmp_path / "bad.duckdb", "r", "u", "1GB")


def test_detect_reversed() -> None:
    reversed_keys = [k for k, *_ in DOMAINS] + ["com.a", "com.b", "org.c"]
    assert detect_reversed(reversed_keys)
    assert not detect_reversed([flip(k) for k in reversed_keys])


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Example.COM", "example.com"),
        ("https://user:pw@www.example.com:8080/path?q=1#x", "www.example.com"),
        ("example.com.", "example.com"),
        ("bücher.de", "xn--bcher-kva.de"),
    ],
)
def test_normalize_query(raw: str, expected: str) -> None:
    assert normalize_query(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "exa mple.com", "-bad.com", "a..b"])
def test_normalize_query_rejects(raw: str) -> None:
    with pytest.raises(InvalidDomain):
        normalize_query(raw)


def test_parent_domains() -> None:
    assert parent_domains("a.b.example.co.uk") == ["b.example.co.uk", "example.co.uk", "co.uk"]


def test_recompute_shifts_old_percentiles_to_midrank_exactly_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import duckdb

    from backend import config
    from backend.tools import recompute_percentiles

    rows = DOMAINS + [("com.tie1", 5.0e5, 0.01, 1), ("com.tie2", 5.0e5, 0.01, 1), ("com.tie3", 5.0e5, 0.01, 1)]
    db = tmp_path / "ranks.duckdb"
    load(write_rank_file(tmp_path / "r.txt.gz", rows), db, "test-release", "u", "1GB")
    con = duckdb.connect(str(db))
    expected = dict(con.execute("SELECT domain, pr_percentile FROM domain_ranks").fetchall())  # mid-rank from the loader
    # Recreate a database written by the old loader: ties at their lowest position, no method marker.
    con.execute("""UPDATE domain_ranks SET pr_percentile = p, hc_percentile = h FROM (
                       SELECT domain AS d, 100 * percent_rank() OVER (ORDER BY pagerank) AS p,
                              100 * percent_rank() OVER (ORDER BY harmonic_centrality) AS h FROM domain_ranks) o
                   WHERE domain = o.d""")
    con.execute("DELETE FROM percentile_method")
    con.close()
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(config, "DUCKDB_TEMP_DIR", tmp_path / "tmp")
    for _ in range(2):  # the second run must be a no-op
        recompute_percentiles.recompute_ranks()
        con = duckdb.connect(str(db), read_only=True)
        got = dict(con.execute("SELECT domain, pr_percentile FROM domain_ranks").fetchall())
        con.close()
        assert got == pytest.approx(expected)
