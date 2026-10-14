import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import uPlot from "uplot";
import { api, ApiError, type CompareResponse, type DomainRanks } from "../api";
import { Num } from "../components/Num";
import { UPlotChart } from "../components/UPlotChart";
import { formatInt, formatPercentile, formatScore, ordinalRank } from "../format";
import { ccHarmonic, ccHosts, ccPageRank, ccPercentile, ccRank } from "../provenance";
import { withAlpha } from "../theme";
import { usePageTitle } from "../usePageTitle";

const MAX = 10;

type ChartMetric = "pr_pct" | "hc_pct" | "pr_val" | "hc_val";
// Values first: well-known domains all sit near the 100th percentile, where percentile bars look identical.
const CHART_METRICS: Record<ChartMetric, { label: string; log: boolean; get: (d: DomainRanks) => number }> = {
  pr_val: { label: "PageRank value (Common Crawl, log scale)", log: true, get: (d) => d.pagerank.value },
  hc_val: { label: "Harmonic centrality value (Common Crawl, log scale)", log: true, get: (d) => d.harmonic_centrality.value },
  pr_pct: { label: "PageRank percentile (Common Crawl)", log: false, get: (d) => d.pagerank.percentile },
  hc_pct: { label: "Harmonic centrality percentile (Common Crawl)", log: false, get: (d) => d.harmonic_centrality.percentile },
};

function parseDomains(raw: string): string[] {
  return [...new Set(raw.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean))];
}

