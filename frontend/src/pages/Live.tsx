import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ApiError,
  liveApi,
  type DanglingStrategy,
  type LiveHitsResponse,
  type LivePageRankResponse,
  type ScoredDomain,
  type WhatIfResponse,
} from "../api";
import { parseLinks, splitDomains } from "../analysis/live";
import { Num } from "../components/Num";
import { UPlotChart } from "../components/UPlotChart";
import { formatInt, formatScore, ordinalRank } from "../format";
import { egoData, LIVE_LABEL, liveHits, livePageRank, liveParams, liveRank, type Provenance } from "../provenance";
import { usePageTitle } from "../usePageTitle";

const MAX_NODES = 50_000;
const DANGLING: { value: DanglingStrategy; label: string }[] = [
  { value: "teleport", label: "Teleport (follow the teleport vector)" },
  { value: "uniform", label: "Uniform (spread over all domains)" },
  { value: "self_loop", label: "Self-loop (keep the mass)" },
  { value: "remove_readd", label: "Remove and re-add" },
];

type Status<T> = { state: "idle" } | { state: "running" } | { state: "ok"; data: T } | { state: "error"; message: string };

function errorMessage(e: unknown): string {
  return e instanceof ApiError ? e.message : String(e);
}

function run<T>(set: (s: Status<T>) => void, call: () => Promise<T>) {
  set({ state: "running" });
  call()
    .then((data) => set({ state: "ok", data }))
    .catch((e: unknown) => set({ state: "error", message: errorMessage(e) }));
}

const statsProv = (what: string, data: string): Provenance => ({
  algorithm: `Live computation: ${what}`,
  params: "Measured on the server for this request; the live budget is 5 seconds",
  data,
});

function StatusLine<T>({ status }: { status: Status<T> }) {
  if (status.state === "running") return <p className="muted" aria-live="polite">Computing…</p>;
  if (status.state === "error") return <p className="error" role="alert">{status.message}</p>;
  return null;
}

function ResidualChart({ residuals, title }: { residuals: number[]; title: string }) {
  if (residuals.length < 2) return null;
  return (
    <UPlotChart
      optionsKey={`${title}-${residuals.length}`}
      data={[residuals.map((_, i) => i + 1), residuals]}
      height={200}
      ariaLabel={`Line chart of the L1 residual per iteration for ${title}, ${residuals.length} iterations, log scale.`}
      options={(c, width, height) => ({
        width,
        height,
        scales: { x: { time: false }, y: { distr: 3 } },
        axes: [
          { label: "Iteration", stroke: c.text, grid: { stroke: c.border, width: 1 }, ticks: { stroke: c.border } },
          { label: "L1 residual", stroke: c.text, grid: { stroke: c.border, width: 1 }, ticks: { stroke: c.border }, size: 70,
            values: (_u, splits) => splits.map((v) => (v == null ? "" : v.toExponential(0))) },
        ],
        series: [{ label: "Iteration" }, { label: "Residual", stroke: c.series1, width: 2, points: { show: false } }],
      })}
    />
  );
}

function ScoreTable({ caption, rows, prov, rankProv }: { caption: string; rows: ScoredDomain[]; prov: Provenance; rankProv?: Provenance }) {
  return (
    <div className="table-wrap card" style={{ padding: 0 }}>
      <table>
        <caption style={{ textAlign: "left", padding: "8px 12px", fontWeight: 600 }}>{caption}</caption>
        <thead>
          <tr>
            <th className="r">Rank</th>
            <th>Domain</th>
            <th className="r">Score</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.domain}>
              <td className="r">{rankProv ? <Num p={rankProv}>{ordinalRank(i + 1)}</Num> : <Num p={prov}>{ordinalRank(i + 1)}</Num>}</td>
              <td>
                <Link to={`/domain/${encodeURIComponent(r.domain)}`}>{r.domain}</Link>
              </td>
              <td className="r">
                <Num p={prov}>{formatScore(r.score)}</Num>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} style={{ marginTop: 32 }}>
      <h2 id={id}>{title}</h2>
      {children}
    </section>
  );
}

