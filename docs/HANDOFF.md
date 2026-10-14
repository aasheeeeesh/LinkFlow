# Linkflow Lab: handoff notes

Living document. Read this first when resuming after a conversation was compacted or a new session starts.
Update it at every milestone (status table, decisions, open issues).

_Last updated: 2026-10-11 17:05 IST_

## The project in one paragraph

"Linkflow Lab" is a transparent link-analysis website on the public Common Crawl web graph (release
`cc-main-2026-may-jun-jul`, domain level, 118M domains, 2.8B links). FastAPI + DuckDB + NumPy/SciPy backend,
React + Vite + TypeScript frontend (Cytoscape, uPlot). It must never claim to be Google's PageRank and must not
use the word "PageRank" in its name, logo or domain. The full specification is the user's first message of the
original conversation; its essential rules are copied below.

## Rules from the user's spec (must keep following)

- Three phases. After each phase: run all tests, start the app, write a short summary of what works and what
  doesn't, then **STOP and wait for confirmation** before the next phase. Never skip ahead.
- If any step fails (download blocked, memory exceeded, format differs from expectation): **stop, report exactly
  what happened and what you propose, and wait.** Do not work around it.
- Before parsing any file: download only its first few MB, print the header and first 20 lines, and write the
  exact format into `docs/DATA.md` (`python -m backend.jobs.inspect_file <url>`). Stream all large files.
- Quality bar: every number in the UI has a tooltip naming algorithm, parameters and data release; every algorithm
  has a METHODOLOGY.md section (definition, formula, parameters/defaults, full citation, limitations); type hints
  and formula docstrings on all Python functions; no placeholder text or TODOs in the UI; keyboard accessible,
  visible focus, light and dark mode.

## Status

| Phase | State |
|---|---|
| Phase 1: lookup, compare, playground, about | Done and confirmed |
| Phase 2: top-1M subgraph, 18 algorithm variants, explain, disagreements, convergence lab | Done and confirmed (2026-10-11) |
| Phase 3: live analysis | Done and confirmed (2026-10-12) (see docs/PHASE3_REPORT.md) |

### Phase 3 checklist (from the spec)

| Item | State |
|---|---|
| Ego graph: 2-hop neighbourhood within the subgraph, capped at 50,000 nodes (keep highest-PageRank neighbours) | done: `backend/api/live.py` `LiveGraph.ego` |
| POST /api/live/pagerank: alpha, dangling, seeds on the ego graph; result within 5 s or an error naming the cap to reduce | done (422 above 3M links with suggested max_nodes; 503 over 5 s) |
| POST /api/live/whatif: add hypothetical links in the ego graph; target's score and rank before/after; UI label "local approximation on this domain's neighborhood" | done (API + `frontend/src/pages/Live.tsx`) |
| POST /api/live/hits: HITS on a base set built from user-supplied root domains | done |
| Weighted PageRank: edge weight = number of host-level links between two domains, from the host graph | done, verified on real data |
| Rank history: earlier releases from the official listing, history chart on the domain page | done, verified on real data |
| Rate limit live endpoints: 10 requests per minute per IP | done (`RateLimiter`, 429 + Retry-After) |
| Tests, METHODOLOGY/DATA docs, run app, summary, STOP | done: backend 171, frontend 220; DATA/METHODOLOGY updated; summary in docs/PHASE3_REPORT.md |

## Decisions taken (with the user)

1. No ART index on `domain_ranks.domain` (option A): lookups rely on domain-sorted storage (6-8 ms).
2. Batch runs use `max_iter = 1000` (option a). In practice alpha = 0.95 converged in 186 iterations.
3. All percentiles are **mid-rank** (tied scores share the average percentile of their group), applied to both
   Common Crawl's and Linkflow Lab's percentiles (option a). Table `percentile_method` records it.