export function Compare() {
  usePageTitle("Compare");
  const [params, setParams] = useSearchParams();
  const requested = useMemo(() => parseDomains(params.get("d") ?? ""), [params]);
  const [draft, setDraft] = useState(requested.join(", "));
  const [result, setResult] = useState<CompareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [chartMetric, setChartMetric] = useState<ChartMetric>("pr_val");

  useEffect(() => setDraft(requested.join(", ")), [requested]);

  useEffect(() => {
    if (requested.length === 0) {
      setResult(null);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    api
      .compare(requested, ctrl.signal)
      .then(setResult)
      .catch((e: unknown) => {
        if ((e as Error).name !== "AbortError") setError(e instanceof ApiError ? e.message : String(e));
      })
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, [requested]);

  const draftCount = parseDomains(draft).length;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const ds = parseDomains(draft);
    if (ds.length === 0 || ds.length > MAX) return;
    setParams({ d: ds.join(",") });
  };

  const rows = result?.results ?? [];
  const metricDef = CHART_METRICS[chartMetric];
  const chartData = useMemo<uPlot.AlignedData>(
    () => [rows.map((_, i) => i), rows.map((d) => metricDef.get(d))],
    [rows, metricDef],
  );
  const labels = rows.map((d) => d.domain);

  return (
    <>
      <h1>Compare domains</h1>
      <p className="lede">Up to {MAX} domains side by side, using Common Crawl's own PageRank and harmonic centrality.</p>
      <form onSubmit={submit} className="card" style={{ maxWidth: 720 }}>
        <label htmlFor="compare-input">Domains, separated by commas, spaces or new lines</label>
        <textarea
          id="compare-input"
          rows={3}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="wikipedia.org, bbc.co.uk, nasa.gov"
          aria-describedby="compare-count"
          spellCheck={false}
        />
        <div className="row" style={{ justifyContent: "space-between", marginTop: 8 }}>
          <span id="compare-count" className={draftCount > MAX ? "error small" : "muted small"}>
            {draftCount} of {MAX} domains{draftCount > MAX ? ": remove some to compare" : ""}
          </span>
          <button type="submit" className="primary" disabled={draftCount === 0 || draftCount > MAX}>
            Compare
          </button>
        </div>
      </form>

      <div aria-live="polite">
        {loading && <p className="muted">Loading…</p>}
        {error && <p className="error">{error}</p>}
      </div>

      {result && (result.not_found.length > 0 || result.invalid.length > 0) && (
        <div className="warn" style={{ marginTop: 16 }}>
          {result.not_found.map((nf) => (
            <p key={nf.query} style={{ margin: "2px 0" }}>
              <code>{nf.domain}</code>: {nf.detail}.
              {nf.suggestions.length > 0 && (
                <>
                  {" "}
                  Registered domain: {nf.suggestions.map((s) => <Link key={s} to={`/domain/${s}`}>{s}</Link>)}
                </>
              )}
            </p>
          ))}
          {result.invalid.map((iv) => (
            <p key={iv.query} style={{ margin: "2px 0" }}>
              <code>{iv.query}</code>: {iv.detail}
            </p>
          ))}
        </div>
      )}

      {result && rows.length > 0 && (
        <>
          <h2>
            Results <span className="muted small">· release {result.release}</span>
          </h2>
          <div className="table-wrap card" style={{ padding: 0 }}>
            <table>
              <thead>
                <tr>
                  <th>Domain</th>
                  <th className="r">PageRank</th>
                  <th className="r">PR rank</th>
                  <th className="r">PR percentile</th>
                  <th className="r">Harmonic centrality</th>
                  <th className="r">HC rank</th>
                  <th className="r">HC percentile</th>
                  <th className="r">Hosts</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.domain}>
                    <td>
                      <Link to={`/domain/${d.domain}`}>{d.domain}</Link>
                    </td>
                    <td className="r">
                      <Num p={ccPageRank(d.release)}>{formatScore(d.pagerank.value)}</Num>
                    </td>
                    <td className="r">
                      <Num p={ccRank("pagerank", d.release, d.total_domains)}>{ordinalRank(d.pagerank.rank)}</Num>
                    </td>
                    <td className="r">
                      <Num p={ccPercentile("pagerank", d.release)}>{formatPercentile(d.pagerank.percentile)}</Num>
                    </td>
                    <td className="r">
                      <Num p={ccHarmonic(d.release)}>{formatScore(d.harmonic_centrality.value)}</Num>
                    </td>
                    <td className="r">
                      <Num p={ccRank("harmonic", d.release, d.total_domains)}>
                        {ordinalRank(d.harmonic_centrality.rank)}
                      </Num>
                    </td>
                    <td className="r">
                      <Num p={ccPercentile("harmonic", d.release)}>
                        {formatPercentile(d.harmonic_centrality.percentile)}
                      </Num>
                    </td>
                    <td className="r">
                      <Num p={ccHosts(d.release)}>{formatInt(d.n_hosts)}</Num>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="row" style={{ justifyContent: "space-between", marginTop: 24 }}>
            <h2 style={{ margin: 0 }}>Chart</h2>
            <label className="row">
              <span>Show</span>
              <select value={chartMetric} onChange={(e) => setChartMetric(e.target.value as ChartMetric)}>
                {Object.entries(CHART_METRICS).map(([k, m]) => (
                  <option key={k} value={k}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="card" style={{ marginTop: 12 }}>
            <UPlotChart
              optionsKey={`${chartMetric}|${labels.join(",")}`}
              data={chartData}
              height={300}
              ariaLabel={`Bar chart of ${metricDef.label} for ${labels.join(", ")}. The table above lists the same values.`}
              options={(c, width, height) => ({
                width,
                height,
                legend: { show: false },
                cursor: { points: { show: false } },
                scales: {
                  x: { time: false, range: [-0.5, labels.length - 0.5] },
                  y: metricDef.log ? { distr: 3 } : { range: [0, 100] },
                },
                axes: [
                  {
                    stroke: c.text,
                    grid: { show: false },
                    ticks: { stroke: c.border },
                    splits: () => labels.map((_, i) => i),
                    values: (_u, splits) => splits.map((i) => labels[i] ?? ""),
                    rotate: labels.length > 4 ? -30 : 0,
                    size: labels.length > 4 ? 100 : 40,
                  },
                  {
                    stroke: c.text,
                    grid: { stroke: c.border, width: 1 },
                    ticks: { stroke: c.border },
                    size: 64,
                    // log scales pass null for unlabelled minor ticks
                    values: (_u, splits) =>
                      splits.map((v) => (v == null ? "" : metricDef.log ? v.toExponential(0) : String(v))),
                  },
                ],
                series: [
                  {},
                  {
                    label: metricDef.label,
                    stroke: c.series1,
                    fill: withAlpha(c.series1, 0.7),
                    width: 1,
                    paths: uPlot.paths.bars!({ size: [0.6, 80] }),
                    points: { show: false },
                  },
                ],
              })}
            />
          </div>
          <p className="small muted">
            Raw values differ by orders of magnitude, so they are drawn on a logarithmic axis. Percentiles put both
            measures on a common 0 to 100 scale, but well-known domains all sit just below 100 on it.
          </p>
        </>
      )}
    </>
  );
}
