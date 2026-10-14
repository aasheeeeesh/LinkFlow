# Data

Linkflow Lab uses the **Common Crawl web graph**, release `cc-main-2026-may-jun-jul`, built from the crawls
CC-MAIN-2026-21, CC-MAIN-2026-25 and CC-MAIN-2026-30 (May, June and July 2026).

- Release page: <https://data.commoncrawl.org/projects/hyperlinkgraph/cc-main-2026-may-jun-jul/index.html>
- Domain files: `https://data.commoncrawl.org/projects/hyperlinkgraph/cc-main-2026-may-jun-jul/domain/`

According to the release page, the domain-level graph has 118.0 million nodes and 2.8 billion edges; 74.5 million
nodes (63.2%) are dangling (no out-links) and the largest strongly connected component covers 30.0 million nodes
(25.39%).

## Rule: inspect before parsing

Before any file is parsed, only its first few MB are downloaded and its header and first 20 lines are printed and
recorded here. Nothing assumes a column order that has not been seen. The helper for this is:

```
python -m backend.jobs.inspect_file <url>
```

## Domain rank file (used now)

| | |
|---|---|
| File | `cc-main-2026-may-jun-jul-domain-ranks.txt.gz` |
| Size | 2,349,720,599 bytes (2.19 GiB), gzip-compressed text |
| Inspected | 2026-10-10, first 4 MiB (148,121 lines) |

### Exact format

- One header line beginning with `#`, then one line per domain.
- Fields are separated by a single **tab** character; lines end with `\n`. No quoting.
- Rows are sorted by `#harmonicc_pos` ascending (highest harmonic centrality first).

| Column (as in header) | Type | Meaning |
|---|---|---|
| `#harmonicc_pos` | integer | Rank by harmonic centrality, 1 = highest. Unique positions; ties are broken by Common Crawl's ordering. |
| `#harmonicc_val` | float (Java `float` text, e.g. `2.9242738E7`) | Harmonic centrality value. |
| `#pr_pos` | integer | Rank by PageRank, 1 = highest. |
| `#pr_val` | float (Java `double` text, e.g. `8.873526110073348E-4`) | PageRank value. |
| `#host_rev` | string | Domain name in **reversed notation** (`com.example`). The column is called `host_rev`, but in the domain graph each value is a registered domain. |
| `#n_hosts` | integer | Number of host names merged into this domain node. |

### Header and first 20 lines (verbatim, tabs shown as `⇥`)

```
#harmonicc_pos⇥#harmonicc_val⇥#pr_pos⇥#pr_val⇥#host_rev⇥#n_hosts
1⇥2.9242738E7⇥1⇥0.015417606535592933⇥com.googleapis⇥2899
2⇥2.9201472E7⇥3⇥0.009362152270281839⇥com.facebook⇥3750
3⇥2.8902034E7⇥2⇥0.015298109970068943⇥com.google⇥32239
4⇥2.6482124E7⇥5⇥0.006388452338664256⇥com.instagram⇥755
5⇥2.5928852E7⇥4⇥0.0075571559087104475⇥com.googletagmanager⇥46
6⇥2.531427E7⇥8⇥0.00485124520426452⇥com.youtube⇥1632
7⇥2.446178E7⇥11⇥0.004029755156475409⇥com.twitter⇥610
8⇥2.4174042E7⇥7⇥0.005465867141178023⇥com.gstatic⇥213
9⇥2.3915728E7⇥12⇥0.0038733729009413492⇥com.linkedin⇥897
10⇥2.3646664E7⇥10⇥0.004557070737564644⇥org.gmpg⇥2
11⇥2.2057096E7⇥6⇥0.006131067944316603⇥com.cloudflare⇥693
12⇥2.1744778E7⇥20⇥0.001799213438886148⇥com.gravatar⇥275
13⇥2.135213E7⇥19⇥0.0018371996348235918⇥com.apple⇥3281
14⇥2.1254186E7⇥38⇥8.873526110073348E-4⇥org.wikipedia⇥2204
15⇥2.1206964E7⇥15⇥0.0020482120621237243⇥net.jsdelivr⇥48
16⇥2.1192764E7⇥24⇥0.001245528503952638⇥com.pinterest⇥308
17⇥2.109311E7⇥18⇥0.001948358051936604⇥org.wordpress⇥1391
18⇥2.103367E7⇥48⇥7.790724854709842E-4⇥be.youtu⇥9
19⇥2.0941518E7⇥28⇥0.0011589522189508275⇥gl.goo⇥804
20⇥2.0934018E7⇥30⇥0.0010857165058144212⇥com.x⇥138
```

