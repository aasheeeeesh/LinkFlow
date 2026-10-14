# Phase 3 report: live analysis, weighted PageRank, rank history

Completed 2026-10-12 01:45 IST; confirmed by the user 2026-10-12. Release `cc-main-2026-may-jun-jul`, top 1,000,000 domains subgraph (99,709,237 links).

## What was built

| Spec item | Where | Verified on real data |
|---|---|---|
| Ego graph: 2-hop neighbourhood (in- and out-links), capped at 50,000 by highest reference PageRank | `backend/api/live.py` `LiveGraph.ego` | yes |
| `POST /api/live/pagerank` (α, dangling strategy, seed set) with residuals; 5 s budget or an error naming the cap | `live.py`, `frontend/src/pages/Live.tsx` | wikipedia.org at 50k: 16.8M links, 69 iterations, 3.4 s; α = 0.99 → 503 "Reduce max_nodes (for example to 25,000) or lower α" |
| `POST /api/live/whatif`: hypothetical links inside the neighbourhood, score and rank before/after, labelled "Local approximation on this domain's neighborhood" | same | bbc.co.uk at 20k: one new link moved it #138 → #116 (score ×1.13) in 1.9 s; links that already exist are reported |
| `POST /api/live/hits` on a base set from user roots | same | roots python.org, rust-lang.org: base set 8,012 domains, 1.45M links, 18 iterations, 0.44 s |
| Weighted PageRank, weight = host-level link count | `backend/jobs/build_host_weights.py`, variant 19 in `compute_all` | 52.7M hosts mapped; 99.7M weighted links; 58 iterations, 55 s |
| Rank history from 5 earlier releases (names from the official listing) and a chart on the domain page | `backend/jobs/load_history.py`, `GET /api/domain/{d}/history`, `analysis/RankHistory.tsx` | 484.8M rows; lookup ~0.3 s; chart verified for bbc.co.uk |
| Rate limit: 10 live requests per minute per IP (429 + Retry-After) | `RateLimiter` in `live.py` | tests |

## Results worth knowing

- Weighted vs unweighted PageRank (α = 0.85) over the 1M domains: Spearman rank correlation 0.967, median rank
  change 25,222 positions, top 8 almost unchanged (twitter.com 8 → 6).
- A domain's 2-hop neighbourhood almost always fills the 50,000 cap and is dense (16–22M links), so live PageRank
  needed a faster path: for graphs up to 50M links `in_links` now uses scipy's transpose plus a float64 Aᵀ matrix
  (3.6 s → 0.65 s per 50k-node run). The batch path for 100M links is unchanged (memory-lean).

## Problems and how they were resolved

1. Host vertex join ran >10 min per part (one-sided condition in `LEFT JOIN ... ON` → nested-loop join); rewritten
   as equi-joins: 1 s per part.
2. Rank history ran out of disk (8.2 GB for 2 releases). With the user's approval: deleted the current release's
   raw files (13.7 GB) and switched to compact storage keyed by current harmonic position (4.45 GB for 5 releases).
   A single string join then hit DuckDB's 4 GB memory limit; it now runs in 8 hash partitions.
3. The machine slept 19:34–22:11; the host job resumed by itself. Common Crawl throttled the host edge downloads
   (HTTP 503) for most of the night: the host step took 7 h 57 min.
4. Browser check found the live form refusing its own default cap (number input step 1000 with min 10); fixed.
5. The first live request also loaded the 1M-node graph (~15 s); the graph now preloads at server start and the
   one-time load is outside the 5 s budget.

## Tests

Backend 171 passed (new: `test_live_api.py` 6, history loader 2, weighted PageRank 6, host weights 1).
Frontend 220 passed (new: `history.test.ts`, `live.test.ts`). Typecheck and build clean.

## Disk

33 GB free. `data/history.duckdb` 4.45 GB, `data/subgraph_top1000000_weighted.npz` 802 MB.

## Test session with the user (2026-10-12 ~01:50)

All suites run in the user's Terminal panel (backend output streamed from `test_backend.log`, because the panel's
sandboxed shell cannot see the uv Python): backend 171 passed, frontend type check clean, frontend 220 passed.
Browser walkthrough: lookup with a messy URL, keyboard focus and tooltips (250 of 250 numbers have one), rank history,
own scores incl. weighted PageRank, compare, disagreements, convergence lab (weighted run listed), playground, about,
live PageRank, what-if, HITS, error responses (404, 422, cap errors), rate limit (429 + Retry-After, then recovery),
light/dark theme, 375 px width without horizontal scroll.

Found and fixed during the session:
1. After a rebuild, a browser that had cached `index.html` asked for deleted chunks and the whole app went blank.
   `index.html` is now served with `Cache-Control: no-cache` (test added), and lazy parts are wrapped in
   `LoadErrorBoundary`, which shows a reload button instead of a blank page. Verified: a plain navigation after a
   rebuild loads the new bundle.
2. The rank-history chart clipped its last x-axis label; the x range is now padded.
3. The HITS form now says its base set is limited by the neighbourhood cap above.

Observed and explained (not bugs): what-if at the 50,000 cap for wikipedia.org needs two 69-iteration runs and
returns the cap error ("Reduce max_nodes (for example to 25,000)"); at 25,000 it runs in 3.4 s. One added link from
googletagmanager.com moved wikipedia.org from #20 to #3, because googletagmanager.com has 313,418 in-links and no
out-links in the subgraph, so its first out-link passes 85% of its large score.
