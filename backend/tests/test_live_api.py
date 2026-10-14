"""Phase 3 live endpoints (ego-graph PageRank, what-if, HITS, rate limit) and rank history."""

from __future__ import annotations

from pathlib import Path

import duckdb
import networkx as nx
import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.api import live
from backend.api.live import RateLimiter
from backend.jobs import build_subgraph, compute_all
from backend.tests.test_phase2_jobs import RELEASE, env  # noqa: F401  (fixture)

# Subgraph (top 5): alpha<->beta, alpha<->gamma, gamma->beta, delta->alpha; epsilon has no links inside.
EGO_EDGES = [("alpha.com", "beta.org"), ("alpha.com", "gamma.net"), ("beta.org", "alpha.com"),
             ("gamma.net", "alpha.com"), ("gamma.net", "beta.org"), ("delta.com", "alpha.com")]


@pytest.fixture()
def client(env: Path) -> TestClient:  # noqa: F811
    build_subgraph.build(5, RELEASE, "1GB")
    compute_all.compute(5, RELEASE, tol=1e-12, max_iter=1000, memory_limit="1GB")
    app = __import__("backend.api.main", fromlist=["create_app"]).create_app(
        db_path=config.DB_PATH, analysis_db_path=config.ANALYSIS_DB_PATH, static_dir=env,
        history_db_path=env / "history.duckdb", limiter=RateLimiter(limit=1000))
    return TestClient(app)


def test_live_pagerank_on_the_ego_graph_matches_networkx(client: TestClient) -> None:
    r = client.post("/api/live/pagerank", json={"domain": "alpha.com", "alpha": 0.85})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["nodes"] == 4 and body["links"] == 6 and "neighborhood" in body["label"]  # epsilon is not a neighbour
    expected = nx.pagerank(nx.DiGraph(EGO_EDGES), alpha=0.85, tol=1e-12)
    got = {t["domain"]: t["score"] for t in body["top"]}
    assert got.keys() == expected.keys()
    assert all(abs(got[d] - expected[d]) < 1e-6 for d in got)
    assert body["target"]["score"] == pytest.approx(expected["alpha.com"], abs=1e-6) and body["target"]["rank"] == 1
    assert body["residuals"][-1] < 1e-8 and len(body["residuals"]) == body["iterations"]


