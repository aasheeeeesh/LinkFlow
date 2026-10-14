# Methodology

Linkflow Lab runs published link-analysis algorithms on the public Common Crawl web graph and shows how every
number was produced. It is **not Google's PageRank** and does not claim to approximate Google's ranking. Google
stopped publishing PageRank values in 2016.

All algorithms live in `backend/algorithms/`. Each one is a pure function of a `scipy.sparse` CSR adjacency
matrix and is tested against an independent implementation or a published example (`backend/tests/`). The
Playground's in-browser versions (`frontend/src/algorithms/`) are tested against numbers exported from the Python
code.

## Notation

| Symbol | Meaning |
|---|---|
| n | number of nodes (domains) |
| A | adjacency matrix, `A[i, j] = 1` if node i links to node j |
| out(i) | number of out-links of i; i is **dangling** if out(i) = 0 |
| M | row-stochastic link matrix, `M[i, j] = A[i, j] / out(i)`; rows of dangling nodes are zero |
| p | score vector; PageRank-family vectors sum to 1 |
| α | damping factor, the probability of following a link |
| v | teleport (personalization) distribution |
| L1 residual | `‖p_k − p_(k−1)‖₁`, recorded after every iteration k |

Iterative algorithms stop when the L1 residual falls below `tol` (default 1e-8) or after `max_iter` iterations,
and return the scores, the iteration count, and the residual at every iteration. Every PageRank variant checks
that its scores sum to 1 within 1e-9.

## Common Crawl's own values

The domain pages and the comparison table show **PageRank and harmonic centrality computed by Common Crawl**
for the release named next to each number. Linkflow Lab only loads them (see the data documentation).

- PageRank: LAW `PageRankParallelGaussSeidel` with library defaults: α = 0.85, uniform teleport, and dangling
  nodes patched with a uniform transition ("weakly preferential").
- Harmonic centrality: WebGraph `HyperBall` with 2^12 registers per counter, a probabilistic approximation with
  about 1.6% relative standard deviation per counter.

**Limitations.** Scores are domain-level: every host of a registered domain is one node and links between them do
not count. The graph contains only what Common Crawl crawled, and Common Crawl prioritizes crawling by harmonic
centrality, so domains that are already central are over-represented in the graph that measures them. Treat
scores as relative positions within one release, not as absolute quantities; values from different releases are
computed on different graphs.

## Linkflow Lab's own computations: the top-1M subgraph

Running every algorithm on all 118 million domains is not practical on one machine, so Linkflow Lab computes
its own scores on a subgraph:

1. Take the 1,000,000 domains with the highest Common Crawl harmonic centrality.
2. Stream all of Common Crawl's ~2.8 billion domain links once and keep only links whose source and target are
   both in that set. Self-links are dropped.
3. Store the result as a sparse matrix (`data/subgraph_top1000000.npz`) and the node-to-domain mapping in
   DuckDB (`subgraph_nodes`, with in- and out-degrees within the subgraph).

**What this changes.** Links from the other 117 million domains are left out, so a domain's in-links, its
out-degree and therefore its scores differ from Common Crawl's full-graph values. Percentiles and ranks
labelled "within the subgraph" are among these 1,000,000 domains only. Domains outside the set have only
Common Crawl's own values.

**Batch parameters.** Every stored run uses `tol = 1e-8` and `max_iter = 1000`. The interactive default is 200.
The worst-case bound for PageRank's convergence rate is α per iteration, which for α = 0.95 would mean about
log(1e-8) / log(0.95) ≈ 360 iterations, so the batch limit was raised before the runs. In practice the error
shrank faster than the bound (the rate is set by the second eigenvalue, which is at most α): α = 0.95 converged in
186 iterations, so every run would also have converged under the default of 200. The Convergence Lab shows each
run's iterations.

**Stored runs.** PageRank at α = 0.50, 0.70, 0.85 and 0.95 with teleport dangling handling; PageRank at
α = 0.85 with each of the other three dangling strategies; TrustRank, spam mass and seed distance from the
200 trusted seeds; one topic-sensitive vector per topic. Each run's scores, percentiles, ranks and L1 residual
history are stored with a hash of its parameters.