export function Live() {
  usePageTitle("Live analysis");
  const [params, setParams] = useSearchParams();
  const [domain, setDomain] = useState(params.get("d") ?? "");
  const [maxNodes, setMaxNodes] = useState(MAX_NODES);
  const [alpha, setAlpha] = useState(0.85);
  const [dangling, setDangling] = useState<DanglingStrategy>("teleport");
  const [seedText, setSeedText] = useState("");
  const [linkText, setLinkText] = useState("");
  const [rootText, setRootText] = useState(params.get("d") ?? "");
  const [perRoot, setPerRoot] = useState(50);
  const [pr, setPr] = useState<Status<LivePageRankResponse>>({ state: "idle" });
  const [whatif, setWhatif] = useState<Status<WhatIfResponse>>({ state: "idle" });
  const [hits, setHits] = useState<Status<LiveHitsResponse>>({ state: "idle" });
  const [linkError, setLinkError] = useState("");

  const base = () => ({ domain: domain.trim(), alpha, dangling, seeds: splitDomains(seedText), max_nodes: maxNodes });
  const keepInUrl = () => setParams(domain.trim() ? { d: domain.trim() } : {}, { replace: true });

  const onPageRank = (e: FormEvent) => {
    e.preventDefault();
    keepInUrl();
    run(setPr, () => liveApi.pagerank(base()));
  };
  const onWhatIf = (e: FormEvent) => {
    e.preventDefault();
    const { links, bad } = parseLinks(linkText);
    if (bad.length) return setLinkError(`Could not read: ${bad.join("; ")}. Write one link per line as "source -> target".`);
    if (!links.length) return setLinkError('Add at least one link, one per line as "source -> target".');
    setLinkError("");
    keepInUrl();
    run(setWhatif, () => liveApi.whatif({ ...base(), links }));
  };
  const onHits = (e: FormEvent) => {
    e.preventDefault();
    run(setHits, () => liveApi.hits({ roots: splitDomains(rootText), max_in_per_root: perRoot, max_nodes: maxNodes }));
  };

  const neighbourhoodFields = (
    <>
      <label>
        Domain
        <input type="text" value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="example.com" required spellCheck={false} />
      </label>
      <label>
        Neighbourhood cap (max_nodes)
        <input type="number" min={10} max={MAX_NODES} step={10} value={maxNodes} onChange={(e) => setMaxNodes(Number(e.target.value))} />
      </label>
      <label>
        Damping α
        <input type="number" min={0} max={1} step={0.01} value={alpha} onChange={(e) => setAlpha(Number(e.target.value))} />
      </label>
      <label>
        Dangling domains
        <select value={dangling} onChange={(e) => setDangling(e.target.value as DanglingStrategy)}>
          {DANGLING.map((d) => (
            <option key={d.value} value={d.value}>
              {d.label}
            </option>
          ))}
        </select>
      </label>
      <label style={{ gridColumn: "1 / -1" }}>
        Seed set for teleport (optional; empty = uniform teleport). Seeds must be in the neighbourhood.
        <textarea rows={2} value={seedText} onChange={(e) => setSeedText(e.target.value)} spellCheck={false} />
      </label>
    </>
  );

  return (
    <>
      <h1>Live analysis</h1>
      <p>
        Recompute PageRank and HITS on demand, with your own parameters, on one domain's neighbourhood: every domain
        within two links of it (in either direction) among the top domains of the Common Crawl subgraph, capped at{" "}
        {formatInt(MAX_NODES)} domains by keeping the neighbours with the highest reference PageRank. Links from outside the
        neighbourhood are ignored, so every result here is a local approximation, not the global score. Each request must
        finish within 5 seconds and each visitor can make 10 live requests per minute. The method is described in{" "}
        <Link to="/about#m-live-analysis">About &amp; methodology</Link>.
      </p>
      <p className="approx">{LIVE_LABEL}</p>

      <Section id="live-pr" title="PageRank on the neighbourhood">
        <form className="card live-form" onSubmit={onPageRank}>
          {neighbourhoodFields}
          <div>
            <button type="submit" className="primary" disabled={pr.state === "running" || !domain.trim()}>
              Compute PageRank
            </button>
          </div>
        </form>
        <StatusLine status={pr} />
        {pr.state === "ok" && <PageRankResult r={pr.data} />}
      </Section>

      <Section id="live-whatif" title="What if these links existed?">
        <p className="muted small">
          Add up to 20 hypothetical links between domains of the neighbourhood above (same domain, cap, α, dangling
          strategy and seeds). The score and rank of the domain and of each link target are shown before and after.
        </p>
        <form className="card live-form" onSubmit={onWhatIf}>
          <label style={{ gridColumn: "1 / -1" }}>
            Links, one per line: source -&gt; target
            <textarea rows={3} value={linkText} onChange={(e) => setLinkText(e.target.value)} spellCheck={false}
              placeholder={domain ? `another-domain.com -> ${domain}` : "source.com -> target.com"} />
          </label>
          <div>
            <button type="submit" className="primary" disabled={whatif.state === "running" || !domain.trim()}>
              Compare before and after
            </button>
          </div>
        </form>
        {linkError && <p className="error" role="alert">{linkError}</p>}
        <StatusLine status={whatif} />
        {whatif.state === "ok" && <WhatIfResult r={whatif.data} />}
      </Section>

      <Section id="live-hits" title="HITS from root domains">
        <p className="muted small">
          Kleinberg's HITS on a base set built from your root domains: the roots, every domain they link to, and up to
          d domains linking to each root (highest reference PageRank first), inside the subgraph. The base set may hold at most the neighbourhood cap set above (max_nodes), so a root that links to very many domains is refused.
        </p>
        <form className="card live-form" onSubmit={onHits}>
          <label style={{ gridColumn: "1 / -1" }}>
            Root domains (up to 10)
            <textarea rows={2} value={rootText} onChange={(e) => setRootText(e.target.value)} spellCheck={false} required />
          </label>
          <label>
            In-links per root (d)
            <input type="number" min={1} max={50} value={perRoot} onChange={(e) => setPerRoot(Number(e.target.value))} />
          </label>
          <div>
            <button type="submit" className="primary" disabled={hits.state === "running" || !splitDomains(rootText).length}>
              Compute HITS
            </button>
          </div>
        </form>
        <StatusLine status={hits} />
        {hits.state === "ok" && <HitsResult r={hits.data} />}
      </Section>
    </>
  );
}

