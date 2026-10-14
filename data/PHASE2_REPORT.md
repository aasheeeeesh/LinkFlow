# Phase 2 status report

_Last updated: 2026-10-11 16:55 IST. **Phase 2 complete, including the mid-rank percentile change the user chose (option a); waiting for confirmation before Phase 3.**_

## Result

| Step | Result |
|---|---|
| Downloads | Vertex file 12:03, edge file 13:14, sizes verified |
| build_subgraph | 13:15-13:19: 1,000,000 domains, 99,709,237 links, 318,887 without out-links; 210 s; peak 4.3 GB |
| compute_all | 13:19-13:33: 18 variants, all converged (alpha = 0.95 in 186 iterations); 14 min; peak 4.7 GB |
| Tests | 154 backend, 216 frontend passing |
| App | Running on port 8000 with the real results; domain page panels, Disagreements and Convergence Lab checked |

Resolved finding (option a, mid-rank percentiles, applied 14:01): within the top 1M every domain is within 2 links of a trusted seed (640,721 at 1 hop,
359,079 at 2), so seed distance has three values and every 2-hop domain sits at percentile 0. This dominates
the Disagreements list. See docs/METHODOLOGY.md, "Disagreements".

## Memory (resolved for now)

At 12:25 Windows had 45.8 GB committed of a 46.4 GB limit. The frontend build crashed with "out of memory" and,
at 12:24, even the download process hit `MemoryError` reading a 1 MB buffer (the supervisor restarted it and it
resumed from the bytes on disk). After Chrome tabs were closed, commit fell to about 24 GB of 31 GB with 4.5 to
5.8 GB of RAM free, and the frontend build succeeded.

The pipeline runner will not start a heavy step unless at least 3 GB of RAM and 5 GB of commit are free; it
logs and waits instead. If a step fails, the pipeline stops and the failure is reported here.

## Interruptions so far

- 03:49 to 05:36: Modern Standby triggered by the sleep button.
- 05:38 to 11:59: Modern Standby again, ended by keyboard input.
- 12:24: download process killed by `MemoryError` (machine out of commit memory); restarted automatically.
- The download resumed by itself after each.

## Handoff notes (how to resume from scratch)

**Spec and rules:** the user's original spec (first message of the session) defines three phases. After each phase:
run all tests, start the app, summarise, then STOP and wait for confirmation. On a failure (download blocked,
memory exceeded, format mismatch) stop, report here and propose; do not work around it. Phase 1 is done and
confirmed. Phase 2 is in progress; do not start Phase 3.

**Decisions taken:** no ART index on `domain_ranks.domain` (option A; lookups use domain-sorted storage, 6-8 ms).
Batch runs use `max_iter = 1000` (option a) so alpha = 0.95 can converge. Spam mass uses the paper's linear
formulation with gamma = 1. Phase 2 outputs go to `data/analysis.duckdb`, separate from the 6 GB rank DB.

**Running jobs:** `download_graph` (supervisor + `fetch` child, restarts stalls and crashes) ->
`phase2_pipeline` waits for both files and 3 GB RAM / 5 GB commit free, then runs `build_subgraph --top 1000000`
and `compute_all` (resumable: finished variants are skipped). Logs in `data/*.log`. A 30-minute cron check
(job 0b247d71, session-only) monitors them.

**If a job died:** re-run `python -m backend.jobs.download_graph` (resumes from `.parts/`),
`python -m backend.jobs.phase2_pipeline` (skips finished work). Use `.venv/Scripts/python.exe -u -m ...`
with `nohup ... > data/<name>.log 2>&1 &`.

**When compute_all finishes:** record subgraph stats (nodes, links, peak memory, timings) in docs/DATA.md;
run `.venv/Scripts/python.exe -m pytest -o addopts=""` and `cd frontend && npx vitest run && npx vite build`;
start the app with preview `linkflow` (.claude/launch.json, port 8000; it serves frontend/dist); check a domain
page (own scores, composite, spam mass, sensitivity, explain + ego graph), /disagreements and /convergence
in light and dark mode and at 375 px; then write the Phase 2 summary, delete the cron job and STOP.

**Windows gotchas on this machine:**
- Python: `.venv/Scripts/python.exe` (uv-managed CPython 3.11.15). The Store `python`/`python3` sandboxes writes
  under AppData\Roaming, and `python3 -` hangs waiting for input. uv: `C:/Users/AASHISH/AppData/Local/hermes/bin/uv.exe`.
- Never use `Path.resolve()` (follows a junction into an unusable path); use `absolute()`.
- Paths over 260 characters fail; use `$TEMP/<short>` for scratch files, not the session scratchpad.
- `docker-compose.exe` (validation only, no engine): `C:/Program Files/Docker/cli-plugins/docker-compose.exe`.
- Modern Standby: the sleep button freezes everything; the download recovers by itself afterwards.
- Commit memory ran out once (45.8 of 46.4 GB) until Chrome tabs were closed; check `\Memory\Committed Bytes`.
- Do not keep the API running while `build_subgraph`/`compute_all` write `analysis.duckdb` (they retry a lock
  for 5 minutes, then fail).
