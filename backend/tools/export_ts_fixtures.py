"""Export reference results from the Python algorithms for the TypeScript port tests.

    python -m backend.tools.export_ts_fixtures

Writes frontend/src/algorithms/fixtures.json. The Vitest suite checks that the in-browser
Playground implementations reproduce these numbers.
"""

from __future__ import annotations

import json

import numpy as np

from backend import config
from backend.algorithms import DANGLING_STRATEGIES, harmonic_centrality, hits, pagerank
from backend.algorithms.common import seed_vector
from backend.tests.graphs import from_edges, random_digraph

OUT = config.REPO_ROOT / "frontend" / "src" / "algorithms" / "fixtures.json"
TOL, MAX_ITER = 1e-12, 2000


def named_graphs() -> list[tuple[str, int, list[tuple[int, int]]]]:
    graphs: list[tuple[str, int, list[tuple[int, int]]]] = [
        ("paper-figure-3", 3, [(0, 1), (0, 2), (1, 2), (2, 0)]),
        ("rank-sink", 3, [(2, 0), (0, 1), (1, 0)]),
        ("dangling-chain", 5, [(0, 1), (1, 0), (1, 2), (2, 3), (3, 4)]),
        ("dag", 4, [(0, 1), (1, 2), (2, 3)]),
        ("single-node", 1, []),
        ("isolated-nodes", 5, []),
        ("self-loops", 4, [(0, 0), (0, 1), (1, 2), (2, 2), (2, 3)]),
        ("star-into-dangling", 4, [(0, 1), (0, 2), (0, 3)]),
    ]
    rng = np.random.default_rng(2026)
    for n in (25, 60, 120):
        A, _ = random_digraph(rng, n, mean_out=3.0, dangling_share=0.25)
        rows, cols = A.nonzero()
        graphs.append((f"random-{n}", n, sorted(zip(rows.tolist(), cols.tolist()))))
    return graphs


def main() -> None:
    cases = []
    for name, n, edges in named_graphs():
        A = from_edges(n, edges)
        seeds = [0, n - 1] if n > 2 else [0]
        pr = {}
        for dangling in DANGLING_STRATEGIES:
            for teleport_name, teleport in (("uniform", None), ("seeds", seed_vector(n, seeds))):
                for alpha in (0.5, 0.85):
                    r = pagerank(A, alpha=alpha, tol=TOL, max_iter=MAX_ITER, teleport=teleport, dangling=dangling)
                    pr[f"{dangling}|{teleport_name}|{alpha}"] = {
                        "scores": r.scores.tolist(),
                        "iterations": r.iterations,
                        "converged": r.converged,
                    }
        h = hits(A, tol=TOL, max_iter=MAX_ITER)
        cases.append(
            {
                "name": name,
                "n": n,
                "edges": edges,
                "seeds": seeds,
                "pagerank": pr,
                "hits": {"hubs": h.hubs.tolist(), "authorities": h.authorities.tolist(), "converged": h.converged},
                "harmonic": harmonic_centrality(A).tolist(),
            }
        )
    OUT.write_text(json.dumps({"tol": TOL, "maxIter": MAX_ITER, "cases": cases}, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(cases)} graphs)")


if __name__ == "__main__":
    main()
