# Linkflow Lab

**A transparent link-analysis website built on the public [Common Crawl web graph](https://commoncrawl.org/web-graphs).**
It measures how important websites are from the way they link to each other, using PageRank and related
algorithms, and explains where every number comes from.

- Look up any of about **118 million domains** and see Common Crawl's own PageRank and harmonic centrality.
- See **19 algorithm variants computed by Linkflow Lab** (PageRank with different settings, TrustRank, spam mass,
  topic-sensitive PageRank, weighted PageRank and more) on the 1 million most central domains.
- Run PageRank, "what if this link existed?" experiments and HITS **live**, with your own parameters.
- Follow a domain's **rank history** across six Common Crawl releases.
- Build a small graph yourself and **watch the algorithms run step by step** in the browser.

Every number on the site has a tooltip naming its algorithm, its parameters and the data release it came from.

> Linkflow Lab is **not Google's PageRank** and is not affiliated with Google or Common Crawl. Google's ranking is
> private, page-level and uses many signals; Linkflow Lab runs the published algorithms on public data.

---

## Contents

- [The idea in one minute](#the-idea-in-one-minute)
- [What the site does](#what-the-site-does)
- [Algorithms](#algorithms)
- [The data](#the-data)
- [How it works](#how-it-works)
- [Tech stack](#tech-stack)
- [Some findings](#some-findings)
- [Running it](#running-it)
- [Tests](#tests)
- [Project layout](#project-layout)
- [Engineering notes](#engineering-notes)
- [Limitations](#limitations)
- [Further documentation](#further-documentation)

---

## The idea in one minute

The web is a **graph**: every domain is a node, and if any page on domain A links to domain B there is a directed
edge A → B. A link works like a vote, and a vote from an important site counts for more.

**PageRank** turns this into numbers with the *random surfer* model: someone clicks links forever; with
probability α = 0.85 they follow a random link on the current site, otherwise they jump to a random site. A
domain's PageRank is the share of time the surfer spends there in the long run. It is computed by **power
iteration**: start with equal scores and apply

```
p = α · Mᵀ p + (1 − α) · v        M splits each site's score equally over its out-links; v is the teleport vector
```

until the scores stop changing (L1 change below 10⁻⁸). Every other algorithm here is a variation on this idea or
a different answer to "what makes a site important?".

## What the site does

| Page | What it shows |
|---|---|
| **Lookup** | Search a domain (URLs and `www.` are normalised). Common Crawl's PageRank and harmonic centrality with rank and percentile among ~118M domains. Top 25 domains. |
| **Domain page** | The above, plus Linkflow Lab's own 19 scores, **Explain** (which domains pass it the most PageRank, and how much comes from links, teleportation and dangling domains), **rank history** chart, and a link to live analysis. |
| **Compare** | Up to 10 domains side by side, as a table and a chart. |
| **Disagreements** | Domains the algorithms disagree about most (high on one measure, low on another). |
| **Convergence Lab** | Residual per iteration for every stored run, on a log scale: how fast each algorithm converged. |
| **Live analysis** | PageRank, what-if and HITS computed on demand on a domain's neighbourhood (see below). |
| **Playground** | Draw your own graph and step through PageRank, personalized PageRank, HITS and harmonic centrality in the browser. |
| **About & methodology** | Definition, formula, defaults, source paper and limitations of every algorithm. |

### Live analysis

Computations run on a domain's **neighbourhood**: every domain within two links of it (in either direction)
inside the top-1M subgraph, capped at 50,000 domains by keeping the highest-PageRank neighbours. Results are
labelled *"Local approximation on this domain's neighborhood"*, because links from outside it are ignored.

- **PageRank:** choose α, the dangling-domain strategy and an optional seed set; returns scores, rank and the
  residual of every iteration.
- **What-if:** add up to 20 hypothetical links; returns score and rank before and after (and says which links
  already exist).
- **HITS:** hub and authority scores on a base set built from root domains you enter.

Each request must finish within **5 seconds**; otherwise the API answers with an error naming the cap to reduce.
Live requests are limited to **10 per minute per IP** (HTTP 429 with `Retry-After`).

## Algorithms

| Algorithm | Question it answers | Source |
|---|---|---|
| **PageRank** (α = 0.50, 0.70, 0.85, 0.95; 4 dangling strategies) | Where does a random surfer spend their time? | Page, Brin, Motwani, Winograd, Stanford tech report 1999-66 |
| **Harmonic centrality** | How close is every other site to this one, in link hops? `H(x) = Σ 1/d(y, x)` | Marchiori & Latora, Physica A 2000; Boldi & Vigna, *Axioms for Centrality*, 2014 |
| **Personalized PageRank** | PageRank when the surfer only teleports to chosen sites | Page et al. 1999; Jeh & Widom, WWW 2003 |
| **Topic-sensitive PageRank** (8 topics × 50 seeds) | How important is the site *for this topic*? | Haveliwala, WWW 2002 |
| **TrustRank** (200 trusted seeds) | How much trust flows to the site from reputable sites? | Gyöngyi, Garcia-Molina, Pedersen, VLDB 2004 |
| **Spam mass** | What fraction of the site's PageRank does *not* come from trusted sites? | Gyöngyi, Berkhin, Garcia-Molina, Pedersen, VLDB 2006 |
| **Seed distance** | How many hops is the site from the nearest trusted seed? | Linkflow Lab's own definition (`score = 0.5^hops`) |
| **HITS** | Two scores: *authorities* are linked from good hubs, *hubs* link to good authorities | Kleinberg, JACM 1999 |
| **Weighted PageRank** | PageRank where a link's weight is the number of host-level links between the two domains | Page et al. 1999 (weighted transition matrix) |

**Dangling domains** (no out-links; 318,887 of the top 1M) would leak score out of the system, so their score is
redistributed. Four strategies are compared: along the teleport vector, uniformly, as a self-loop, or by removing
them and adding them back afterwards (the 1999 paper's approach).

Formulas, parameters, citations and limitations for each: [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

## The data

All data comes from Common Crawl's web graph, release **`cc-main-2026-may-jun-jul`**:

| File | Size | Used for |
|---|---|---|
| Domain ranks (PageRank and harmonic centrality computed by Common Crawl) | 2.35 GB compressed, 117,963,409 domains | Lookup, compare, percentiles |
| Domain vertices + edges | 0.88 GB + 10.5 GB compressed | Building the top-1M subgraph (99,709,237 links) |
| Host graph (48 vertex + 192 edge files) | streamed, one file at a time | Weighted PageRank: 52.7M hosts mapped, 222.7M host-level links counted |
| Domain ranks of the 5 previous releases | ~2.4 GB each, deleted after loading | Rank history (484.8M rows) |

Release names are taken from Common Crawl's official listing, never guessed. Common Crawl writes domain names
reversed (`uk.co.bbc`); Linkflow Lab normalises them both ways. Exact file formats and load results:
[`docs/DATA.md`](docs/DATA.md).

The data is **not in this repository** (about 15 GB once built). The jobs below download and rebuild it.

## How it works

```
 Common Crawl (HTTPS)
        │  parallel, resumable downloads; retries on throttling; stall watchdog
        ▼
 data/raw ──► Python jobs (run once, offline)
               ├─ load_ranks          → data/linkflow.duckdb    118M domains: Common Crawl's scores, ranks, percentiles
               ├─ build_subgraph      → data/subgraph_top1000000.npz   top 1M domains, 99.7M links (sparse matrix)
               ├─ compute_all         → data/analysis.duckdb    19 algorithm variants × 1M domains, convergence runs
               ├─ build_host_weights  → data/subgraph_top1000000_weighted.npz   host-level link counts
               └─ load_history        → data/history.duckdb     5 earlier releases
                                   │
          FastAPI backend (Python) ── JSON /api/... ──► React frontend (TypeScript)
          + live endpoints computing on demand            tables, charts, tooltips, playground
```

Development happened in three phases, each tested and confirmed before the next:

1. **Common Crawl's scores** for all 118M domains: lookup, compare, playground, methodology.
2. **Linkflow Lab's own scores** on the top 1M domains by harmonic centrality (running every algorithm on the full
   graph of billions of links is not feasible on a laptop): explain, disagreements, convergence lab.
3. **Live analysis**, weighted PageRank from the host graph, rank history, rate limiting.

## Tech stack

| Layer | Tools | Why |
|---|---|---|
| Algorithms | Python 3.11, NumPy, SciPy sparse matrices | Only the 99.7M existing links are stored, not 10¹² possible ones |
| Storage | DuckDB | Embedded column-store; queries 118M rows on a laptop and spills to disk when memory runs out |
| API | FastAPI, Uvicorn | Typed request validation, fast JSON |
| Frontend | React 19, TypeScript, Vite, react-router | |
| Charts and graphs | uPlot, Cytoscape.js | Fast time-series charts; interactive graph editor |
| Methodology page | marked + DOMPurify | Renders `docs/METHODOLOGY.md` safely |
| Tests | pytest, NetworkX, Vitest | Algorithms are checked against NetworkX on small graphs |

## Some findings

- **PageRank measures links, not popularity.** `googletagmanager.com` is #4 by PageRank, ahead of Wikipedia:
  millions of sites embed its script, and Common Crawl counts embedded resources as links.
- **One link can matter a lot.** `googletagmanager.com` has 313,418 in-links and no out-links. In a what-if
  experiment, a single link from it to `wikipedia.org` moved Wikipedia from #20 to #3 in its neighbourhood,
  because 85% of a large score suddenly had one place to go.
- **Weighting changes the middle, not the top.** Weighted and unweighted PageRank have a Spearman rank correlation
  of 0.967; blog platforms rise (`blogspot.com` #47 → #13) because each hosted blog is a separate host.
- **Trust reshuffles institutions.** Under TrustRank, seed domains rise (`harvard.edu` #159 → #32) while sites whose
  PageRank comes from user content fall (`blogspot.com` #47 → #250).
- **HITS drifts.** Roots `python.org` and `rust-lang.org` give `google.com`, `youtube.com` and `twitter.com` as top
  authorities: Kleinberg's "tightly knit community" effect.

## Running it

Requirements: **Python 3.11+**, **Node 20.19+**, about **16 GB of RAM** and **35 GB of free disk** while building
the data (about 15 GB when done). Commands below use Windows paths (`.venv/Scripts`); on macOS and Linux use
`.venv/bin`.

### 1. Install

```
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements-dev.txt

cd frontend
npm install
npm run build          # writes frontend/dist, which the API serves at /
cd ..
```

### 2. Build the data

Each job is resumable: if it stops, run it again and it continues where it left off. Stop the web app while a job
runs, because DuckDB allows only one process to write a database.

```
# Phase 1: Common Crawl's ranks for ~118M domains (2.35 GB download, ~3.5 GB RAM)
.venv/Scripts/python -m backend.jobs.load_ranks

# Phase 2: top-1M subgraph and Linkflow Lab's own algorithm variants
.venv/Scripts/python -m backend.jobs.download_graph                  # vertices + edges, ~11 GB
.venv/Scripts/python -m backend.jobs.build_subgraph --top 1000000    # -> data/subgraph_top1000000.npz
.venv/Scripts/python -m backend.jobs.compute_all                     # -> data/analysis.duckdb

# Phase 3: weighted PageRank and rank history
.venv/Scripts/python -m backend.jobs.build_host_weights              # streams the host graph part by part
.venv/Scripts/python -m backend.jobs.compute_all                     # adds the weighted PageRank variant
.venv/Scripts/python -m backend.jobs.download_graph --history        # rank files of the 5 earlier releases
.venv/Scripts/python -m backend.jobs.load_history                    # -> data/history.duckdb
```

`data/phase3_chain.sh` runs the Phase 3 steps in order. Expect several hours in total, mostly downloading;
Common Crawl throttles heavy downloads and the jobs retry automatically.

### 3. Run

```
.venv/Scripts/python -m uvicorn backend.api.main:app --port 8000
```

Open http://localhost:8000. For frontend development, run `npm run dev` in `frontend/` (http://localhost:5173,
proxies `/api` to port 8000).

Pages that need data which has not been built yet say so, with the command to run, instead of failing.

### With Docker (Phases 1 and 2)

```
docker compose run --rm load-ranks
docker compose run --rm download-graph
docker compose run --rm build-subgraph
docker compose run --rm compute-all
docker compose up                       # http://localhost:8000
```

## Tests

```
.venv/Scripts/python -m pytest         # backend: 171 tests
cd frontend && npm test                # frontend: 220 tests
cd frontend && npm run typecheck       # TypeScript
```

The backend tests check every algorithm against NetworkX and worked examples from the source papers, and cover the
data jobs on small graphs in Common Crawl's file format, the API, the live endpoints (time budget, caps,
rate limit) and rank history. The frontend tests check the in-browser algorithm ports against the Python
reference numbers. `run_tests.ps1` runs everything on Windows.

## Project layout

```
backend/
  algorithms/   PageRank family, HITS, harmonic centrality, spam mass, seed distance, scoring (pure NumPy/SciPy)
  api/          FastAPI app: lookup and compare, analysis endpoints, live endpoints and rank history
  jobs/         download, load and compute jobs (streaming, resumable)
  seeds/        trusted seed list (200 domains) and topic seed lists (8 × 50)
  tools/        maintenance scripts (seed check, test fixtures, percentile recompute)
  tests/        pytest suite
frontend/
  src/pages/        one component per page
  src/analysis/     domain-page sections: own scores, explain, rank history
  src/algorithms/   in-browser PageRank, HITS and harmonic centrality for the playground
  src/components/   tooltips (Num), charts, search box, theme toggle
docs/
  METHODOLOGY.md    every algorithm: definition, formula, defaults, citation, limitations
  DATA.md           file formats, sample lines, load results
  PHASE3_REPORT.md  Phase 3 results and test session
  HANDOFF.md        build log: decisions, status, machine notes
data/               built data (not in the repository) and the Phase 2 report
```

## Engineering notes

- **Big data on a laptop.** Files are streamed in parts rather than loaded whole; the 1M-node graph is a sparse
  matrix with 8-bit values and 32-bit indices (~500 MB); PageRank pulls scores through a precomputed in-link
  structure in chunks, so the 100M-link batch run stays within a few GB of RAM.
- **Fast live analysis.** A domain's 2-hop neighbourhood usually fills the 50,000-domain cap with 16–22M links. For
  graphs up to 50M links the code switches to SciPy's compiled transpose and matrix–vector product, which brought
  live PageRank from 3.6 s to 0.65 s. The iteration limit is derived from the time left in the 5-second budget.
- **Ties in percentiles.** 3.75M domains share the minimum PageRank. Percentiles use the mid-rank definition
  `100 · (#lower + (#tied − 1)/2) / (n − 1)`, so tied domains are not all pushed to 0.
- **Compact history.** Rank history is keyed by each domain's position in the current release instead of its name:
  4.45 GB for five releases instead of about 20 GB.
- **Robust downloads.** Four parallel segments per file, automatic retry with backoff on HTTP 503 throttling,
  resumable parts and a stall watchdog.

## Limitations

- **Domain level, not page level:** all pages of a domain are one node.
- **Crawl coverage:** Common Crawl sees only what it crawled, with a bias towards English-language sites; ranks are
  relative positions in this crawl, not absolute truth.
- **Subgraph scores:** Linkflow Lab's own scores cover the top 1M domains and ignore links from outside that set.
- **Live analysis is local:** it ignores links from outside the neighbourhood.
- **Trust measures depend on the seed list:** 200 mostly English-language institutions; good sites far from them
  score lower.
- **Embedded resources count as links:** analytics, CDN and font domains rank very high.

## Further documentation

- [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md): algorithms in full, with citations (also shown on the site's About page)
- [`docs/DATA.md`](docs/DATA.md): data formats and load results
- [`docs/PHASE3_REPORT.md`](docs/PHASE3_REPORT.md) and [`data/PHASE2_REPORT.md`](data/PHASE2_REPORT.md): phase reports

Data: [Common Crawl](https://commoncrawl.org), used under its [terms of use](https://commoncrawl.org/terms-of-use).