### How Common Crawl computed these values

From Common Crawl's open-source pipeline
([`cc-webgraph`, `src/script/webgraph_ranking/process_webgraph.sh` and `webgraph_config.sh`](https://github.com/commoncrawl/cc-webgraph)):

- **PageRank**: `it.unimi.dsi.law.rank.PageRankParallelGaussSeidel` from the LAW library, run without parameter
  overrides. LAW's documented defaults are damping factor α = 0.85 (`DEFAULT_ALPHA`), a uniform preference
  (teleport) vector, and the "weakly preferential" formula, in which dangling nodes are patched with a uniform
  transition to all nodes.
- **Harmonic centrality**: `it.unimi.dsi.webgraph.algo.HyperBall` with `--log2m 12`, i.e. 2^12 registers per
  HyperLogLog counter for the domain graph. HyperBall is a probabilistic approximation; counters of this size
  have a relative standard deviation of about 1.6% (1.04/√4096).

Linkflow Lab does not recompute these values. It loads them and labels them as Common Crawl's computation
everywhere they appear.

### Loading (`python -m backend.jobs.load_ranks`)

1. Download with HTTP Range requests in 4 parallel segments, resuming partial work, and verify the final size
   against `Content-Length`. Common Crawl's front end throttles long single connections and answers bursts with
   `503 SlowDown`; the downloader backs off exponentially and retries.
2. Check that the header equals the six columns above exactly; any difference stops the job.
3. Detect the notation from the first 20,000 keys: if common TLDs (`com`, `org`, `uk`, ...) appear as the first
   label more often than as the last label, the file is reversed. For this release the detector reports
   **reversed**.
4. Stream the gzip file through DuckDB's CSV reader (the file is never held in memory) into table `domain_ranks`,
   sorted by domain. `domain` is the reversed key with its labels flipped (`com.example` becomes `example.com`);
   the original key is kept in `domain_key`.
5. Check that both rank columns run exactly from 1 to the row count; otherwise the transaction is not committed.
6. Build a small `top_domains` table (rows with either rank ≤ 1000) and checkpoint. Re-running the job detects a
   release already loaded from a file of the same size and only repeats this step (`--force` reloads).

**No separate index on `domain`.** The original plan included one. DuckDB builds its ART indexes in memory, and
an index over 118 million domain strings ran out of memory under a 3 GB limit (`Out of Memory Error: could not
allocate block of size 256.0 KiB (2.7 GiB/2.7 GiB used)`). Rows are stored sorted by domain, so DuckDB's
per-row-group min/max statistics confine an equality lookup to one row group of about 123,000 rows. Measured on
the full release: 6–8 ms per single-domain lookup (35 ms cold), 26 ms for a 10-domain lookup.

### Load results for `cc-main-2026-may-jun-jul`

| | |
|---|---|
| Rows | 117,963,409 (all domain names distinct after flipping) |
| Rank ranges | `hc_rank` and `pr_rank` both exactly 1 … 117,963,409 |
| Sum of PageRank | 1.000001 (Common Crawl's values as published) |
| Stream into DuckDB | 476 s |
| Peak process memory | about 3.2 GB (DuckDB limit 3 GB, sorts spilled to `data/duckdb_tmp`) |
| Database size | 5.9 GB |

### Table `domain_ranks`

| Column | Type | Source |
|---|---|---|
| `domain_key` | VARCHAR | `#host_rev` unchanged |
| `domain` | VARCHAR | `#host_rev` with labels reversed |
| `harmonic_centrality` | DOUBLE | `#harmonicc_val` |
| `hc_rank` | BIGINT | `#harmonicc_pos` |
| `pagerank` | DOUBLE | `#pr_val` |
| `pr_rank` | BIGINT | `#pr_pos` |
| `hc_percentile` | DOUBLE | mid-rank percentile of `harmonic_centrality` (see below) |
| `pr_percentile` | DOUBLE | mid-rank percentile of `pagerank` (see below) |
| `n_hosts` | BIGINT | `#n_hosts` |
| `release` | VARCHAR | release name |

The percentile is the share of other domains with a lower value, counting half of those tied with this one
(mid-rank), so tied values share a percentile even though Common Crawl gives them distinct positions. On this
release 3,746,526 domains tie at the minimum PageRank (percentile 1.588), and 116,460,761 domains share their
harmonic centrality value with another domain. The first load stored "strictly lower" percentiles; on 2026-10-11
`python -m backend.tools.recompute_percentiles` shifted the tied rows to mid-rank in place (the table
`percentile_method` records which definition each column uses, so the shift is applied only once).

### Lookups

User input is lower-cased; scheme, credentials, port, path, query and fragment are stripped; internationalised
names are converted to punycode (`bücher.de` becomes `xn--bcher-kva.de`). If the exact name is missing and it starts
with `www.`, the name without `www.` is tried. Otherwise the API answers 404 with
"Domain not in the Common Crawl graph for this release" and suggests parent domains that do exist.

## Domain vertex file (used by the subgraph job)

| | |
|---|---|
| File | `cc-main-2026-may-jun-jul-domain-vertices.txt.gz` |
| Size | 878,981,361 bytes (838.3 MiB), gzip-compressed text |
| Inspected | 2026-10-11, first 4 MiB |

- **No header line.** One line per domain node, three fields separated by a single tab, lines end with `\n`.
- Rows are sorted by the reversed domain name; ids start at 0 and increase by one per line.

| Field | Type | Meaning |
|---|---|---|
| 1 | integer | node id used by the edge file (0-based) |
| 2 | string | domain in reversed notation, same keys as `#host_rev` in the rank file |
| 3 | integer | number of hosts merged into the node |

First 21 lines (verbatim, tabs shown as `⇥`):

```
0⇥aaa.11111⇥1
1⇥aaa.115⇥1
2⇥aaa.139⇥1
3⇥aaa.a⇥1
4⇥aaa.aaa⇥5
5⇥aaa.aaaa⇥1
6⇥aaa.aaaaa⇥1
7⇥aaa.aaaaaa⇥1
8⇥aaa.aaaaaaaa⇥1
9⇥aaa.aaaaaaaaa⇥1
10⇥aaa.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa⇥1
11⇥aaa.abuhatimsports⇥1
12⇥aaa.ahj⇥1
13⇥aaa.atelier⇥1
14⇥aaa.aughts⇥1
15⇥aaa.dafds⇥1
16⇥aaa.diaz⇥1
17⇥aaa.driinaa⇥1
18⇥aaa.elio⇥1
19⇥aaa.fake-link⇥1
20⇥aaa.fake-links⇥1
```

## Domain edge file (used by the subgraph job)

| | |
|---|---|
| File | `cc-main-2026-may-jun-jul-domain-edges.txt.gz` |
| Size | 10,506,172,897 bytes (9.78 GiB), gzip-compressed text, about 2.8 billion lines |
| Inspected | 2026-10-11, first 4 MiB |

- **No header line.** One line per directed link, two fields separated by a single tab, lines end with `\n`.
- Rows are sorted by `from_id`, then `to_id`. Nodes without out-links (for example ids 0 to 37) do not appear as sources.

| Field | Type | Meaning |
|---|---|---|
| 1 | integer | `from_id`: vertex id of the linking domain |
| 2 | integer | `to_id`: vertex id of the linked domain |

First 21 lines (verbatim, tabs shown as `⇥`):

```
38⇥55275916
38⇥82742546
45⇥95284595
51⇥36371177
51⇥95284595
57⇥95284595
64⇥6593531
64⇥6736296
64⇥6939322
64⇥7074000
64⇥7107645
64⇥7273846
64⇥14174654
64⇥14749770
64⇥15966381
64⇥16662539
64⇥18441742
64⇥19633047
64⇥26026244
64⇥27082001
64⇥29738968
```

## Other files in the release (not parsed yet)

Listed on the release page; each will be inspected and documented here before it is parsed.

| File | Size | Description on the release page |
|---|---|---|
| `domain/cc-main-2026-may-jun-jul-domain.graph` (+ `-t.graph`) | 4.7 / 4.8 GiB | BVGraph format and its transpose |
| `host/cc-main-2026-may-jun-jul-host-vertices.paths.gz` | 1.7 GiB total | paths of 48 vertex files ⟨id, rev host⟩ |
| `host/cc-main-2026-may-jun-jul-host-edges.paths.gz` | 15.8 GiB total | paths of 192 edge files ⟨from_id, to_id⟩ |
| `host/cc-main-2026-may-jun-jul-host-ranks.txt.gz` | 4.5 GiB | host-level harmonic centrality and PageRank |

## Subgraph and batch results for `cc-main-2026-may-jun-jul` (2026-10-11)

| | |
|---|---|
| Domains | 1,000,000 (top by Common Crawl harmonic centrality; all matched to vertex ids) |
| Links kept | 99,709,237 of about 2.8 billion (both ends in the set, self-links dropped) |
| Domains without out-links in the subgraph | 318,887 |
| Build time | 210 s (vertex match 22 s, one pass over all edges 172 s, matrix 16 s) |
| Build peak memory | 4.3 GB (DuckDB limit 3 GB) |
| Matrix file | `data/subgraph_top1000000.npz`, 507 MB |
| Batch (18 variants) | 14 min, peak memory 4.7 GB; `data/analysis.duckdb`, 1.1 GB |

Iterations to reach tol = 1e-8 (all converged): PageRank α = 0.50: 15, 0.70: 27, 0.85: 59, 0.95: 186;
α = 0.85 with uniform dangling: 59, self-loop: 55, remove & re-add: 67 (core plus re-add passes);
TrustRank: 58; spam mass: 59 (global) and 58 (core); topics: 57 to 61. Seed distance is a breadth-first
search; every domain reachable from the trusted seeds is within 2 links of one.

## Host-level graph (Phase 3, used for weighted PageRank)

Listed by `host/cc-main-2026-may-jun-jul-host-vertices.paths.gz` (48 vertex files, 1.7 GiB in total) and
`host/cc-main-2026-may-jun-jul-host-edges.paths.gz` (192 edge files, 15.8 GiB in total); each path is relative to
`https://data.commoncrawl.org/`. Inspected 2026-10-11 (first 2 MiB of the first part of each; the last vertex
part starts at id 235,688,177).

**Vertex parts:** no header; two tab-separated fields: host id (0-based, continuous across parts) and host name in
reversed notation (`com.example.www`); sorted by reversed host name. Unlike the domain vertex file there is no
host-count column. First 21 lines of part 00000:

```
0⇥aaa.11111.www
1⇥aaa.115
2⇥aaa.139.124.222
3⇥aaa.a
4⇥aaa.aaa
5⇥aaa.aaa.aa
6⇥aaa.aaa.aaa
7⇥aaa.aaa.aaa.aaa
8⇥aaa.aaa.www
9⇥aaa.aaaa
10⇥aaa.aaaaa
11⇥aaa.aaaaaa
12⇥aaa.aaaaaaaa.aaa
13⇥aaa.aaaaaaaaa.aaa
14⇥aaa.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.aaa
15⇥aaa.abuhatimsports
16⇥aaa.ahj.www
17⇥aaa.atelier
18⇥aaa.aughts
19⇥aaa.dafds
20⇥aaa.diaz
```

**Edge parts:** no header; two tab-separated fields: `from_id`, `to_id` (host ids); sorted by `from_id`.
First 21 lines of part 00000:

```
108⇥188982651
143⇥12162325
143⇥109676569
148⇥212057641
154⇥8519079
154⇥9048461
158⇥69620717
174⇥167843383
199⇥53641214
208⇥53641214
208⇥73648718
208⇥199291876
208⇥206612850
208⇥210486939
226⇥8519079
226⇥183433780
226⇥237457194
239⇥8519079
239⇥31171853
239⇥210488126
264⇥265
```

**Host to domain.** A host belongs to the registered domain whose reversed key is the longest dot-separated prefix
of the reversed host name (`uk.co.bbc.news` belongs to `uk.co.bbc`). Only hosts whose domain is in the top-1M
subgraph matter, so the mapping is a longest-prefix match against the subgraph's 1,000,000 domain keys; no public
suffix list is needed.

## Earlier releases (Phase 3, rank history)

Release names come from Common Crawl's official listing, https://commoncrawl.org/web-graphs (newest first). The
five releases before `cc-main-2026-may-jun-jul` were inspected on 2026-10-11; each
`<release>/domain/<release>-domain-ranks.txt.gz` has exactly the header documented above
(`#harmonicc_pos ⇥ #harmonicc_val ⇥ #pr_pos ⇥ #pr_val ⇥ #host_rev ⇥ #n_hosts`):

| Release | Rank file size (bytes) |
|---|---|
| cc-main-2026-apr-may-jun | 2,388,634,678 |
| cc-main-2026-mar-apr-may | 2,348,299,329 |
| cc-main-2026-feb-mar-apr | 2,414,416,937 |
| cc-main-2026-jan-feb-mar | 2,365,541,332 |
| cc-main-2025-26-dec-jan-feb | 2,549,908,791 |

### Rank history: load results (2026-10-11)

`data/history.duckdb` (4.45 GB after compaction), loaded by `python -m backend.jobs.load_history`:

| Release | Domains in its rank file | Of these, also in cc-main-2026-may-jun-jul (stored) |
|---|---:|---:|
| cc-main-2026-apr-may-jun | 121,091,933 | 108,976,234 |
| cc-main-2026-mar-apr-may | 118,760,321 | 97,514,154 |
| cc-main-2026-feb-mar-apr | 124,646,710 | 94,419,059 |
| cc-main-2026-jan-feb-mar | 120,025,754 | 92,976,304 |
| cc-main-2025-26-dec-jan-feb | 134,222,466 | 90,937,924 |

Total 484,823,675 rows. Storage: `history(cur_pos INTEGER, release_pos TINYINT, hc_rank INTEGER, pr_rank INTEGER)`,
where `cur_pos` is the domain's `#harmonicc_pos` in the current release (unique per domain), so no domain strings
are stored. A first version stored the reversed domain string plus both raw scores (about 34 bytes per row) and
ran out of disk after two releases (8.2 GB); the compact form uses about 9 bytes per row. The join from domain
string to `cur_pos` runs in 8 hash partitions to stay under DuckDB's 4 GB memory limit; each partition is
inserted sorted by `cur_pos`, so a lookup for one domain reads about one row group per partition (measured
endpoint time about 0.3 s). Domains absent from the current release are not stored: they have no domain page.
Raw rank files were deleted after loading.

Host-level weights: 52,679,701 hosts of the host graph were mapped to the 1,000,000 subgraph domains
(vertex pass, 48 parts, 2,166 s).

### Host-level weights: results (2026-10-12)

`python -m backend.jobs.build_host_weights` streamed 48 host vertex parts and 192 host edge parts of
cc-main-2026-may-jun-jul, one part at a time (each deleted after ingestion), in 28,649 s (7 h 57 min), most of it
waiting on Common Crawl's HTTP 503 throttling and one 2.5-hour machine sleep. Peak RSS 5.4 GB.

| Measure | Value |
|---|---:|
| Hosts mapped to a subgraph domain | 52,679,701 |
| Domain pairs with at least one host-level link (weighted links) | 99,720,291 |
| Links of the binary domain subgraph | 99,709,237 |
| Pairs present in both | 99,709,233 |
| Sum of weights (host-to-host links between different subgraph domains) | 222,698,544 |

Mean weight is about 2.2 host links per domain pair. Only 4 domain-graph links have no host-level link: their
domains are linked only through hosts whose names do not map to the subgraph key under the longest-prefix rule.
About 11,000 weighted pairs (0.01%) are absent from the domain graph. Output: `data/subgraph_top1000000_weighted.npz`
(float32 CSR, 802 MB).