function PageRankResult({ r }: { r: LivePageRankResponse }) {
  const data = egoData(r.domain, r.nodes, r.links, r.release, r.subgraph_top);
  const prov = livePageRank(r.alpha, r.dangling, r.seeds, data);
  const stat = (what: string) => statsProv(what, data);
  return (
    <div className="grid" style={{ marginTop: 12 }}>
      <p className="approx">{r.label}</p>
      <p>
        {r.domain}: score <Num p={prov}>{formatScore(r.target.score)}</Num>, rank{" "}
        <Num p={liveRank(data, r.nodes)}>{ordinalRank(r.target.rank)}</Num> of{" "}
        <Num p={stat("domains in the neighbourhood")}>{formatInt(r.nodes)}</Num> domains (
        <Num p={stat("links inside the neighbourhood")}>{formatInt(r.links)}</Num> links).{" "}
        {r.converged ? "Converged" : "Did not converge"} after <Num p={stat("power iterations")}>{formatInt(r.iterations)}</Num>{" "}
        iterations in <Num p={stat("server time in seconds")}>{r.seconds.toFixed(2)}</Num> s.
        {r.capped && " The neighbourhood reached the cap, so lower-PageRank neighbours were left out."}
      </p>
      <p className="small muted">Parameters: {liveParams(r.alpha, r.dangling, r.seeds)}.</p>
      <div className="card">
        <ResidualChart residuals={r.residuals} title={`live PageRank around ${r.domain}`} />
      </div>
      <ScoreTable caption={`Top ${r.top.length} domains of the neighbourhood`} rows={r.top} prov={prov} rankProv={liveRank(data, r.nodes)} />
    </div>
  );
}

