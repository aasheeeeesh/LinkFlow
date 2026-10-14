import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, type DomainRanks, type Metric, type NotFound } from "../api";
import { OwnScores } from "../analysis/OwnScores";
import { RankHistory } from "../analysis/RankHistory";
import { Disclosures } from "../components/Disclosures";
import { Num } from "../components/Num";
import { SearchBox } from "../components/SearchBox";
import { formatInt, formatPercentile, formatScore, ordinalRank } from "../format";
import { ccHarmonic, ccHosts, ccPageRank, ccPercentile, ccRank, type Provenance } from "../provenance";
import { usePageTitle } from "../usePageTitle";

type Load =
  | { status: "loading" }
  | { status: "ok"; data: DomainRanks }
  | { status: "missing"; info: NotFound }
  | { status: "error"; message: string };

function MetricCard({
  title,
  metric,
  kind,
  d,
  valueP,
  explanation,
}: {
  title: string;
  metric: Metric;
  kind: "pagerank" | "harmonic";
  d: DomainRanks;
  valueP: Provenance;
  explanation: string;
}) {
  const share = (100 * metric.rank) / d.total_domains;
  return (
    <section className="card" aria-label={title}>
      <div className="stat-label">{title}</div>
      <div className="stat-value">
        <Num p={valueP}>{formatScore(metric.value)}</Num>
      </div>
      <div className="stat-sub">
        <span>
          Rank{" "}
          <b>
            <Num p={ccRank(kind, d.release, d.total_domains)}>{ordinalRank(metric.rank)}</Num>
          </b>{" "}
          of {formatInt(d.total_domains)}
        </span>
        <span>
          Percentile{" "}
          <b>
            <Num p={ccPercentile(kind, d.release)}>{formatPercentile(metric.percentile)}</Num>
          </b>
        </span>
      </div>
      <p className="small muted" style={{ margin: "10px 0 0" }}>
        {explanation} {share < 1 ? "This domain is in the top 1% of the graph by this measure." : null}
      </p>
    </section>
  );
}

export function DomainPage() {
  const { domain = "" } = useParams();
  usePageTitle(domain);
  const [load, setLoad] = useState<Load>({ status: "loading" });

  useEffect(() => {
    const ctrl = new AbortController();
    setLoad({ status: "loading" });
    api
      .domain(domain, ctrl.signal)
      .then((data) => setLoad({ status: "ok", data }))
      .catch((e: unknown) => {
        if ((e as Error).name === "AbortError") return;
        const body = e instanceof ApiError ? (e.body as Partial<NotFound> | null) : null;
        if (e instanceof ApiError && e.status === 404 && body && typeof body.domain === "string") {
          setLoad({
            status: "missing",
            info: { query: domain, domain: body.domain, detail: body.detail ?? e.message, suggestions: body.suggestions ?? [] },
          });
        } else setLoad({ status: "error", message: e instanceof ApiError ? e.message : String(e) });
      });
    return () => ctrl.abort();
  }, [domain]);

  if (load.status === "loading") {
    return (
      <p aria-live="polite" className="muted">
        Looking up {domain}…
      </p>
    );
  }
  if (load.status === "error") {
    return (
      <>
        <h1>{domain}</h1>
        <p className="error" role="alert">
          {load.message}
        </p>
        <SearchBox initial={domain} />
      </>
    );
  }
  if (load.status === "missing") {
    const { info } = load;
    return (
      <>
        <h1>{info.domain}</h1>
        <div className="warn" role="alert">
          <p style={{ margin: 0 }}>
            <strong>{info.detail}.</strong> Common Crawl's domain graph contains only registered domains that its crawler
            reached or saw linked during the crawls this release is built from.
          </p>
          {info.suggestions.length > 0 && (
            <p style={{ margin: "8px 0 0" }}>
              Hosts are merged into their registered domain. Did you mean{" "}
              {info.suggestions.map((s, i) => (
                <span key={s}>
                  {i > 0 && ", "}
                  <Link to={`/domain/${s}`}>{s}</Link>
                </span>
              ))}
              ?
            </p>
          )}
        </div>
        <h2>Try another domain</h2>
        <SearchBox initial={info.domain} />
      </>
    );
  }

  const d = load.data;
  return (
    <>
      <p className="small muted" style={{ marginBottom: 0 }}>
        Domain
      </p>
      <h1 style={{ marginTop: 0 }}>{d.domain}</h1>
      <p className="muted">
        Common Crawl key <code>{d.domain_key}</code> ·{" "}
        <Num p={ccHosts(d.release)}>{formatInt(d.n_hosts)}</Num> {d.n_hosts === 1 ? "host" : "hosts"} merged into this
        node · release <code>{d.release}</code>
      </p>
      {d.matched_from && (
        <p className="note">
          You entered <code>{d.matched_from}</code>. Common Crawl aggregates host names into their registered domain, so
          this page shows <code>{d.domain}</code>.
        </p>
      )}

      <div className="grid grid-2">
        <MetricCard
          title="PageRank (Common Crawl)"
          kind="pagerank"
          metric={d.pagerank}
          d={d}
          valueP={ccPageRank(d.release)}
          explanation="The long-run share of time a random surfer spends on this domain when it follows links 85% of the time and jumps to a random domain otherwise. All values sum to 1 across the graph."
        />
        <MetricCard
          title="Harmonic centrality (Common Crawl)"
          kind="harmonic"
          metric={d.harmonic_centrality}
          d={d}
          valueP={ccHarmonic(d.release)}
          explanation="The sum, over every other domain, of 1 divided by the number of link hops needed to reach this domain. High values mean many domains reach it in few hops."
        />
      </div>

      <div className="note" role="note" aria-label="Source of these values">
        <strong>These values are Common Crawl's own computation</strong> for release <code>{d.release}</code>, published
        in its domain rank file; Linkflow Lab only loads and indexes them. PageRank was computed with the LAW library's
        defaults (α = 0.85, uniform teleport, dangling mass spread uniformly); harmonic centrality with WebGraph's
        HyperBall, an approximate method. Hover or focus any number for its exact definition, or read the{" "}
        <Link to="/about">methodology</Link>.
      </div>

      <h2>Why the two measures can disagree</h2>
      <p className="prose">
        PageRank rewards receiving links from domains that themselves hold a lot of rank, and it splits a domain's rank
        across all of its outgoing links. Harmonic centrality ignores rank and counts how close every other domain is, in
        link hops. A domain linked from a handful of very popular sites can rank high on PageRank, while a domain that
        is a short hop from millions of ordinary sites ranks high on harmonic centrality. A gap between the two
        percentiles is a prompt to look closer, not a verdict.
      </p>
      <p>
        <Link to={`/compare?d=${encodeURIComponent(d.domain)}`}>Compare {d.domain} with other domains</Link>
        {" · "}
        <Link to={`/live?d=${encodeURIComponent(d.domain)}`}>Analyse {d.domain}'s neighbourhood live</Link>
      </p>

      <RankHistory domain={d.domain} />

      <OwnScores domain={d.domain} />

      <footer style={{ marginTop: 32 }}>
        <Disclosures headingLevel={2} />
      </footer>
    </>
  );
}