**Memory.** Instead of building float copies of the matrix and its transpose, the power iteration keeps only
the in-link structure (one 4-byte source index per link, built by a chunked counting sort) and computes
Mᵀx by gathering and summing in chunks of 8 million links. The results are identical to the straightforward
computation; the test suite checks this against NetworkX and against scipy's transpose.

## Explaining a score

For PageRank with uniform teleport and teleport or uniform dangling handling, a domain's score splits
exactly into three parts:

```
p(u) = Σ over in-links v → u of α · p(v) / out(v)     (links)
     + (1 − α) / n                                      (teleportation)
     + α · D / n                                        (rank re-spread from dangling domains)
```

where out(v) is v's number of out-links within the subgraph, n the number of domains and D the total score
held by domains without out-links. The "Explain this score" panel lists the 25 linking domains with the largest
share α · p(v) / out(v), each as a percentage of p(u), and shows the three parts, which add up to 100%. A domain
can receive a large share from a single link if the linking domain has a high score and few out-links.

## Disagreements

For every subgraph domain, take its percentile under PageRank (α = 0.85, teleport), TrustRank (α = 0.85,
trusted seeds) and seed distance (β = 0.5, trusted seeds). The spread is the highest minus the lowest of the
three. The Disagreements page lists the domains with the largest spread: their standing depends most on which
question is asked.

**Known limitations.** On the top-1M subgraph seed distance is very coarse: every domain is within two links of
one of the 200 trusted seeds (200 seeds at distance 0, 640,721 domains at distance 1, 359,079 at distance 2,
none unreachable), so it takes only three percentile values: 99.99, 67.94 and 17.95. A well-linked domain two hops
from the seeds therefore shows a spread of about 82 even when PageRank and TrustRank agree, and much of the top of
the list reflects that coarseness (for example `oculuscdn.com`: PageRank and TrustRank percentiles above 99.9,
seed distance 17.95). Among equal spreads, the order is by harmonic centrality rank.

## PageRank

**Definition.** The stationary distribution of a random surfer who, at each step, follows a uniformly chosen
out-link with probability α and otherwise jumps to a node drawn from v.

**Formula** (power iteration, starting from the uniform vector):

```
p_(k+1) = α · ( Mᵀ p_k + dangling_mass_k · w ) + (1 − α) · v
dangling_mass_k = Σ p_k[d] over dangling nodes d
```

**Parameters and defaults.** `alpha = 0.85`, `tol = 1e-8`, `max_iter = 200`, `teleport = None` (uniform
`v_i = 1/n`, or a probability vector over a seed set), `dangling = "teleport"`.

**Dangling-node strategies.** A dangling node has nowhere to send its rank. Four strategies are selectable:

| Strategy | What happens to rank on a dangling node |
|---|---|
| `teleport` | redistributed through the teleport vector: `w = v` |
| `uniform` | spread evenly over all nodes: `w_i = 1/n` (equals `teleport` when v is uniform) |
| `self_loop` | each dangling node links to itself and keeps its rank |
| `remove_readd` | the 1999 paper's procedure (section 2.7), below |

`remove_readd` follows Page et al. (1999), section 2.7: (1) repeatedly remove dangling nodes, since removing them
can leave other nodes dangling, counting the rounds; (2) compute PageRank on the remaining core, with v restricted
to the core and renormalised; (3) add the removed nodes back with score 0 and run exactly as many further
iterations on the full graph as there were stripping rounds. The paper notes that adding the nodes back this way
does not change the result significantly. In these final iterations dangling rank is re-injected through v,
matching the paper's step that re-adds lost rank via its source vector E. If every node is stripped (the graph
is acyclic), the extra iterations start from v. The final passes are a fixed count, so the reported residual
after them is not a convergence test.

**The 1999 formulation.** The tech report writes PageRank as

```
R' = c (A R' + E),   with ‖R'‖₁ = 1 and c maximised
```