def test_live_pagerank_seeds_and_caps(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    seeded = client.post("/api/live/pagerank", json={"domain": "alpha.com", "seeds": ["delta.com"]}).json()
    assert {t["domain"]: t["score"] for t in seeded["top"]}["delta.com"] == pytest.approx(0.15, abs=1e-6)
    r = client.post("/api/live/pagerank", json={"domain": "alpha.com", "seeds": ["epsilon.org"]})
    assert r.status_code == 422 and "epsilon.org" in r.json()["detail"]
    assert client.post("/api/live/pagerank", json={"domain": "nowhere.example"}).status_code == 404
    monkeypatch.setattr(live, "LIVE_MAX_LINKS", 2)
    r = client.post("/api/live/pagerank", json={"domain": "alpha.com"})
    assert r.status_code == 422 and r.json()["cap"] == "max_nodes" and "Reduce max_nodes" in r.json()["detail"]
    monkeypatch.setattr(live, "LIVE_MAX_LINKS", 10**9)
    monkeypatch.setattr(live, "SECONDS_PER_LINK_ITERATION", 0.1)  # budget allows ~7 iterations on 6 links: cut short
    r = client.post("/api/live/pagerank", json={"domain": "alpha.com"})
    assert r.status_code == 503 and "did not converge" in r.json()["detail"] and r.json()["cap"] == "max_nodes"
    monkeypatch.setattr(live, "SECONDS_PER_LINK_ITERATION", 2e-9)
    monkeypatch.setattr(live, "TIME_BUDGET_S", -1.0)
    r = client.post("/api/live/pagerank", json={"domain": "alpha.com"})
    assert r.status_code == 503 and r.json()["cap"] == "max_nodes"


def test_whatif_adds_links_inside_the_neighbourhood(client: TestClient) -> None:
    r = client.post("/api/live/whatif", json={"domain": "beta.org", "links": [{"source": "delta.com", "target": "beta.org"}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["links_after"] == body["links_before"] + 1 and "neighborhood" in body["label"]
    assert body["already_linked"] == []
    again = client.post("/api/live/whatif", json={"domain": "beta.org", "links": [{"source": "gamma.net", "target": "beta.org"}]}).json()
    assert again["already_linked"] == ["gamma.net -> beta.org"] and again["links_after"] == again["links_before"]
    beta = next(x for x in body["results"] if x["domain"] == "beta.org")
    after = nx.pagerank(nx.DiGraph(EGO_EDGES + [("delta.com", "beta.org")]), alpha=0.85, tol=1e-12)
    assert beta["score_after"] > beta["score_before"]
    assert beta["score_after"] == pytest.approx(after["beta.org"], abs=1e-6)
    r = client.post("/api/live/whatif", json={"domain": "beta.org", "links": [{"source": "epsilon.org", "target": "beta.org"}]})
    assert r.status_code == 422 and "epsilon.org" in r.json()["detail"]


def test_live_hits_on_a_root_base_set(client: TestClient) -> None:
    r = client.post("/api/live/hits", json={"roots": ["alpha.com"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["base_size"] == 4 and body["links"] == 6
    g = nx.DiGraph(EGO_EDGES)
    hubs, auths = nx.hits(g, tol=1e-12, max_iter=1000)
    top_auth = max(auths, key=auths.get)
    assert body["authorities"][0]["domain"] == top_auth
    r = client.post("/api/live/hits", json={"roots": ["alpha.com"], "max_nodes": 10})
    assert r.status_code == 200
    r = client.post("/api/live/hits", json={"roots": ["alpha.com"], "max_nodes": 3})
    assert r.status_code == 422


def test_rate_limit_returns_429_with_retry_after(env: Path) -> None:  # noqa: F811
    from backend.api.main import create_app

    c = TestClient(create_app(db_path=config.DB_PATH, analysis_db_path=config.ANALYSIS_DB_PATH, static_dir=env,
                              limiter=RateLimiter(limit=2, window=60)))
    codes = [c.post("/api/live/hits", json={"roots": ["a.com"]}).status_code for _ in range(3)]
    assert codes[:2] != [429, 429] and codes[2] == 429
    r = c.post("/api/live/pagerank", json={"domain": "a.com"})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1


def test_history_endpoint(client: TestClient, env: Path) -> None:  # noqa: F811
    r = client.get("/api/domain/alpha.com/history")
    body = r.json()
    assert [p["release"] for p in body["points"]] == [RELEASE] and body["not_loaded"] == list(config.HISTORY_RELEASES)
    con = duckdb.connect(str(env / "history.duckdb"))
    con.execute("CREATE TABLE history (cur_pos INTEGER, release_pos TINYINT, hc_rank INTEGER, pr_rank INTEGER)")
    con.execute("CREATE TABLE history_releases (release VARCHAR, position INTEGER, domains BIGINT, matched BIGINT)")
    con.execute("CREATE TABLE history_meta (key VARCHAR, value VARCHAR)")
    con.execute("INSERT INTO history_meta VALUES ('current_release', ?)", [RELEASE])
    rel = config.HISTORY_RELEASES
    con.execute("INSERT INTO history_releases VALUES (?, 1, 100, 90), (?, 2, 90, 80)", [rel[0], rel[1]])
    con.execute("INSERT INTO history VALUES (1, 2, 3, 4)")  # alpha.com is position 1 by harmonic centrality
    con.close()
    body = client.get("/api/domain/www.alpha.com/history").json()
    assert body["domain"] == "alpha.com"
    assert [p["release"] for p in body["points"]] == [rel[1], RELEASE]  # oldest first
    assert body["points"][0]["pr_rank"] == 4 and body["not_in_release"] == [rel[0]]
    assert body["not_loaded"] == list(rel[2:])
    assert client.get("/api/domain/nowhere.example/history").status_code == 404
