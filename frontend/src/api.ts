/** Typed client for the Linkflow Lab API (see backend/api/main.py). */

export interface Metric {
  value: number;
  rank: number;
  percentile: number;
}

export interface DomainRanks {
  domain: string;
  domain_key: string;
  release: string;
  n_hosts: number;
  harmonic_centrality: Metric;
  pagerank: Metric;
  total_domains: number;
  matched_from: string | null;
}

export interface NotFound {
  query: string;
  domain: string;
  detail: string;
  suggestions: string[];
}

export interface CompareResponse {
  release: string;
  results: DomainRanks[];
  not_found: NotFound[];
  invalid: { query: string; detail: string }[];
}

export interface TopResponse {
  release: string;
  metric: "pagerank" | "harmonic";
  limit: number;
  results: DomainRanks[];
}

export interface MetaResponse {
  release: string;
  source_url: string;
  domains: number;
  loaded_at: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly body: unknown,
  ) {
    super(message);
  }
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { signal, headers: { Accept: "application/json" } });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "Could not reach the Linkflow Lab API. Is the backend running?", null);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? String((body as { detail: unknown }).detail) : res.statusText;
    throw new ApiError(res.status, detail, body);
  }
  return body as T;
}

export const api = {
  domain: (d: string, signal?: AbortSignal) => get<DomainRanks>(`/api/domain/${encodeURIComponent(d)}`, signal),
  compare: (ds: string[], signal?: AbortSignal) =>
    get<CompareResponse>(`/api/compare?d=${encodeURIComponent(ds.join(","))}`, signal),
  top: (metric: "pagerank" | "harmonic", limit: number, signal?: AbortSignal) =>
    get<TopResponse>(`/api/top?metric=${metric}&limit=${limit}`, signal),
  meta: (signal?: AbortSignal) => get<MetaResponse>("/api/meta", signal),
};

// ---- Phase 2: Linkflow Lab's own computations on the top-N subgraph ----------------------

export interface VariantScore {
  params_hash: string;
  algorithm: string;
  label: string;
  params: Record<string, unknown>;
  score: number;
  percentile: number;
  rank: number;
}

export interface ScoresResponse {
  domain: string;
  domain_key: string;
  release: string;
  subgraph_top: number;
  subgraph_nodes: number;
  matched_from: string | null;
  scores: VariantScore[];
  spam_mass: { relative_mass: number; threshold: number; flagged: boolean } | null;
}

export interface Contributor {
  domain: string;
  score: number;
  out_degree: number;
  share: number;
  percent: number;
}

export interface ExplainResponse {
  domain: string;
  params_hash: string;
  label: string;
  alpha: number;
  score: number;
  nodes: number;
  in_links: number;
  shown: number;
  contributors: Contributor[];
  from_links: { share: number; percent: number };
  from_teleport: { share: number; percent: number };
  from_dangling: { share: number; percent: number };
  ego: { nodes: string[]; edges: [string, string][] };
}

export interface RunHistory {
  params_hash: string;
  run: string;
  label: string;
  iterations: number;
  residuals: number[];
  seconds: number;
  converged: boolean;
  info: Record<string, number>;
}

export interface ConvergenceResponse {
  release: string;
  subgraph_top: number;
  runs: RunHistory[];
}

export interface Disagreement {
  domain: string;
  pagerank_percentile: number;
  trustrank_percentile: number;
  seed_distance_percentile: number;
  spread: number;
}

export interface DisagreementsResponse {
  release: string;
  subgraph_top: number;
  results: Disagreement[];
}

export const analysisApi = {
  scores: (d: string, signal?: AbortSignal) => get<ScoresResponse>(`/api/domain/${encodeURIComponent(d)}/scores`, signal),
  explain: (d: string, signal?: AbortSignal) => get<ExplainResponse>(`/api/domain/${encodeURIComponent(d)}/explain`, signal),
  convergence: (signal?: AbortSignal) => get<ConvergenceResponse>("/api/convergence", signal),
  disagreements: (limit: number, signal?: AbortSignal) =>
    get<DisagreementsResponse>(`/api/disagreements?limit=${limit}`, signal),
};

// ---- Phase 3: live computations on a domain's neighbourhood, and rank history -----------------

async function post<T>(path: string, payload: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      signal,
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "Could not reach the Linkflow Lab API. Is the backend running?", null);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    let detail: string = res.statusText;
    if (body && typeof body === "object" && "detail" in body) {
      const d = (body as { detail: unknown }).detail;
      // FastAPI validation errors arrive as a list of {loc, msg}.
      detail = Array.isArray(d) ? d.map((e) => `${(e.loc ?? []).slice(1).join(".")}: ${e.msg}`).join("; ") : String(d);
    }
    throw new ApiError(res.status, detail, body);
  }
  return body as T;
}

export type DanglingStrategy = "teleport" | "uniform" | "self_loop" | "remove_readd";

export interface ScoredDomain {
  domain: string;
  score: number;
}

interface LiveSource {
  release: string;
  subgraph_top: number;
}

export interface LivePageRankRequest {
  domain: string;
  alpha: number;
  dangling: DanglingStrategy;
  seeds: string[];
  max_nodes: number;
}

export interface LivePageRankResponse extends LiveSource {
  domain: string;
  label: string;
  nodes: number;
  links: number;
  capped: boolean;
  alpha: number;
  dangling: DanglingStrategy;
  seeds: string[];
  iterations: number;
  residuals: number[];
  converged: boolean;
  seconds: number;
  target: { score: number; rank: number };
  top: ScoredDomain[];
}

export interface WhatIfResult {
  domain: string;
  score_before: number;
  score_after: number;
  rank_before: number;
  rank_after: number;
}

export interface WhatIfResponse extends LiveSource {
  domain: string;
  label: string;
  nodes: number;
  alpha: number;
  dangling: DanglingStrategy;
  seeds: string[];
  links_before: number;
  links_after: number;
  already_linked: string[];
  seconds: number;
  results: WhatIfResult[];
}

export interface LiveHitsResponse extends LiveSource {
  roots: string[];
  max_in_per_root: number;
  base_size: number;
  links: number;
  iterations: number;
  residuals: number[];
  converged: boolean;
  seconds: number;
  authorities: ScoredDomain[];
  hubs: ScoredDomain[];
}

export interface HistoryPoint {
  release: string;
  hc_rank: number;
  pr_rank: number;
  domains: number;
}

export interface HistoryResponse {
  domain: string;
  points: HistoryPoint[];
  not_in_release: string[];
  not_loaded: string[];
}

export const liveApi = {
  pagerank: (req: LivePageRankRequest, signal?: AbortSignal) => post<LivePageRankResponse>("/api/live/pagerank", req, signal),
  whatif: (req: LivePageRankRequest & { links: { source: string; target: string }[] }, signal?: AbortSignal) =>
    post<WhatIfResponse>("/api/live/whatif", req, signal),
  hits: (req: { roots: string[]; max_in_per_root: number; max_nodes: number }, signal?: AbortSignal) =>
    post<LiveHitsResponse>("/api/live/hits", req, signal),
  history: (d: string, signal?: AbortSignal) => get<HistoryResponse>(`/api/domain/${encodeURIComponent(d)}/history`, signal),
};