4. Spam mass: the paper's linear formulation, gamma = 1 by default.
5. Project stays in the session's scratch folder (user's choice, 2026-10-11). It is deleted with the session.
6. Rank history (Phase 3): the 5 releases before ours, in the order Common Crawl's web-graphs page lists them
   (newest first): `cc-main-2026-apr-may-jun`, `cc-main-2026-mar-apr-may`, `cc-main-2026-feb-mar-apr`,
   `cc-main-2026-jan-feb-mar`, `cc-main-2025-26-dec-jan-feb`. Source: https://commoncrawl.org/web-graphs.
   Releases newer than ours (`cc-main-2026-jun-jul-aug`, `cc-main-2026-jul-aug-sep`) exist but the spec fixes
   May/Jun/Jul 2026, so they are not used. Limited to 5 because of disk space (31 GB free on 2026-10-11).

## Data and files

| Path | What |
|---|---|
| `data/linkflow.duckdb` (5.9 GB) | `domain_ranks` (118M rows, sorted by domain), `top_domains`, `releases`, `percentile_method` |
| `data/analysis.duckdb` (1.1 GB) | `subgraph_nodes`, `subgraph_edges` (sorted by dst), `variants`, `scores`, `runs`, `disagreements`, `subgraph_meta` |
| `data/subgraph_top1000000.npz` (507 MB) | binary CSR, int8 data, int32 indices, 1M nodes, 99,709,237 links |
| `data/raw/` | downloaded Common Crawl files (rank, vertices, edges for our release) |
| `data/PHASE2_REPORT.md` | Phase 2 log, timings, interruptions |

## How to run things

- Python: always `.venv/Scripts/python.exe` (uv-managed CPython 3.11.15). Tests:
  `.venv/Scripts/python.exe -m pytest -o addopts=""`. Frontend: `cd frontend && npx vitest run && npx tsc --noEmit -p . && npx vite build`.
- App: Claude preview config `linkflow` in `.claude/launch.json` (uvicorn on port 8000, serves `frontend/dist`).
- Long jobs: `nohup .venv/Scripts/python.exe -u -m backend.jobs.<job> > data/<job>.log 2>&1 &`.
- Stop the app before any job that writes `linkflow.duckdb` or `analysis.duckdb` (DuckDB allows one writer).

## Machine quirks (Windows 11 laptop, 15.6 GB RAM)

- The Microsoft Store `python`/`python3` sandboxes writes under AppData\Roaming, and `python3 -` hangs waiting
  for input. Use the venv Python. uv: `C:/Users/AASHISH/AppData/Local/hermes/bin/uv.exe`.
- Never use `Path.resolve()` (follows a junction into an unusable path); use `absolute()`.
- Paths over 260 characters fail: use `$TEMP/<short>` for scratch files.
- Console is cp1252: set `PYTHONIOENCODING=utf-8` when printing non-ASCII from Python.
- Modern Standby: the sleep button freezes everything; downloads recover by themselves (supervisor + resume).
- Commit memory can run out (it hit 45.8 of 46.4 GB once) when many Chrome tabs are open. Check with
  `Get-Counter '\Memory\Committed Bytes','\Memory\Commit Limit'`. Heavy jobs need ~3 GB RAM and 5 GB commit free.
- Common Crawl throttles single connections and answers bursts with 503 SlowDown: downloads use 4 parallel
  range segments with backoff (`backend/jobs/fetch.py`).
- Docker is not installed; `docker-compose.exe` from an old install validates compose files only.
- DuckDB rewrites of the 118M-row table can exhaust disk with spill files (27 GiB once); prefer in-place
  updates of only the rows that change, and set `max_temp_directory_size`.

## Phase 3 running notes (2026-10-11)

- Chain: `(nohup bash data/phase3_chain.sh > /dev/null 2>&1 &)` from the project root (never `cd` through the junction).
  Order: build_host_weights -> compute_all (adds weighted_pagerank variant only) -> load_history. Logs in `data/*.log`,
  progress lines in `data/phase3_chain.log`. All three steps are resumable; rerun the script after a failure.
- History raw files are downloaded separately by `python -m backend.jobs.download_graph --history` (log
  `data/download_history.log`); load_history waits for each file to reach its remote size.
