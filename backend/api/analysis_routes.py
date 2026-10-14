"""Phase 2 endpoints: per-domain scores, score explanations, convergence and disagreements."""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.domains import lookup_candidates, normalize_query

from .analysis import Analysis
from .db import Database

DEFAULT_SPAM_THRESHOLD = 0.7


class VariantScore(BaseModel):
    params_hash: str
    algorithm: str
    label: str
    params: dict[str, Any]
    score: float
    percentile: float
    rank: int


class SpamMass(BaseModel):
    relative_mass: float
    threshold: float
    flagged: bool


class ScoresResponse(BaseModel):
    domain: str
    domain_key: str
    release: str
    subgraph_top: int
    subgraph_nodes: int
    matched_from: str | None
    scores: list[VariantScore]
    spam_mass: SpamMass | None


class Contributor(BaseModel):
    domain: str
    score: float
    out_degree: int
    share: float      # alpha * p(v) / out(v)
    percent: float    # share as a percentage of the domain's score


class Part(BaseModel):
    share: float
    percent: float


class EgoGraph(BaseModel):
    nodes: list[str]
    edges: list[tuple[str, str]]


class ExplainResponse(BaseModel):
    domain: str
    params_hash: str
    label: str
    alpha: float
    score: float
    nodes: int
    in_links: int
    shown: int
    contributors: list[Contributor]
    from_links: Part
    from_teleport: Part
    from_dangling: Part
    ego: EgoGraph


class RunHistory(BaseModel):
    params_hash: str
    run: str
    label: str
    iterations: int
    residuals: list[float]
    seconds: float
    converged: bool
    info: dict[str, float]


class ConvergenceResponse(BaseModel):
    release: str
    subgraph_top: int
    runs: list[RunHistory]


class Disagreement(BaseModel):
    domain: str
    pagerank_percentile: float
    trustrank_percentile: float
    seed_distance_percentile: float
    spread: float


class DisagreementsResponse(BaseModel):
    release: str
    subgraph_top: int
    results: list[Disagreement]


