# Linkflow Lab

A transparent link-analysis site on the public [Common Crawl web graph](https://commoncrawl.org/web-graphs).
It shows Common Crawl's own PageRank and harmonic centrality for about 118 million domains, compares domains
side by side, and lets you step through PageRank, personalized PageRank, HITS and harmonic centrality on your own
graphs in the browser. Every number names its algorithm, parameters and data release.

Linkflow Lab is **not Google's PageRank** and is not affiliated with Google or Common Crawl.

- `docs/METHODOLOGY.md`: every algorithm's definition, formula, defaults, source paper and limitations
- `docs/DATA.md`: the exact file formats, how they are loaded, and load results

## Layout

```
backend/    FastAPI app (api/), algorithms (algorithms/), data jobs (jobs/), seed lists (seeds/), tests (tests/)
frontend/   React + Vite + TypeScript app; in-browser algorithm ports in src/algorithms/
data/       downloaded and derived files (gitignored)
docs/       METHODOLOGY.md, DATA.md
```

## Run with Docker

```
docker compose run --rm load-ranks     # downloads 2.2 GiB, loads ~118M domains into data/linkflow.duckdb
docker compose up                      # http://localhost:8000
```

The load needs about 3.5 GB of RAM and 10 GB of free disk (rank file plus database). DuckDB lets only one
process write the database, so run the load job while the app is stopped (`docker compose stop app`).

## Run without Docker

Requires Python 3.11+ and Node 20.19+.

```
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements-dev.txt     # .venv/bin/pip on macOS/Linux
.venv/Scripts/python -m backend.jobs.load_ranks
.venv/Scripts/python -m uvicorn backend.api.main:app --port 8000

cd frontend
npm install
npm run dev                                                    # http://localhost:5173, proxies /api to :8000
```

`npm run build` writes `frontend/dist`, which the API then serves at `/`.

## Tests

```
.venv/Scripts/python -m pytest           # backend: algorithms vs networkx, paper examples, loader, API, seeds
cd frontend && npm test                  # in-browser ports vs the Python reference, preset claims
```

## Linkflow Lab's own scores (top-1M subgraph)

```
python -m backend.jobs.download_graph                    # vertex + edge files, ~11 GB, resumable, stall watchdog
python -m backend.jobs.build_subgraph --top 1000000      # one pass over ~2.8B links -> data/subgraph_top1000000.npz
python -m backend.jobs.compute_all                       # every algorithm variant -> data/analysis.duckdb (resumable)
```

With Docker: `docker compose run --rm download-graph`, then `build-subgraph`, then `compute-all`. Stop the app
first; each job needs about 3–4 GB of free memory.

## Useful jobs

```
python -m backend.jobs.inspect_file <url>      # header + first 20 lines of a remote .gz, reading only a few MB
python -m backend.tools.check_seeds            # every seed domain exists in the loaded graph
python -m backend.tools.export_ts_fixtures     # regenerate the reference numbers for the frontend tests
```
