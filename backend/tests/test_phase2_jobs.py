"""build_subgraph + compute_all end to end on a small graph in Common Crawl's file layout."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import duckdb
import numpy as np
import pytest
import scipy.sparse as sp

from backend import config
from backend.algorithms import pagerank
from backend.jobs import build_subgraph, compute_all
from backend.jobs.load_ranks import FormatError, load
from backend.tests.test_load_and_api import write_rank_file

RELEASE = "test-release"
# Reversed keys with (harmonic centrality, pagerank, hosts); top 5 by harmonic are the first five.
DOMAINS = [
    ("com.alpha", 9.0e6, 0.30, 3),
    ("org.beta", 8.0e6, 0.20, 2),
    ("net.gamma", 7.0e6, 0.15, 1),
    ("com.delta", 6.0e6, 0.15, 1),
    ("org.epsilon", 5.0e6, 0.10, 1),
    ("com.zeta", 1.0e6, 0.10, 1),  # outside the top 5
]
# Edges by domain key; links to or from com.zeta and the self-link must be dropped.
EDGES = [
    ("com.alpha", "org.beta"), ("com.alpha", "net.gamma"), ("org.beta", "com.alpha"),
    ("net.gamma", "com.alpha"), ("net.gamma", "org.beta"), ("com.delta", "com.alpha"),
    ("com.delta", "com.delta"), ("com.zeta", "com.alpha"), ("org.epsilon", "com.zeta"),
]


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "RAW_DIR", raw)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "ranks.duckdb")
    monkeypatch.setattr(config, "ANALYSIS_DB_PATH", tmp_path / "analysis.duckdb")
    monkeypatch.setattr(config, "DUCKDB_TEMP_DIR", tmp_path / "tmp")
    load(write_rank_file(tmp_path / "ranks.txt.gz", DOMAINS), config.DB_PATH, RELEASE, "u", "1GB")
    keys = sorted(k for k, *_ in DOMAINS)  # Common Crawl orders vertices by reversed name
    ids = {k: i for i, k in enumerate(keys)}
    with gzip.open(raw / f"{RELEASE}-domain-vertices.txt.gz", "wt", newline="") as f:
        f.writelines(f"{ids[k]}\t{k}\t1\n" for k in keys)
    with gzip.open(raw / f"{RELEASE}-domain-edges.txt.gz", "wt", newline="") as f:
        f.writelines(f"{ids[s]}\t{ids[t]}\n" for s, t in sorted(EDGES, key=lambda e: (ids[e[0]], ids[e[1]])))
    seeds = ["alpha.com", "beta.org"]
    monkeypatch.setattr(compute_all, "trusted_seeds", lambda: seeds)
    monkeypatch.setattr(compute_all, "topic_seeds", lambda: {"science": ["gamma.net"], "sport": ["delta.com", "nowhere.org"]})
    return tmp_path


def test_build_subgraph_keeps_only_links_inside_the_top_set(env: Path) -> None:
    stats = build_subgraph.build(5, RELEASE, "1GB")
    assert stats["nodes"] == 5
    assert stats["edges"] == 6  # 9 minus the self-link and the two links touching com.zeta
    A = sp.load_npz(build_subgraph.subgraph_path(5))
    assert A.dtype == np.int8 and A.shape == (5, 5) and A.has_canonical_format
    con = duckdb.connect(str(config.ANALYSIS_DB_PATH), read_only=True)
    node = dict(con.execute("SELECT domain, node FROM subgraph_nodes").fetchall())
    expected = {("alpha.com", "beta.org"), ("alpha.com", "gamma.net"), ("beta.org", "alpha.com"),
                ("gamma.net", "alpha.com"), ("gamma.net", "beta.org"), ("delta.com", "alpha.com")}
    got = {(d1, d2) for d1, i in node.items() for d2, j in node.items() if A[i, j]}
    assert got == expected
    degrees = dict(con.execute("SELECT domain, out_degree FROM subgraph_nodes").fetchall())
    assert degrees == {"alpha.com": 2, "beta.org": 1, "gamma.net": 2, "delta.com": 1, "epsilon.org": 0}
    assert con.execute("SELECT count(*) FROM subgraph_edges").fetchone()[0] == 6


def test_build_subgraph_rejects_vertex_file_without_the_rank_keys(env: Path) -> None:
    with gzip.open(config.RAW_DIR / f"{RELEASE}-domain-vertices.txt.gz", "wt", newline="") as f:
        f.write("0\tcom.somethingelse\t1\n")
    with pytest.raises(FormatError):
        build_subgraph.build(5, RELEASE, "1GB")


def test_compute_all_stores_every_variant_and_resumes(env: Path) -> None:
    build_subgraph.build(5, RELEASE, "1GB")
    compute_all.compute(5, RELEASE, tol=1e-12, max_iter=1000, memory_limit="1GB")
    con = duckdb.connect(str(config.ANALYSIS_DB_PATH), read_only=True)
    variants = con.execute("SELECT algorithm, count(*) FROM variants GROUP BY algorithm").fetchall()
    assert dict(variants) == {"pagerank": 7, "trustrank": 1, "spam_mass": 1, "seed_distance": 1,
                              "topic:science": 1, "topic:sport": 1}
    assert con.execute("SELECT count(*) FROM scores").fetchone()[0] == 12 * 5

    # Stored PageRank equals a direct computation on the saved matrix.
    A = sp.load_npz(build_subgraph.subgraph_path(5))
    h = con.execute("""SELECT params_hash FROM variants WHERE algorithm = 'pagerank'
                       AND label LIKE '%0.85%teleport%'""").fetchone()[0]
    stored = dict(con.execute("SELECT domain_key, score FROM scores WHERE params_hash = ?", [h]).fetchall())
    keys = [k for (k,) in con.execute("SELECT domain_key FROM subgraph_nodes ORDER BY node").fetchall()]
    direct = pagerank(A, alpha=0.85, tol=1e-12, max_iter=1000).scores
    np.testing.assert_allclose([stored[k] for k in keys], direct, atol=1e-12)
    assert abs(sum(stored.values()) - 1) < 1e-9

    runs = con.execute("SELECT algorithm, iterations, residuals, converged FROM runs").fetchall()
    assert any(name == "spam_mass (core PageRank)" for name, *_ in runs)
    for name, iterations, residuals, converged in runs:
        if name != "seed_distance":
            assert len(json.loads(residuals)) == iterations and converged
    assert con.execute("SELECT count(*) FROM disagreements").fetchone()[0] == 5
    con.close()

    # A second run finds every variant stored and recomputes nothing.
    compute_all.compute(5, RELEASE, tol=1e-12, max_iter=1000, memory_limit="1GB")
    con = duckdb.connect(str(config.ANALYSIS_DB_PATH), read_only=True)
    assert con.execute("SELECT count(*) FROM runs").fetchone()[0] == len(runs)


def test_phase2_endpoints(env: Path) -> None:
    from fastapi.testclient import TestClient

    from backend.api.main import create_app

    build_subgraph.build(5, RELEASE, "1GB")
    compute_all.compute(5, RELEASE, tol=1e-13, max_iter=2000, memory_limit="1GB")
    static = env / "static"
    static.mkdir()
    c = TestClient(create_app(db_path=config.DB_PATH, analysis_db_path=config.ANALYSIS_DB_PATH, static_dir=static))

    r = c.get("/api/domain/alpha.com/scores")
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "alpha.com" and body["subgraph_top"] == 5
    assert len(body["scores"]) == 12
    assert {s["algorithm"] for s in body["scores"]} >= {"pagerank", "trustrank", "spam_mass", "seed_distance"}
    assert body["spam_mass"]["threshold"] == 0.7
    assert c.get("/api/domain/alpha.com/scores", params={"spam_threshold": 0.0}).json()["spam_mass"]["threshold"] == 0.0

    r = c.get("/api/domain/zeta.com/scores")
    assert r.status_code == 404 and "outside the top 5" in r.json()["detail"]
    r = c.get("/api/domain/nowhere.org/scores")
    assert r.status_code == 404 and "not in the Common Crawl graph" in r.json()["detail"]

    r = c.get("/api/domain/www.alpha.com/explain")
    assert r.status_code == 200
    ex = r.json()
    assert {x["domain"] for x in ex["contributors"]} == {"beta.org", "gamma.net", "delta.com"}
    assert ex["in_links"] == 3 and ex["alpha"] == 0.85
    total = ex["from_links"]["percent"] + ex["from_teleport"]["percent"] + ex["from_dangling"]["percent"]
    assert abs(total - 100) < 1e-6  # every bit of the score is accounted for
    shares = [x["share"] for x in ex["contributors"]]
    assert shares == sorted(shares, reverse=True)
    assert "alpha.com" in ex["ego"]["nodes"] and ["beta.org", "alpha.com"] in ex["ego"]["edges"]

    trust = next(s for s in body["scores"] if s["algorithm"] == "trustrank")
    r = c.get("/api/domain/alpha.com/explain", params={"params_hash": trust["params_hash"]})
    assert r.status_code == 400

    conv = c.get("/api/convergence").json()
    assert len(conv["runs"]) == 13  # 12 variants, spam mass has two runs
    assert all(len(run["residuals"]) == run["iterations"] for run in conv["runs"] if run["run"] != "seed_distance")

    dis = c.get("/api/disagreements", params={"limit": 3}).json()
    assert len(dis["results"]) == 3
    assert dis["results"][0]["spread"] >= dis["results"][-1]["spread"]

    # Phase 1 routes are unaffected by the more specific Phase 2 routes.
    assert c.get("/api/domain/alpha.com").json()["domain"] == "alpha.com"


def test_phase2_endpoints_before_any_computation(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from backend.api.main import create_app

    c = TestClient(create_app(db_path=tmp_path / "r.duckdb", analysis_db_path=tmp_path / "a.duckdb", static_dir=tmp_path))
    r = c.get("/api/convergence")
    assert r.status_code == 503 and "compute_all" in r.json()["detail"]