def register_analysis_routes(app: FastAPI, db: Database, analysis: Analysis) -> None:
    """Add the Phase 2 routes. Call before the catch-all /api/domain/{query:path} route."""

    def locate(query: str) -> tuple[tuple, str | None] | JSONResponse:
        """The subgraph node for a query, or a 404 that says why it is missing."""
        domain = normalize_query(query)
        for candidate in lookup_candidates(domain):
            row = analysis.node(candidate)
            if row is not None:
                return row, (domain if candidate != domain else None)
        top = analysis.meta()["top"]
        ranks = db.lookup(lookup_candidates(domain))
        if ranks:
            hc_rank = next(iter(ranks.values()))[5]
            detail = (
                f"This domain is in the Common Crawl graph (harmonic centrality rank #{hc_rank:,}) but outside the "
                f"top {top:,} domains that Linkflow Lab computes its own scores on."
            )
        else:
            detail = "Domain not in the Common Crawl graph for this release"
        return JSONResponse(status_code=404, content={"detail": detail, "domain": domain, "subgraph_top": top})

    @app.get("/api/domain/{query:path}/scores", response_model=ScoresResponse)
    def domain_scores(
        query: str, spam_threshold: float = Query(DEFAULT_SPAM_THRESHOLD, ge=0, le=1)
    ) -> ScoresResponse | JSONResponse:
        found = locate(query)
        if isinstance(found, JSONResponse):
            return found
        (node, key, domain, _hc_rank, _out, _in), matched_from = found
        meta = analysis.meta()
        rows = {h: (s, p, r) for h, s, p, r in analysis.scores(key)}
        scores = [
            VariantScore(**v, score=rows[v["params_hash"]][0], percentile=rows[v["params_hash"]][1], rank=rows[v["params_hash"]][2])
            for v in meta["variants"]
            if v["params_hash"] in rows
        ]
        mass = next((s for s in scores if s.algorithm == "spam_mass"), None)
        return ScoresResponse(
            domain=domain,
            domain_key=key,
            release=meta["release"],
            subgraph_top=meta["top"],
            subgraph_nodes=meta["nodes"],
            matched_from=matched_from,
            scores=scores,
            spam_mass=SpamMass(relative_mass=mass.score, threshold=spam_threshold, flagged=mass.score > spam_threshold)
            if mass
            else None,
        )

    @app.get("/api/domain/{query:path}/explain", response_model=ExplainResponse)
    def domain_explain(query: str, params_hash: str | None = None) -> ExplainResponse | JSONResponse:
        found = locate(query)
        if isinstance(found, JSONResponse):
            return found
        (node, key, domain, _hc_rank, _out, in_degree), _ = found
        variant = analysis.variant(params_hash) if params_hash else analysis.default_pagerank()
        if variant is None:
            return JSONResponse(status_code=404, content={"detail": f"No stored run with params_hash {params_hash}"})
        params = variant["params"]
        if variant["algorithm"] != "pagerank" or params.get("dangling") not in ("teleport", "uniform"):
            return JSONResponse(
                status_code=400,
                content={"detail": "Explanations are defined for PageRank runs with teleport or uniform dangling handling"},
            )
        alpha = float(params["alpha"])
        n = analysis.meta()["nodes"]
        result = analysis.explain(node, variant["params_hash"])
        score = next(s for h, s, _p, _r in analysis.scores(key) if h == variant["params_hash"])

        def pct(x: float) -> float:
            return 100.0 * x / score if score > 0 else 0.0

        contributors = [
            Contributor(domain=d, score=s, out_degree=o, share=alpha * per, percent=pct(alpha * per))
            for d, _node, s, o, per in result["top"]
        ]
        links = alpha * sum(per for *_rest, per in result["contributors"])
        teleport = (1.0 - alpha) / n  # uniform teleport vector
        dangling = alpha * result["dangling_mass"] / n  # teleport and uniform dangling both spread it as 1/n
        names = {node: domain} | {nid: d for d, nid, *_ in result["top"]}
        return ExplainResponse(
            domain=domain,
            params_hash=variant["params_hash"],
            label=variant["label"],
            alpha=alpha,
            score=score,
            nodes=n,
            in_links=int(in_degree),
            shown=len(contributors),
            contributors=contributors,
            from_links=Part(share=links, percent=pct(links)),
            from_teleport=Part(share=teleport, percent=pct(teleport)),
            from_dangling=Part(share=dangling, percent=pct(dangling)),
            ego=EgoGraph(nodes=list(names.values()), edges=[(names[s], names[t]) for s, t in result["edges"]]),
        )

    @app.get("/api/convergence", response_model=ConvergenceResponse)
    def convergence() -> ConvergenceResponse:
        meta = analysis.meta()
        runs = [
            RunHistory(
                params_hash=h, run=run, label=label, iterations=it, residuals=json.loads(res),
                seconds=sec, converged=conv, info=json.loads(info),
            )
            for h, run, label, it, res, sec, conv, info in analysis.convergence()
        ]
        return ConvergenceResponse(release=meta["release"], subgraph_top=meta["top"], runs=runs)

    @app.get("/api/disagreements", response_model=DisagreementsResponse)
    def disagreements(limit: int = Query(100, ge=1, le=1000)) -> DisagreementsResponse:
        meta = analysis.meta()
        return DisagreementsResponse(
            release=meta["release"],
            subgraph_top=meta["top"],
            results=[
                Disagreement(domain=d, pagerank_percentile=a, trustrank_percentile=b, seed_distance_percentile=c, spread=s)
                for d, a, b, c, s in analysis.disagreements(limit)
            ],
        )

    @app.get("/api/analysis/meta")
    def analysis_meta() -> dict[str, Any]:
        return analysis.meta()