- Fixed 17:33: the vertex join used `LEFT JOIN ... ON key = expr AND len(parts) >= n`; the one-sided condition made
  DuckDB use a nested-loop join (>10 min per part). Now keys are computed first (NULL if too few labels): 1 s per part.
- While the chain writes `data/analysis.duckdb`, the API's Phase 2/live endpoints cannot open it (DuckDB file lock).
- Performance (17:45): a 50k-domain neighbourhood has ~22M links. `in_links` now uses scipy's transpose plus a float64
  A^T matrix (`InLinks.matrix`, used by `pull`) when links <= 50M (`FAST_PULL_MAX_LINKS`); live uses scipy fancy
  indexing for the induced subgraph. Live PageRank at 50k: 3.6 s -> 0.65 s; full request <= ~3 s for the biggest hub.
  Iteration limit = time left / (runs x links x 2 ns), cut-short runs -> 503 naming max_nodes.
- Verified in browser (17:46): domain page shows Rank history (current release only until load_history runs) and the
  "Analyse ... live" link; /live renders. Live endpoints on real data still to verify after the chain releases the DB.
- 18:35: history download finished; started load_history in parallel (separate history.duckdb; the chain's later load_history call skips loaded releases). Vertex mapping: 52,679,701 hosts -> subgraph domains (2,166 s). Edge parts ~0.7-2 min each.
- **22:15 FAILURE (waiting for the user):** load_history died at 18:37 with "There is not enough space on the disk" while
  writing the 3rd release. history.duckdb = 8.2 GB for only 2 releases (~34 B/row: string key + float + double), so
  5 releases would need ~20 GB. Loaded: apr-may-jun (121.1M rows), mar-apr-may (118.8M rows); their raw files are
  deleted; feb-mar-apr, jan-feb-mar, 2025-26-dec-jan-feb raw files still in data/raw. Free disk 11 GB.
  Proposal: (1) delete the current-release raw files (rank 2.35 GB, vertices 0.88 GB, edges 10.5 GB; already loaded);
  (2) compact history: key = current-release harmonic rank position (unique int), store only hc_rank/pr_rank,
  ~9 B/row, ~5-6 GB for 5 releases; convert the 2 loaded releases from history.duckdb, then drop it.
  Alternative: history only for the top-1M subgraph domains (~60 MB).
- Also: the machine slept 19:34-22:11 (no log lines, then read timeouts); the host-edge job resumed by itself.
  At 22:12 it was at edge part 57 of 192.
- **22:40 RESOLVED (user chose the proposal):** deleted current-release raw files (13.7 GB). load_history rewritten to
  compact storage keyed by current harmonic position (`cur_pos`), 8 hash-partition join (a single join hit OOM at 4 GB),
  `--convert-from` for the old format. All 5 releases loaded (484.8M rows); compacted by COPY FROM DATABASE to 4.45 GB;
  old history_v1.duckdb deleted. Endpoint verified on real data (wikipedia.org, bbc.co.uk, ~0.3 s); chart verified.
  DATA.md has the load table. Remaining: host edge parts -> compute_all (weighted PR) -> real-data live check -> summary.
- 23:00: watcher `bash data/watch_chain.sh` (background) exits on a new phase3_chain.log line or a 40-min log silence; on wake: report, restart the watcher, and if stalled rerun `(nohup bash data/phase3_chain.sh > /dev/null 2>&1 &)` (resumable).
- 01:31 build_host_weights done (stats in DATA.md); compute_all running weighted_pagerank (19th variant). Watcher restarted.
- 01:45 Phase 3 complete: chain finished 01:31 (weighted PR 55 s); live endpoints verified on real data; UI verified; STOPPED for confirmation.
- 01:55 test session with the user: all suites pass; fixed stale index.html cache (no-cache + LoadErrorBoundary), chart label clipping, HITS cap note. Details in PHASE3_REPORT.md. Still waiting for Phase 3 confirmation.
- 2026-10-12: user confirmed Phase 3. All three phases of the spec are complete.
