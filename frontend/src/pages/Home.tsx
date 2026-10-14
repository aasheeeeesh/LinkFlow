import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type TopResponse } from "../api";
import { Num } from "../components/Num";
import { SearchBox } from "../components/SearchBox";
import { formatPercentile, formatScore, ordinalRank } from "../format";
import { ccHarmonic, ccPageRank, ccPercentile, ccRank } from "../provenance";
import { usePageTitle } from "../usePageTitle";

type Metric = "pagerank" | "harmonic";

export function Home() {
  usePageTitle("");
  const [metric, setMetric] = useState<Metric>("harmonic");
  const [top, setTop] = useState<TopResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setError(null);
    api
      .top(metric, 25, ctrl.signal)
      .then(setTop)
      .catch((e: unknown) => {
        if ((e as Error).name !== "AbortError") setError(e instanceof ApiError ? e.message : String(e));
      });
    return () => ctrl.abort();
  }, [metric]);

  return (
    <>
      <h1>See how links flow between domains</h1>
      <p className="lede">
        Linkflow Lab computes link-analysis scores on the public Common Crawl web graph, exposes every parameter, and
        explains where each number comes from.
      </p>
      <SearchBox autoFocus />
      <p className="small muted" style={{ marginTop: 8 }}>
        Enter a registered domain such as <Link to="/domain/wikipedia.org">wikipedia.org</Link> or{" "}
        <Link to="/domain/bbc.co.uk">bbc.co.uk</Link>. URLs and <code>www.</code> host names are accepted.
      </p>

      <div className="grid grid-2" style={{ marginTop: 28 }}>
        <section className="card" aria-labelledby="what-it-is">
          <h2 id="what-it-is" style={{ marginTop: 0 }}>
            What it computes
          </h2>
          <ul>
            <li>
              Common Crawl's own <strong>PageRank</strong> and <strong>harmonic centrality</strong> for about 118 million
              domains, with ranks and percentiles.
            </li>
            <li>
              Side-by-side <Link to="/compare">comparisons</Link> of up to ten domains.
            </li>
            <li>
              A <Link to="/playground">playground</Link> where you build a small graph and step through PageRank,
              personalized PageRank, HITS and harmonic centrality one iteration at a time.
            </li>
            <li>
              A <Link to="/about">methodology</Link> page with the formula, defaults, source paper and limitations of
              every algorithm.
            </li>
          </ul>
        </section>
        <section className="card" aria-labelledby="what-it-is-not">
          <h2 id="what-it-is-not" style={{ marginTop: 0 }}>
            What it is not
          </h2>
          <ul>
            <li>
              <strong>Not Google's PageRank.</strong> Google has not published PageRank values since 2016, and nothing
              here reflects Google's ranking.
            </li>
            <li>
              <strong>Not page-level.</strong> Scores belong to whole registered domains.
            </li>
            <li>
              <strong>Not absolute.</strong> The graph only contains what Common Crawl crawled, and its crawler favours
              domains that are already central. Read scores as relative positions.
            </li>
          </ul>
        </section>
      </div>

      <section aria-labelledby="top-heading">
        <div className="row" style={{ justifyContent: "space-between", marginTop: 28 }}>
          <h2 id="top-heading" style={{ margin: 0 }}>
            Top 25 domains{top ? <span className="muted small"> · release {top.release}</span> : null}
          </h2>
          <div className="segmented" role="group" aria-label="Rank by">
            <button type="button" aria-pressed={metric === "harmonic"} onClick={() => setMetric("harmonic")}>
              Harmonic centrality
            </button>
            <button type="button" aria-pressed={metric === "pagerank"} onClick={() => setMetric("pagerank")}>
              PageRank
            </button>
          </div>
        </div>
        <p className="small muted">Both values are Common Crawl's own computation for this release.</p>
        {error && <p className="error">{error}</p>}
        {top && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th className="r">Rank</th>
                  <th>Domain</th>
                  <th className="r">{metric === "pagerank" ? "PageRank" : "Harmonic centrality"}</th>
                  <th className="r">Percentile</th>
                </tr>
              </thead>
              <tbody>
                {top.results.map((d) => {
                  const m = metric === "pagerank" ? d.pagerank : d.harmonic_centrality;
                  return (
                    <tr key={d.domain}>
                      <td className="r">
                        <Num p={ccRank(metric, top.release, d.total_domains)}>{ordinalRank(m.rank)}</Num>
                      </td>
                      <td>
                        <Link to={`/domain/${d.domain}`}>{d.domain}</Link>
                      </td>
                      <td className="r">
                        <Num p={metric === "pagerank" ? ccPageRank(top.release) : ccHarmonic(top.release)}>
                          {formatScore(m.value)}
                        </Num>
                      </td>
                      <td className="r">
                        <Num p={ccPercentile(metric, top.release)}>{formatPercentile(m.percentile)}</Num>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