where the paper's A is our Mᵀ and E is a "source of rank" vector. Since `‖R'‖₁ = 1`, this is the eigenproblem
`R' = c (A + E 1ᵀ) R'`; `pagerank_1999()` solves it by power iteration and reports c.

*Mapping to α.* On a graph with no dangling nodes, A preserves the L1 norm, so taking norms gives
`1 = c (1 + ‖E‖₁)`, i.e. `c = 1 / (1 + ‖E‖₁)`. The equation then becomes the standard update with

```
α = c = 1 / (1 + ‖E‖₁)        v = E / ‖E‖₁
```

So the paper's `‖E‖₁ = 0.15` corresponds to α = 1/1.15 ≈ 0.8696, not exactly 0.85. Conversely, α = 0.85
corresponds to `‖E‖₁ = (1 − α)/α = 0.15/0.85 ≈ 0.1765`. The familiar value 0.85 is the damping factor d of
Brin & Page (1998), and reading "0.15" as "1 − 0.85" is only an approximation. With dangling nodes, the raw 1999
equation leaks rank through their zero columns and c absorbs the loss. The test suite checks both
correspondences numerically.

**Worked example (the report's Figure 3).** Edges A→B, A→C, B→C, C→A with α = 1 converge to A = 0.4, B = 0.2,
C = 0.4. The Playground's first preset reproduces it.

**Rank sinks.** Two nodes that link only to each other, fed by a third, trap all rank when α = 1: the feeder
falls to 0, and the pair passes rank back and forth without converging, because the 2-cycle is periodic. With
α < 1 every node keeps at least (1 − α)/n.

**Sources.**
L. Page, S. Brin, R. Motwani, T. Winograd. *The PageRank Citation Ranking: Bringing Order to the Web.* Technical
Report 1999-66, Stanford InfoLab, 1999.
S. Brin, L. Page. *The Anatomy of a Large-Scale Hypertextual Web Search Engine.* Computer Networks and ISDN
Systems 30(1–7):107–117, 1998.

**Known limitations.** Treats every link as an equal endorsement. Rewards link farms and reciprocal-link schemes.
Depends on the choice of α and of the dangling strategy: the strategies give different results whenever v is not
uniform, which can be compared directly in the Playground. Power iteration converges at rate α, so α close to 1
needs many more iterations, and at α = 1 a reducible or periodic graph may not converge at all.

## Personalized PageRank

**Definition.** PageRank whose teleport vector is concentrated on a seed set S instead of all nodes. It
measures proximity to S in the random-surfer sense.

**Formula.** PageRank with `v_i = 1/|S|` for i in S and 0 otherwise. With the default `dangling = "teleport"`,
dangling rank also returns to the seeds.

**Parameters and defaults.** `seeds` (required), `alpha = 0.85`, `tol = 1e-8`, `max_iter = 200`,
`dangling = "teleport"`.

**Sources.** Page et al. (1999), section on personalized PageRank. G. Jeh, J. Widom. *Scaling Personalized Web
Search.* Proceedings of the 12th International World Wide Web Conference (WWW 2003), 271–279.

**Known limitations.** Results depend entirely on the seed set: nodes unreachable from the seeds score 0, and a
biased or small seed set gives biased scores.

## TrustRank

**Definition.** Trust starts at a small, manually vetted set of reputable seeds and flows along links. Spam pages
rarely receive links from reputable pages, so they receive little trust.

**Formula.** Personalized PageRank with the trusted set as seeds:

```
t = α · ( Mᵀ t + dangling_mass · w ) + (1 − α) · d,   d_i = 1/|S| for trusted i
```

**Parameters and defaults.** `trusted_seeds` (required), `alpha = 0.85`, `tol = 1e-8`, `max_iter = 200`,
`dangling = "teleport"`. Users can replace the default trusted seed list with their own. The original paper ran a
fixed number of biased-PageRank iterations; Linkflow Lab iterates to the tolerance instead.

**Source.** Z. Gyöngyi, H. Garcia-Molina, J. Pedersen. *Combating Web Spam with TrustRank.* Proceedings of the
30th International Conference on Very Large Data Bases (VLDB 2004), 576–587.

**Known limitations.** Trust decays with distance from the seeds, so good domains far from the seeds score low.
The seed list reflects its curators' judgment and coverage (language, region, topic). Spammers who obtain links
from trusted domains inherit trust.

## Spam mass

**Definition.** The share of a node's PageRank that is *not* explained by a known-good core of nodes. A node
whose rank comes mostly from outside the good core is likely supported by link spam.

**Formula.**

```
p        = PageRank with uniform teleport
p_plus   = γ · PPR(good core), put on the same scale as p
M        = p − p_plus          (absolute spam mass)
m        = M / p               (relative spam mass, at most 1)
flagged  = m > threshold
```

The paper defines mass with the linear PageRank system `L₀(v) = (1 − α)(I − α Mᵀ)⁻¹ v`, in which dangling rows
stay zero; L₀ is linear in the jump vector v, so the contribution of jumps into the core can be separated
exactly. Teleport-dangling PageRank equals L₀ up to a scalar: its fixed point satisfies
`p = α Mᵀ p + (α δ + 1 − α) v`, where δ is the dangling mass of p, so `L₀(v) = p · (1 − α)/(1 − α + α δ)`.
Linkflow Lab computes both runs with teleport-dangling PageRank, maps them onto the L₀ scale with this factor,
and reports p, p_plus and M rescaled so that p sums to 1. A test checks this against a direct sparse solve of the
linear system. The `uniform` and `self_loop` dangling strategies give other linear systems and are offered for
comparison; `remove_readd` is not linear and is not accepted.

**Parameters and defaults.** `good_core` (required), `alpha = 0.85`, `threshold = 0.7`,
`good_fraction` γ = 1, `dangling = "teleport"`. γ scales the core jump vector, because a hand-picked core is far
smaller than the set of all good nodes:

| γ | Meaning |
|---|---|
| 1 (default) | p_plus is the core-personalized PageRank itself; assumes the whole graph is good unless the core fails to explain it |
| \|core\| / n | the exact contribution of jumps into the core, so 0 ≤ M ≤ p; strongly overstates mass when the core is small |
| estimated good share | the paper's scaled estimator |

Negative M means the core explains more than the node's PageRank: the node is strongly supported by good nodes.

**Source.** Z. Gyöngyi, P. Berkhin, H. Garcia-Molina, J. Pedersen. *Link Spam Detection Based on Mass
Estimation.* Proceedings of the 32nd International Conference on Very Large Data Bases (VLDB 2006), 439–450.

**Known limitations.** Good nodes that the core does not reach, such as new or regional sites, also show high
mass, so a flag is a reason to look closer, not a verdict. Results depend on γ and on the core's coverage. The
paper restricts flags to nodes with substantial PageRank, because relative mass is noisy for low-ranked nodes.

## Seed distance

> The 2024 Google Content Warehouse documentation leak lists an attribute named `pagerank_ns`, described as
> "PageRank-NearestSeeds". **The leak documents only the attribute name. How Google computes it is unknown.**
> The definition below is Linkflow Lab's own, inspired by the name. It is not Google's.

**Definition.** How few forward-link hops separate a node from the nearest seed.

**Formula.** A breadth-first search over forward links, starting from all seeds at once, gives each node its
minimum hop distance d (seeds have d = 0). Then

```
score = β^d   if the node is reachable from a seed,   0 otherwise
```

**Parameters and defaults.** `seeds` (required; the trusted seed list by default), `beta = 0.5`, with
0 < β ≤ 1.

**Source.** Linkflow Lab's own definition. Hop-distance decay from trusted seeds is related in spirit to
TrustRank (Gyöngyi et al., 2004).

**Known limitations.** Ignores how many paths lead to a node and how strong they are: one link from a seed's
neighbour counts the same as a thousand. Unreachable nodes all score 0. Not comparable to any Google value.

## HITS (hubs and authorities)

**Definition.** On a query-specific subgraph, a good *authority* is pointed to by many good *hubs*, and a good
hub points to many good authorities.

**Formula** (starting from `h_0 = 1/√n`):

```
a_(k+1) = Aᵀ h_k,      then L2-normalise
h_(k+1) = A a_(k+1),   then L2-normalise
```

The residual is `‖a_k − a_(k−1)‖₁ + ‖h_k − h_(k−1)‖₁`. The vectors converge to the principal right and left
singular vectors of A when the top singular value is simple.

**Base set (Kleinberg's construction).** Root set R (user-supplied domains or a topic seed list), plus every
out-neighbour of R, plus up to d = 50 in-neighbours per root node. Kleinberg allowed an arbitrary choice of the d
in-neighbours; Linkflow Lab keeps the d with the highest PageRank, breaking ties by node id, so results are
reproducible. Self-links are removed, following Kleinberg's removal of intrinsic links.

**Parameters and defaults.** `tol = 1e-8`, `max_iter = 100`, in-neighbour cap 50.

**Source.** J. M. Kleinberg. *Authoritative Sources in a Hyperlinked Environment.* Journal of the ACM
46(5):604–632, 1999.

**Known limitations.** Topic drift: the base set can be dominated by a densely linked community unrelated to the
query, the tightly knit community effect. If the top singular value is repeated, the result depends on the
starting vector. Scores are only meaningful within one base set.

## Harmonic centrality

**Definition.** How close a node is to every other node, measured by incoming shortest paths, with unreachable
pairs contributing 0.

**Formula.**

```
H(x) = Σ over y ≠ x of 1 / d(y, x),     1/∞ = 0
```

where d(y, x) is the length of the shortest directed path from y to x.

**Computation.** For the full web graph Linkflow Lab uses Common Crawl's precomputed values (HyperBall,
approximate). It computes the exact value, one breadth-first search per node, only for graphs of at most 50,000
nodes, such as the Playground and ego graphs; larger graphs are refused.

**Sources.** M. Marchiori, V. Latora. *Harmony in the Small-World.* Physica A 285(3–4):539–546, 2000.
P. Boldi, S. Vigna. *Axioms for Centrality.* Internet Mathematics 10(3–4):222–262, 2014.
P. Boldi, S. Vigna. *In-Core Computation of Geometric Centralities with HyperBall: A Hundred Billion Nodes and
Beyond.* IEEE ICDM Workshops, 2013.

**Known limitations.** Counts paths, not their quality: a hop from a spam domain counts as much as a hop from a
reputable one. Common Crawl's values are approximate, and its crawler prioritizes by this measure, which feeds
back into the graph.

## Topic-sensitive PageRank

**Definition.** One personalized PageRank vector per topic, precomputed from that topic's seed list, then blended
at query time.

**Formula.**

```
offline:  p_t = PPR(seed set of topic t)                       for each topic t
query:    p   = Σ_t w_t · p_t,     w_t ≥ 0,  Σ_t w_t = 1
```

User weights are rescaled to sum to 1. Each p_t sums to 1, so the blend does too.

**Parameters and defaults.** Eight topics with 50 seed domains each: science, health, technology, finance, news,
education, government, sport. `alpha = 0.85`, `dangling = "teleport"`.

**Source.** T. H. Haveliwala. *Topic-Sensitive PageRank.* Proceedings of the 11th International World Wide Web
Conference (WWW 2002), 517–526.

**Known limitations.** Topics are only as good as their seed lists. Haveliwala derived the weights from the query
text; here the user sets them directly.

## Percentiles and the composite score

**Percentile.** Every percentile on the site, Common Crawl's and Linkflow Lab's, is a mid-rank percentile: the
share of the other domains with a lower score, counting half of those tied with this one:

```
percentile(x) = 100 · ( #{ y : s(y) < s(x) } + ( #{ y : s(y) = s(x) } − 1 ) / 2 ) / (n − 1)
```

A unique top score gets 100 and a unique bottom score 0; a block of tied scores lands in the middle of its block.
This matters for coarse measures: on the top-1M subgraph seed distance has three values, and the 359,079
domains two links from a seed share percentile 17.95 rather than 0. In the full graph, 3,746,526 domains tie at the
minimum PageRank (percentile 1.588) and 116 million of 118 million domains share their harmonic centrality value
with at least one other domain (HyperBall's approximate counters produce many exact ties).

**Composite.** A weighted sum of per-algorithm percentiles with user-set weights rescaled to sum to 1:

```
composite(x) = Σ_a w_a · percentile_a(x)
```

The composite is never shown alone: the interface always shows each algorithm's percentile, weight and
contribution next to it. By default PageRank (α = 0.85), TrustRank and seed distance have equal weight and
every other stored run has weight 0; spam mass is excluded because a higher value is worse.

**Known limitations.** Percentiles discard the size of score gaps. The composite is a presentation device that
depends entirely on the chosen weights, not a measurement.

## The Playground

The Playground runs TypeScript ports of PageRank (all four dangling strategies, uniform or seeded teleport),
HITS and exact harmonic centrality in the browser. **Step** performs exactly one iteration of the update above,
and **Run to convergence** repeats it until the residual is below 1e-8 or the iteration limit is reached (200 for
PageRank, 100 for HITS). Scores start uniform at iteration 0. With `remove_readd`, Step first iterates on the
stripped core, showing stripped nodes at 0, and then performs the extra re-add iterations. A test suite checks
that every port reproduces the Python implementation to within 1e-9 on reference graphs.

## Weighted PageRank

**Definition.** PageRank in which the random surfer picks an out-link with probability proportional to how many
host-level links join the two domains, instead of uniformly. A domain linked from 5,000 pages of another domain's
hosts receives more of that domain's score than one linked from a single host.

**Edge weight.** `w(u, v)` = number of distinct host-to-host links in Common Crawl's host graph (same release) from a
host of domain u to a host of domain v, for u ≠ v, both inside the subgraph. A host is assigned to a subgraph domain
by the longest reversed-name prefix (2 to 5 labels) that is a subgraph domain; a match on a shorter prefix is
discarded when the next-longer prefix is itself a domain in Common Crawl's full domain list (so `bbc.co.uk` hosts
are never counted as `co.uk`). Host files are streamed one part at a time and each part is deleted after ingestion.

**Formula.**

```
M[u, v] = w(u, v) / Σ_x w(u, x)
p_(k+1) = α · (Mᵀ p_k + (Σ_dangling p_k) · v) + (1 − α) · v
```

With every weight equal to 1 this is exactly the unweighted PageRank above (checked by the tests).

**Parameters and defaults.** `α = 0.85`, uniform teleport `v`, dangling mass sent along the teleport vector,
`tol = 1e-8` (L1), `max_iter` as in the batch run.

**Source.** L. Page, S. Brin, R. Motwani, T. Winograd. *The PageRank Citation Ranking: Bringing Order to the Web.*
Stanford InfoLab Technical Report 1999-66, 1999 (the random-surfer model; weighting the surfer's choice of link is the
standard generalisation, e.g. M. Bianchini, M. Gori, F. Scarselli, *Inside PageRank*, ACM Transactions on Internet
Technology 5(1):92–128, 2005). This is **not** the "Weighted PageRank" of W. Xing and A. Ghorbani (CNSR 2004),
which weights by in- and out-degree; that method is not implemented.

**Measured on this release.** Compared with unweighted PageRank (α = 0.85) on the same 1M domains: Spearman rank correlation 0.967, median rank change 25,222 positions; the top 8 domains are almost unchanged. 58 iterations.

**Known limitations.** Host counts reward sites that publish many hosts (wildcard subdomains, blog platforms), so
weights can be inflated without any editorial intent. Hosts whose domain is outside the subgraph are dropped.

## Live analysis

**Neighbourhood (ego graph).** For a domain c, the candidate set is every domain at distance 1 or 2 from c following
links in either direction inside the subgraph. If it has more than `max_nodes − 1` members (default and maximum
50,000), the candidates with the highest reference PageRank (α = 0.85, the batch run) are kept. The live graph is the
subgraph induced by c and the kept candidates: links leaving or entering the neighbourhood are dropped.

**Live PageRank.** The PageRank of the [PageRank section](#m-pagerank) run on the neighbourhood with the user's
α, dangling strategy and optional seed set (teleport uniform over the seeds; all seeds must be in the neighbourhood).
`tol = 1e-8`, `max_iter = 200`. The response returns the residual of every iteration.

**What-if.** Up to 20 hypothetical links, both ends inside the neighbourhood, are added to the neighbourhood graph
(an existing link is not doubled; self-links are ignored). PageRank is computed with the same parameters before and
after; the score and rank (1 = highest, ties broken by subgraph order) of the domain and of each link target are
returned.

**Live HITS.** The [HITS](#m-hits-hubs-and-authorities) base set from user-supplied roots (up to 10): roots, all
their out-neighbours and up to d (default and maximum 50) in-neighbours per root, highest reference PageRank first,
ties by node id. Requests whose base set exceeds `max_nodes` are refused with an explanation.

**Time budget.** Each request must finish in 5 seconds. A neighbourhood with more than 30,000,000 links is refused
before computing (HTTP 422, with a suggested smaller `max_nodes`). Otherwise the iteration limit is
`min(200, ⌊remaining time / (runs × links × 2 ns)⌋)` (runs = 2 for what-if; about 1.2 ns per link per iteration was
measured on the reference laptop). A run cut short by this limit before converging, or any request still over 5 s,
returns HTTP 503 naming `max_nodes` as the cap to reduce. Measured on the real subgraph: a 50,000-domain
neighbourhood has about 22 million links and PageRank converges in about 0.7 s (24 iterations at α = 0.85); building
the neighbourhood takes 0.05 to 2 s depending on how linked the domain is.

**Rate limit.** At most 10 live requests per minute per client IP (sliding 60-second window, kept in server memory;
HTTP 429 with a `Retry-After` header).

**Source.** Y.-Y. Chen, Q. Gan, T. Suel. *Local Methods for Estimating PageRank Values.* Proceedings of CIKM 2004,
pp. 381–389 (estimating a page's PageRank from a local neighbourhood, and the error this introduces).

**Known limitations.** These are local approximations on this domain's neighborhood, not global scores: rank mass
arriving from outside the neighbourhood is ignored, so a domain's live score is not comparable to its batch score,
and a what-if gain is only indicative of the direction and rough size of the effect. The cap keeps high-PageRank
neighbours, which biases the neighbourhood towards well-linked domains. The rate limit is per server process and
resets on restart.

## Rank history

**Definition.** Common Crawl's own PageRank rank and harmonic-centrality rank of a domain in earlier releases of the
domain graph, read from each release's published rank file (`<release>-domain-ranks.txt.gz`, same six columns as the
current release). Releases are not guessed: the names come from Common Crawl's web graph listing
(https://commoncrawl.org/web-graphs). The five releases before the current one are used:
`cc-main-2025-26-dec-jan-feb`, `cc-main-2026-jan-feb-mar`, `cc-main-2026-feb-mar-apr`, `cc-main-2026-mar-apr-may`,
`cc-main-2026-apr-may-jun`.

**Matching.** A domain's history is found through its harmonic-centrality position in the current release; earlier rows were matched to the current release by the reversed domain name. A domain that is not in an earlier release's rank file is listed as not in that release.

**Display.** The chart plots rank on an inverted log scale (rank 1 at the top), oldest release first, with a table
of the same values and the number of domains in each release.

**Source.** Common Crawl web graph releases, https://commoncrawl.org/web-graphs; ranks computed by Common Crawl with
the WebGraph framework (P. Boldi, S. Vigna, *The WebGraph Framework I: Compression Techniques*, WWW 2004).

**Known limitations.** Each release covers a different crawl, so the number of ranked domains changes between
releases and a rank change can reflect crawl coverage rather than links. A domain absent from a release's rank file is
listed as not in that release, not as rank 0.