function WhatIfResult({ r }: { r: WhatIfResponse }) {
  const before = egoData(r.domain, r.nodes, r.links_before, r.release, r.subgraph_top);
  const after = `${egoData(r.domain, r.nodes, r.links_after, r.release, r.subgraph_top)}, plus your hypothetical links`;
  const pb = livePageRank(r.alpha, r.dangling, r.seeds, before);
  const pa = livePageRank(r.alpha, r.dangling, r.seeds, after);
  return (
    <div className="grid" style={{ marginTop: 12 }}>
      <p className="approx">{r.label}</p>
      <div className="table-wrap card" style={{ padding: 0 }}>
        <table>
          <caption className="sr-only">Score and rank before and after adding the links</caption>
          <thead>
            <tr>
              <th>Domain</th>
              <th className="r">Score before</th>
              <th className="r">Score after</th>
              <th className="r">Rank before</th>
              <th className="r">Rank after</th>
            </tr>
          </thead>
          <tbody>
            {r.results.map((x) => (
              <tr key={x.domain}>
                <td>{x.domain}</td>
                <td className="r"><Num p={pb}>{formatScore(x.score_before)}</Num></td>
                <td className="r"><Num p={pa}>{formatScore(x.score_after)}</Num></td>
                <td className="r"><Num p={liveRank(before, r.nodes)}>{ordinalRank(x.rank_before)}</Num></td>
                <td className="r"><Num p={liveRank(after, r.nodes)}>{ordinalRank(x.rank_after)}</Num></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {r.already_linked.length > 0 && (
        <p className="note">
          Already linked, so these change nothing: {r.already_linked.join(", ")}.
        </p>
      )}
      <p className="small muted">
        Links in the neighbourhood: <Num p={statsProv("links before", before)}>{formatInt(r.links_before)}</Num> before,{" "}
        <Num p={statsProv("links after", after)}>{formatInt(r.links_after)}</Num> after (a link that already existed adds
        nothing). Computed in <Num p={statsProv("server time in seconds", after)}>{r.seconds.toFixed(2)}</Num> s.
      </p>
    </div>
  );
}

function HitsResult({ r }: { r: LiveHitsResponse }) {
  const data = `Base set of ${formatInt(r.base_size)} domains and ${formatInt(r.links)} links inside the top ${formatInt(r.subgraph_top)} domains of Common Crawl release ${r.release}`;
  const stat = (what: string) => statsProv(what, data);
  return (
    <div className="grid" style={{ marginTop: 12 }}>
      <p>
        Base set: <Num p={stat("domains in the base set")}>{formatInt(r.base_size)}</Num> domains,{" "}
        <Num p={stat("links in the base set")}>{formatInt(r.links)}</Num> links. {r.converged ? "Converged" : "Did not converge"} after{" "}
        <Num p={stat("iterations")}>{formatInt(r.iterations)}</Num> iterations in{" "}
        <Num p={stat("server time in seconds")}>{r.seconds.toFixed(2)}</Num> s.
      </p>
      <div className="card">
        <ResidualChart residuals={r.residuals} title={`HITS from ${r.roots.join(", ")}`} />
      </div>
      <div className="grid grid-2">
        <ScoreTable caption="Top authorities" rows={r.authorities} prov={liveHits("authority", r.roots, r.max_in_per_root, data)} />
        <ScoreTable caption="Top hubs" rows={r.hubs} prov={liveHits("hub", r.roots, r.max_in_per_root, data)} />
      </div>
    </div>
  );
}
