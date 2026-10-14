/**
 * What every number in the UI is: the algorithm, its parameters and the data it ran on.
 * These strings feed the tooltips required on every displayed number.
 */

export interface Provenance {
  algorithm: string;
  params: string;
  data: string;
}

export const ccPageRank = (release: string): Provenance => ({
  algorithm: "PageRank, computed by Common Crawl",
  params: "LAW PageRankParallelGaussSeidel, library defaults: α = 0.85, uniform teleport, dangling mass spread uniformly",
  data: `Common Crawl domain graph, release ${release}`,
});

export const ccHarmonic = (release: string): Provenance => ({
  algorithm: "Harmonic centrality, computed by Common Crawl",
  params: "WebGraph HyperBall, 2^12 registers per counter (approximate, about ±1.6% relative error)",
  data: `Common Crawl domain graph, release ${release}`,
});

export const ccRank = (metric: "pagerank" | "harmonic", release: string, total: number): Provenance => ({
  algorithm: metric === "pagerank" ? "Rank by Common Crawl PageRank" : "Rank by Common Crawl harmonic centrality",
  params: `Position 1 = highest score, out of ${total.toLocaleString("en-US")} domains; ties broken by Common Crawl's ordering`,
  data: `Common Crawl domain graph, release ${release}`,
});

export const ccPercentile = (metric: "pagerank" | "harmonic", release: string): Provenance => ({
  algorithm: `Percentile of Common Crawl ${metric === "pagerank" ? "PageRank" : "harmonic centrality"}`,
  params: "Mid-rank percentile, 0 to 100: share of domains with a lower score, counting half of those tied with this one",
  data: `Common Crawl domain graph, release ${release}`,
});

export const ccHosts = (release: string): Provenance => ({
  algorithm: "Number of hosts",
  params: "Distinct host names Common Crawl aggregated into this domain node",
  data: `Common Crawl domain graph, release ${release}`,
});

export const PLAYGROUND_DATA = "Your playground graph, computed in this browser (not Common Crawl data)";

/** Data description for Linkflow Lab's own computations on the subgraph. */
export const subgraphData = (release: string, top: number): string =>
  `Top ${top.toLocaleString("en-US")} domains by harmonic centrality, Common Crawl release ${release}; only links between them count`;

/** Human-readable parameter list for a stored variant. */
export function formatParams(params: Record<string, unknown>): string {
  const names: Record<string, string> = { alpha: "α", beta: "β", max_iter: "max iterations", good_fraction: "γ" };
  return Object.entries(params)
    .map(([k, v]) => `${names[k] ?? k.replace(/_/g, " ")} = ${typeof v === "number" && k === "tol" ? v.toExponential(0) : String(v)}`)
    .join(" · ");
}

export const lfScore = (label: string, params: Record<string, unknown>, release: string, top: number): Provenance => ({
  algorithm: `${label}, computed by Linkflow Lab`,
  params: formatParams(params),
  data: subgraphData(release, top),
});

export const lfPercentile = (label: string, release: string, top: number): Provenance => ({
  algorithm: `Percentile of ${label}`,
  params: "Mid-rank percentile within the subgraph, 0 to 100: share of domains with a lower score, counting half of those tied",
  data: subgraphData(release, top),
});

export const lfRank = (label: string, release: string, top: number): Provenance => ({
  algorithm: `Rank by ${label}`,
  params: `Position 1 = highest score among ${top.toLocaleString("en-US")} subgraph domains; ties share the best rank`,
  data: subgraphData(release, top),
});

// ---- Phase 3 ---------------------------------------------------------------------------------

export const LIVE_LABEL = "Local approximation on this domain's neighborhood";

/** Data description for a live computation on a domain's 2-hop neighbourhood. */
export const egoData = (domain: string, nodes: number, links: number, release: string, top: number): string =>
  `${LIVE_LABEL}: 2-hop neighbourhood of ${domain} (${nodes.toLocaleString("en-US")} domains, ${links.toLocaleString("en-US")} links) ` +
  `inside the top ${top.toLocaleString("en-US")} domains of Common Crawl release ${release}; links from outside it are ignored`;

export const liveParams = (alpha: number, dangling: string, seeds: string[]): string =>
  `α = ${alpha} · dangling = ${dangling} · teleport = ${seeds.length ? `seed set (${seeds.join(", ")})` : "uniform"} · tol = 1e-8 · max iterations = 200`;

export const livePageRank = (alpha: number, dangling: string, seeds: string[], data: string): Provenance => ({
  algorithm: "PageRank (live), computed by Linkflow Lab",
  params: liveParams(alpha, dangling, seeds),
  data,
});

export const liveRank = (data: string, nodes: number): Provenance => ({
  algorithm: "Rank by live PageRank",
  params: `Position 1 = highest score among ${nodes.toLocaleString("en-US")} neighbourhood domains; ties broken by subgraph order`,
  data,
});

export const liveHits = (kind: "authority" | "hub", roots: string[], perRoot: number, data: string): Provenance => ({
  algorithm: `HITS ${kind} score (live), computed by Linkflow Lab`,
  params: `Kleinberg base set from roots ${roots.join(", ")}: roots, all their out-links, up to ${perRoot} in-links per root ` +
    "(highest reference PageRank first) · L2-normalised · tol = 1e-8 · max iterations = 100",
  data,
});

export const historyRank = (metric: "pagerank" | "harmonic", release: string, total: number): Provenance => ccRank(metric, release, total);
