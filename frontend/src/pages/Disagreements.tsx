import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { analysisApi, ApiError, type DisagreementsResponse } from "../api";
import { Num } from "../components/Num";
import { formatPercentile } from "../format";
import { subgraphData, type Provenance } from "../provenance";
import { usePageTitle } from "../usePageTitle";

const LIMITS = [50, 100, 250, 1000];

export function Disagreements() {
  usePageTitle("Disagreements");
  const [limit, setLimit] = useState(100);
  const [data, setData] = useState<DisagreementsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setError(null);
    analysisApi
      .disagreements(limit, ctrl.signal)
      .then(setData)
      .catch((e: unknown) => {
        if ((e as Error).name !== "AbortError") setError(e instanceof ApiError ? e.message : String(e));
      });
    return () => ctrl.abort();
  }, [limit]);

  const prov = (algorithm: string, params: string): Provenance => ({
    algorithm,
    params,
    data: data ? subgraphData(data.release, data.subgraph_top) : "",
  });

  return (
    <>
      <h1>Where the algorithms disagree</h1>
      <p className="lede">
        Domains whose percentiles differ the most between PageRank, TrustRank and seed distance. A large spread means
        the domain's standing depends heavily on which question you ask: how much rank flows to it, how much trust
        reaches it from vetted seeds, or how few links separate it from them.
      </p>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <p className="small muted" style={{ margin: 0 }}>
          Spread = highest minus lowest of the three percentiles. PageRank: α = 0.85, dangling = teleport. TrustRank:
          α = 0.85, 200 trusted seeds. Seed distance: β = 0.5 from the same seeds.
        </p>
        <label className="row">
          <span>Show</span>
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
            {LIMITS.map((l) => (
              <option key={l} value={l}>
                top {l}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && <p className="note">{error}</p>}
      {data && (
        <div className="table-wrap card" style={{ padding: 0, marginTop: 12 }}>
          <table>
            <thead>
              <tr>
                <th className="r">#</th>
                <th>Domain</th>
                <th className="r">PageRank pct.</th>
                <th className="r">TrustRank pct.</th>
                <th className="r">Seed distance pct.</th>
                <th className="r">Spread</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((d, i) => (
                <tr key={d.domain}>
                  <td className="r">{i + 1}</td>
                  <td>
                    <Link to={`/domain/${d.domain}`}>{d.domain}</Link>
                  </td>
                  <td className="r">
                    <Num p={prov("Percentile of PageRank", "α = 0.85, dangling = teleport")}>{formatPercentile(d.pagerank_percentile)}</Num>
                  </td>
                  <td className="r">
                    <Num p={prov("Percentile of TrustRank", "α = 0.85, 200 trusted seeds")}>{formatPercentile(d.trustrank_percentile)}</Num>
                  </td>
                  <td className="r">
                    <Num p={prov("Percentile of seed distance", "β = 0.5 from the 200 trusted seeds")}>{formatPercentile(d.seed_distance_percentile)}</Num>
                  </td>
                  <td className="r">
                    <Num p={prov("Percentile spread", "highest minus lowest of the three percentiles")}>{d.spread.toFixed(2)}</Num>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
