"""Phase 3 endpoints: live PageRank / what-if / HITS on a domain's neighbourhood, and rank history.

Live computations run on the domain's ego graph: its 2-hop neighbourhood (in- and out-links) within the
top-1M subgraph, capped at ``max_nodes`` (keeping the highest-PageRank neighbours). They are local
approximations: links from outside the neighbourhood are ignored.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Literal

import duckdb
import numpy as np
import scipy.sparse as sp
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend import config
from backend.algorithms import hits, pagerank
from backend.algorithms.common import InLinks, binary_csr, gather_rows, in_links
from backend.algorithms.hits import KLEINBERG_IN_CAP, base_subgraph
from backend.domains import lookup_candidates, normalize_query
from backend.jobs.build_subgraph import subgraph_path

from .analysis import Analysis
from .db import Database, DataNotLoaded

MAX_EGO_NODES = 50_000
LIVE_MAX_LINKS = 30_000_000  # measured: a 50,000-domain neighbourhood has up to ~22M links
TIME_BUDGET_S = 5.0
SECONDS_PER_LINK_ITERATION = 2e-9  # measured ~1.2 ns per link per PageRank iteration on the reference laptop
MAX_ITER = 200
RATE_LIMIT = 10
RATE_WINDOW_S = 60.0
log = logging.getLogger("linkflow.live")
APPROXIMATION = "Local approximation on this domain's neighborhood"


class RateLimiter:
    """At most ``limit`` requests per ``window`` seconds per client IP (sliding window, in memory)."""

    def __init__(self, limit: int = RATE_LIMIT, window: float = RATE_WINDOW_S) -> None:
        self.limit, self.window = limit, window
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def __call__(self, request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with self._lock:
            q = self._hits[ip]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                retry = int(self.window - (now - q[0])) + 1
                raise HTTPException(
                    status_code=429,
                    detail=f"Live analysis is limited to {self.limit} requests per minute. Try again in {retry} s.",
                    headers={"Retry-After": str(retry)},
                )
            q.append(now)


class LiveGraph:
    """The subgraph, its in-links, domain names and reference PageRank, loaded on first use (~1 GB)."""

    def __init__(self, analysis: Analysis) -> None:
        self.analysis = analysis
        self._lock = threading.Lock()
        self.A: sp.csr_matrix | None = None
        self.links: InLinks | None = None
        self.domains: list[str] = []
        self.node_of: dict[str, int] = {}
        self.reference: np.ndarray = np.zeros(0)

    def ensure(self) -> None:
        with self._lock:
            if self.A is not None:
                return
            meta = self.analysis.meta()
            path = subgraph_path(meta["top"])
            if not path.exists():
                raise DataNotLoaded("The subgraph matrix is missing. Run: python -m backend.jobs.build_subgraph")
            A = sp.load_npz(path).tocsr()
            self.domains = [d for (d,) in self.analysis._query("SELECT domain FROM subgraph_nodes ORDER BY node")]
            self.node_of = {d: i for i, d in enumerate(self.domains)}
            h = self.analysis.default_pagerank()["params_hash"]
            ref = self.analysis._query(
                "SELECT n.node, s.score FROM scores s JOIN subgraph_nodes n USING (domain_key) WHERE s.params_hash = ?", [h]
            )
            self.reference = np.zeros(A.shape[0])
            idx = np.array([r[0] for r in ref], dtype=np.int64)
            self.reference[idx] = np.array([r[1] for r in ref])
            self.links = in_links(A)
            self.A = A

    def source(self) -> dict[str, Any]:
        meta = self.analysis.meta()
        return {"release": meta["release"], "subgraph_top": meta["top"]}

    def node(self, query: str) -> int:
        domain = normalize_query(query)
        for candidate in lookup_candidates(domain):
            if candidate in self.node_of:
                return self.node_of[candidate]
        raise HTTPException(status_code=404, detail=f"{domain} is not in the top {len(self.domains):,}-domain subgraph")

    def ego(self, center: int, max_nodes: int) -> np.ndarray:
        """Sorted node ids of the 2-hop neighbourhood (both directions), capped by reference PageRank."""
        assert self.A is not None and self.links is not None
        A, L = self.A, self.links
        mask = np.zeros(A.shape[0], dtype=bool)
        first = np.unique(np.concatenate([A.indices[A.indptr[center]:A.indptr[center + 1]],
                                          L.sources[L.indptr[center]:L.indptr[center + 1]]]))
        mask[first] = True
        for i in range(0, first.size, 20_000):  # bounded memory for hubs with huge 1-hop sets
            chunk = first[i:i + 20_000]
            mask[gather_rows(A.indptr, A.indices, chunk)] = True
            mask[gather_rows(L.indptr, L.sources, chunk)] = True
        mask[center] = False
        cand = np.flatnonzero(mask)
        if cand.size > max_nodes - 1:
            keep = np.argpartition(-self.reference[cand], max_nodes - 2)[: max_nodes - 1]
            cand = cand[keep]
        return np.sort(np.concatenate([[center], cand]))


class LivePageRankRequest(BaseModel):
    domain: str
    alpha: float = Field(0.85, ge=0, le=1)
    dangling: Literal["teleport", "uniform", "self_loop", "remove_readd"] = "teleport"
    seeds: list[str] = Field(default_factory=list, max_length=100)
    max_nodes: int = Field(MAX_EGO_NODES, ge=10, le=MAX_EGO_NODES)


class Link(BaseModel):
    source: str
    target: str


class WhatIfRequest(LivePageRankRequest):
    links: list[Link] = Field(..., min_length=1, max_length=20)


class HitsRequest(BaseModel):
    roots: list[str] = Field(..., min_length=1, max_length=10)
    max_in_per_root: int = Field(KLEINBERG_IN_CAP, ge=1, le=KLEINBERG_IN_CAP)
    max_nodes: int = Field(MAX_EGO_NODES, ge=10, le=MAX_EGO_NODES)


def _too_big(links: int, max_nodes: int) -> JSONResponse:
    suggestion = max(100, int(max_nodes * LIVE_MAX_LINKS / links * 0.9))
    return JSONResponse(status_code=422, content={
        "detail": f"This neighbourhood has {links:,} links, above the live limit of {LIVE_MAX_LINKS:,} that keeps a "
                  f"computation under {TIME_BUDGET_S:.0f} s. Reduce max_nodes (for example to {suggestion:,}).",
        "cap": "max_nodes", "suggested_max_nodes": suggestion})


def _ranks(scores: np.ndarray) -> np.ndarray:
    order = np.argsort(-scores, kind="stable")
    ranks = np.empty(scores.size, dtype=np.int64)
    ranks[order] = np.arange(1, scores.size + 1)
    return ranks


def register_live_routes(app: FastAPI, db: Database, analysis: Analysis, history_db: Path,
                         limiter: RateLimiter | None = None) -> None:
    """Add /api/live/* (rate limited) and /api/domain/{d}/history. Call before the catch-all domain route."""
    graph = LiveGraph(analysis)
    limit = limiter or RateLimiter()

    def warm() -> None:
        try:
            graph.ensure()
            log.info("live graph loaded: %s domains", f"{len(graph.domains):,}")
        except Exception as exc:  # data missing or being written: load on first request instead
            log.warning("live graph not preloaded: %s", exc)

    # Preload when the server starts (not on import, and not in tests that skip startup events).
    app.router.on_startup.append(lambda: threading.Thread(target=warm, daemon=True).start())

    def setup(req: LivePageRankRequest) -> tuple[int, np.ndarray, sp.csr_matrix, np.ndarray | None]:
        graph.ensure()
        center = graph.node(req.domain)
        nodes = graph.ego(center, req.max_nodes)
        sub = binary_csr(graph.A[nodes][:, nodes])  # type: ignore[index]  # scipy indexing: fastest at this size
        teleport = None
        if req.seeds:
            pos = {n: i for i, n in enumerate(nodes)}
            seed_nodes = [graph.node(s) for s in req.seeds]
            outside = [s for s, n in zip(req.seeds, seed_nodes) if n not in pos]
            if outside:
                raise HTTPException(422, detail=f"Seeds outside this neighbourhood: {', '.join(outside)}")
            teleport = np.zeros(nodes.size)
            teleport[[pos[n] for n in seed_nodes]] = 1.0
        return center, nodes, sub, teleport

    def iteration_budget(t0: float, links: int, runs: int) -> int:
        """Iterations that fit in what is left of the time budget: remaining / (runs * links * cost per link)."""
        remaining = TIME_BUDGET_S - (time.perf_counter() - t0) - 0.25
        return max(0, min(MAX_ITER, int(remaining / (runs * max(links, 1) * SECONDS_PER_LINK_ITERATION))))

    def run_pr(sub: sp.csr_matrix, req: LivePageRankRequest, teleport: np.ndarray | None, max_iter: int) -> Any:
        return pagerank(sub, alpha=req.alpha, dangling=req.dangling, teleport=teleport, tol=1e-8, max_iter=max_iter)

    def out_of_budget(result: Any, max_iter: int, links: int, max_nodes: int) -> JSONResponse | None:
        """A run cut short by the time budget (not by the 200-iteration limit) is an error naming the caps."""
        if max_iter >= MAX_ITER or (result is not None and result.converged):
            return None
        done = 0 if result is None else result.iterations
        return JSONResponse(status_code=503, content={
            "detail": f"PageRank did not converge within the {TIME_BUDGET_S:.0f} s budget ({done} iterations on {links:,} links). "
                      f"Reduce max_nodes (for example to {max(100, max_nodes // 2):,}) or lower α, which converges faster.",
            "cap": "max_nodes"})

    def over_time(t0: float) -> JSONResponse | None:
        elapsed = time.perf_counter() - t0
        if elapsed > TIME_BUDGET_S:
            return JSONResponse(status_code=503, content={
                "detail": f"The computation took {elapsed:.1f} s, over the {TIME_BUDGET_S:.0f} s budget. Reduce max_nodes.",
                "cap": "max_nodes"})
        return None

    @app.post("/api/live/pagerank", dependencies=[Depends(limit)])
    def live_pagerank(req: LivePageRankRequest) -> Any:
        graph.ensure()  # one-time load (~15 s) is not part of the per-request budget
        t0 = time.perf_counter()
        center, nodes, sub, teleport = setup(req)
        if sub.nnz > LIVE_MAX_LINKS:
            return _too_big(sub.nnz, req.max_nodes)
        budget = iteration_budget(t0, sub.nnz, 1)
        result = run_pr(sub, req, teleport, budget) if budget else None
        if (cut := out_of_budget(result, budget, sub.nnz, req.max_nodes)) is not None:
            return cut
        if (late := over_time(t0)) is not None:
            return late
        ranks = _ranks(result.scores)
        c = int(np.searchsorted(nodes, center))
        top = np.argsort(-result.scores)[:25]
        return {
            **graph.source(), "domain": graph.domains[center], "label": APPROXIMATION, "nodes": int(nodes.size), "links": int(sub.nnz),
            "capped": bool(nodes.size >= req.max_nodes), "alpha": req.alpha, "dangling": req.dangling, "seeds": req.seeds,
            "iterations": result.iterations, "residuals": result.residuals, "converged": result.converged,
            "seconds": round(time.perf_counter() - t0, 3),
            "target": {"score": float(result.scores[c]), "rank": int(ranks[c])},
            "top": [{"domain": graph.domains[nodes[i]], "score": float(result.scores[i])} for i in top],
        }

    @app.post("/api/live/whatif", dependencies=[Depends(limit)])
    def live_whatif(req: WhatIfRequest) -> Any:
        graph.ensure()  # one-time load (~15 s) is not part of the per-request budget
        t0 = time.perf_counter()
        center, nodes, sub, teleport = setup(req)
        pos = {int(n): i for i, n in enumerate(nodes)}
        added: list[tuple[int, int]] = []
        existing: list[str] = []
        for link in req.links:
            s, t = graph.node(link.source), graph.node(link.target)
            missing = [d for d, n in ((link.source, s), (link.target, t)) if n not in pos]
            if missing:
                raise HTTPException(422, detail=f"Outside this domain's neighbourhood: {', '.join(missing)}")
            if s != t:
                added.append((pos[s], pos[t]))
                if sub[pos[s], pos[t]]:
                    existing.append(f"{graph.domains[s]} -> {graph.domains[t]}")
        if sub.nnz + len(added) > LIVE_MAX_LINKS:
            return _too_big(sub.nnz, req.max_nodes)
        budget = iteration_budget(t0, sub.nnz, 2)
        before = run_pr(sub, req, teleport, budget) if budget else None
        if (cut := out_of_budget(before, budget, sub.nnz, req.max_nodes)) is not None:
            return cut
        extra = sp.csr_matrix((np.ones(len(added), dtype=np.int8), ([a for a, _ in added], [b for _, b in added])), shape=sub.shape)
        plus = (sub + extra).tocsr()
        plus.data[:] = 1
        plus = plus.astype(np.int8)
        plus.sort_indices()
        after = run_pr(plus, req, teleport, budget)
        if (cut := out_of_budget(after, budget, plus.nnz, req.max_nodes)) is not None:
            return cut
        if (late := over_time(t0)) is not None:
            return late
        rb, ra = _ranks(before.scores), _ranks(after.scores)
        watched = dict.fromkeys([pos[center]] + [b for _, b in added])
        return {
            **graph.source(), "domain": graph.domains[center], "label": APPROXIMATION, "nodes": int(nodes.size),
            "alpha": req.alpha, "dangling": req.dangling, "seeds": req.seeds, "links_before": int(sub.nnz), "links_after": int(plus.nnz), "already_linked": existing, "seconds": round(time.perf_counter() - t0, 3),
            "results": [{"domain": graph.domains[nodes[i]], "score_before": float(before.scores[i]),
                         "score_after": float(after.scores[i]), "rank_before": int(rb[i]), "rank_after": int(ra[i])}
                        for i in watched],
        }

    @app.post("/api/live/hits", dependencies=[Depends(limit)])
    def live_hits(req: HitsRequest) -> Any:
        graph.ensure()
        t0 = time.perf_counter()
        A, L = graph.A, graph.links
        assert A is not None and L is not None
        roots = np.array(sorted({graph.node(r) for r in req.roots}), dtype=np.int64)
        members = [roots, gather_rows(A.indptr, A.indices, roots)]
        for r in roots:  # Kleinberg: up to d in-neighbours per root, highest reference PageRank first
            preds = L.sources[L.indptr[r]:L.indptr[r + 1]]
            if preds.size > req.max_in_per_root:
                preds = preds[np.lexsort((preds, -graph.reference[preds]))[: req.max_in_per_root]]
            members.append(preds.astype(np.int64))
        base = np.unique(np.concatenate(members))
        if base.size > req.max_nodes:
            return JSONResponse(status_code=422, content={
                "detail": f"The base set has {base.size:,} domains, above max_nodes = {req.max_nodes:,}. "
                          "Use fewer or less-linked root domains.", "cap": "roots"})
        sub = base_subgraph(A, base)
        if sub.nnz > LIVE_MAX_LINKS:
            return _too_big(sub.nnz, req.max_nodes)
        result = hits(sub, tol=1e-8, max_iter=100)
        if (late := over_time(t0)) is not None:
            return late

        def top(v: np.ndarray) -> list[dict[str, Any]]:
            return [{"domain": graph.domains[base[i]], "score": float(v[i])} for i in np.argsort(-v)[:25]]

        return {**graph.source(), "roots": [graph.domains[r] for r in roots], "max_in_per_root": req.max_in_per_root, "base_size": int(base.size), "links": int(sub.nnz),
                "iterations": result.iterations, "residuals": result.residuals, "converged": result.converged,
                "seconds": round(time.perf_counter() - t0, 3),
                "authorities": top(result.authorities), "hubs": top(result.hubs)}

    @app.get("/api/domain/{query:path}/history")
    def domain_history(query: str) -> Any:
        domain = normalize_query(query)
        candidates = lookup_candidates(domain)
        rows = db.lookup(candidates)
        hit = next((c for c in candidates if c in rows), None)
        if hit is None:
            return JSONResponse(status_code=404, content={"detail": "Domain not in the Common Crawl graph for this release"})
        cur = rows[hit]
        info = db.release()
        points: list[dict[str, Any]] = []
        missing: list[str] = []
        if history_db.exists():
            try:
                con = duckdb.connect(str(history_db), read_only=True)
            except duckdb.IOException:
                con = None
            if con is not None:
                try:
                    # History rows are keyed by the domain's harmonic position in the release they were matched to.
                    meta = dict(con.execute("SELECT key, value FROM history_meta").fetchall())
                    loaded = con.execute("SELECT release, position, domains FROM history_releases ORDER BY position DESC").fetchall()
                    found = dict((pos, (hc, pr)) for pos, hc, pr in con.execute(
                        "SELECT release_pos, hc_rank, pr_rank FROM history WHERE cur_pos = ?", [cur[5]]
                    ).fetchall())
                    if meta.get("current_release") != info.release:
                        loaded, found = [], {}
                except duckdb.CatalogException:
                    loaded, found = [], {}
                finally:
                    con.close()
                for release, pos, total in loaded:
                    if pos in found:
                        hc_rank, pr_rank = found[pos]
                        points.append({"release": release, "hc_rank": hc_rank, "pr_rank": pr_rank, "domains": total})
                    else:
                        missing.append(release)
        points.append({"release": info.release, "hc_rank": cur[5], "pr_rank": cur[8], "domains": info.domains})
        pending = [r for r in config.HISTORY_RELEASES if r not in {p["release"] for p in points} and r not in missing]
        return {"domain": cur[0], "points": points, "not_in_release": missing, "not_loaded": pending}
