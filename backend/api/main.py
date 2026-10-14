"""Linkflow Lab HTTP API.

    uvicorn backend.api.main:app --port 8000
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import config
from backend.domains import InvalidDomain, lookup_candidates, normalize_query, parent_domains

from .analysis import Analysis
from .analysis_routes import register_analysis_routes
from .live import RateLimiter, register_live_routes
from .db import Database, DataNotLoaded, ReleaseInfo

NOT_FOUND_MESSAGE = "Domain not in the Common Crawl graph for this release"
MAX_COMPARE = 10
MAX_TOP = 1000


class Metric(BaseModel):
    """One Common Crawl metric for a domain. Percentile = mid-rank: share of domains scoring lower, counting half of the ties."""

    value: float
    rank: int
    percentile: float


class DomainRanks(BaseModel):
    domain: str
    domain_key: str
    release: str
    n_hosts: int
    harmonic_centrality: Metric
    pagerank: Metric
    total_domains: int
    matched_from: str | None = None


class NotFound(BaseModel):
    query: str
    domain: str
    detail: str
    suggestions: list[str]


class Invalid(BaseModel):
    query: str
    detail: str


class CompareResponse(BaseModel):
    release: str
    results: list[DomainRanks]
    not_found: list[NotFound]
    invalid: list[Invalid]


class TopResponse(BaseModel):
    release: str
    metric: str
    limit: int
    results: list[DomainRanks]


class MetaResponse(BaseModel):
    release: str
    source_url: str
    domains: int
    loaded_at: str


def _to_model(row: tuple, total: int, matched_from: str | None = None) -> DomainRanks:
    domain, key, release, n_hosts, hc, hc_rank, hc_pct, pr, pr_rank, pr_pct = row
    return DomainRanks(
        domain=domain,
        domain_key=key,
        release=release,
        n_hosts=n_hosts,
        harmonic_centrality=Metric(value=hc, rank=hc_rank, percentile=hc_pct),
        pagerank=Metric(value=pr, rank=pr_rank, percentile=pr_pct),
        total_domains=total,
        matched_from=matched_from,
    )


def create_app(
    db_path: Path | None = None, static_dir: Path | None = None, analysis_db_path: Path | None = None,
    history_db_path: Path | None = None, limiter: RateLimiter | None = None,
) -> FastAPI:
    """Build the app. ``static_dir`` (the built frontend) is served at / when it exists."""
    db = Database(db_path or config.DB_PATH, config.RELEASE)
    app = FastAPI(title="Linkflow Lab API", version="0.1.0")

    @app.exception_handler(DataNotLoaded)
    async def data_not_loaded(_: Request, exc: DataNotLoaded) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(InvalidDomain)
    async def invalid_domain(_: Request, exc: InvalidDomain) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    def resolve(queries: list[str]) -> tuple[list[DomainRanks], list[NotFound], list[Invalid], ReleaseInfo]:
        info = db.release()
        normalized: list[tuple[str, str]] = []
        invalid: list[Invalid] = []
        for q in queries:
            try:
                normalized.append((q, normalize_query(q)))
            except InvalidDomain as exc:
                invalid.append(Invalid(query=q, detail=str(exc)))
        wanted = {c for _, d in normalized for c in lookup_candidates(d) + parent_domains(d)}
        rows = db.lookup(sorted(wanted))
        found: list[DomainRanks] = []
        missing: list[NotFound] = []
        seen: set[str] = set()  # "Example.com" and "www.example.com" are the same domain: list it once
        for q, d in normalized:
            hit = next((c for c in lookup_candidates(d) if c in rows), None)
            key = hit if hit is not None else d
            if key in seen:
                continue
            seen.add(key)
            if hit is not None:
                found.append(_to_model(rows[hit], info.domains, matched_from=d if hit != d else None))
            else:
                # Only the most specific existing parent: news.bbc.co.uk -> bbc.co.uk, not also co.uk.
                suggestions = [p for p in parent_domains(d) if p in rows][:1]
                missing.append(NotFound(query=q, domain=d, detail=NOT_FOUND_MESSAGE, suggestions=suggestions))
        return found, missing, invalid, info

    @app.get("/api/meta", response_model=MetaResponse)
    def meta() -> MetaResponse:
        info = db.release()
        return MetaResponse(release=info.release, source_url=info.source_url, domains=info.domains, loaded_at=info.loaded_at)

    # Phase 2 routes first: /api/domain/{d}/scores must win over the catch-all below.
    analysis = Analysis(analysis_db_path or config.ANALYSIS_DB_PATH)
    register_analysis_routes(app, db, analysis)
    register_live_routes(app, db, analysis, history_db_path or config.HISTORY_DB_PATH, limiter)

    @app.get(
        "/api/domain/{query:path}",  # :path so a pasted URL with slashes still reaches the handler
        response_model=DomainRanks,
        responses={404: {"model": NotFound}, 400: {"model": Invalid}},
    )
    def domain(query: str) -> DomainRanks | JSONResponse:
        normalize_query(query)  # raises InvalidDomain -> 400
        found, missing, _, _ = resolve([query])
        if found:
            return found[0]
        return JSONResponse(status_code=404, content=missing[0].model_dump())

    @app.get("/api/compare", response_model=CompareResponse)
    def compare(d: str = Query(..., description="Comma-separated domains, at most 10")) -> CompareResponse | JSONResponse:
        queries = [q.strip() for q in d.split(",") if q.strip()]
        queries = list(dict.fromkeys(queries))
        if not queries:
            return JSONResponse(status_code=400, content={"detail": "Give at least one domain in ?d="})
        if len(queries) > MAX_COMPARE:
            return JSONResponse(
                status_code=400, content={"detail": f"Compare at most {MAX_COMPARE} domains at a time ({len(queries)} given)"}
            )
        found, missing, invalid, info = resolve(queries)
        return CompareResponse(release=info.release, results=found, not_found=missing, invalid=invalid)

    @app.get("/api/top", response_model=TopResponse)
    def top(
        metric: Literal["pagerank", "harmonic"] = "pagerank",
        limit: int = Query(100, ge=1, le=MAX_TOP),
    ) -> TopResponse:
        info = db.release()
        rows = db.top(metric, limit)
        return TopResponse(
            release=info.release, metric=metric, limit=limit, results=[_to_model(r, info.domains) for r in rows]
        )

    static = static_dir if static_dir is not None else config.REPO_ROOT / "frontend" / "dist"
    if static.is_dir() and (static / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path == "api" or path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not Found")
            root = os.path.normpath(os.path.abspath(static))
            candidate = os.path.normpath(os.path.join(root, path))
            if path and candidate.startswith(root + os.sep) and os.path.isfile(candidate):
                return FileResponse(candidate)
            # index.html names the current hashed bundles: browsers must revalidate it, or after a rebuild a cached
            # copy requests chunks that no longer exist and the app fails to load.
            return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
