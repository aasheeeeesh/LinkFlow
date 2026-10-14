import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import type uPlot from "uplot";
import { analysisApi, ApiError, type ScoresResponse, type VariantScore } from "../api";
import { LoadErrorBoundary } from "../components/LoadErrorBoundary";
import { Num } from "../components/Num";
import { UPlotChart } from "../components/UPlotChart";
import { formatInt, formatPercentile, formatScore, ordinalRank } from "../format";
import { lfPercentile, lfRank, lfScore, subgraphData, type Provenance } from "../provenance";
import { computeComposite } from "./composite";

const ExplainPanel = lazy(() => import("./ExplainPanel").then((m) => ({ default: m.ExplainPanel })));

type Load = { status: "loading" } | { status: "ok"; data: ScoresResponse } | { status: "unavailable"; message: string };

const isReferencePageRank = (s: VariantScore) =>
  s.algorithm === "pagerank" && s.params.alpha === 0.85 && s.params.dangling === "teleport";

/** Default composite weights: the three measures the disagreements page compares. */
function defaultWeight(s: VariantScore): number {
  if (isReferencePageRank(s) || s.algorithm === "trustrank" || s.algorithm === "seed_distance") return 1;
  return 0;
}

export function OwnScores({ domain }: { domain: string }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });

  useEffect(() => {
    const ctrl = new AbortController();
    setLoad({ status: "loading" });
    analysisApi
      .scores(domain, ctrl.signal)
      .then((data) => setLoad({ status: "ok", data }))
      .catch((e: unknown) => {
        if ((e as Error).name === "AbortError") return;
        setLoad({ status: "unavailable", message: e instanceof ApiError ? e.message : String(e) });
      });
    return () => ctrl.abort();
  }, [domain]);

  return (
    <section aria-labelledby="own-scores-heading" style={{ marginTop: 32 }}>
      <h2 id="own-scores-heading">Linkflow Lab's own scores</h2>
      {load.status === "loading" && <p className="muted">Loading…</p>}
      {load.status === "unavailable" && (
        <p className="note" role="note">
          {load.message}
        </p>
      )}
      {load.status === "ok" && <OwnScoresBody data={load.data} />}
    </section>
  );
}

function OwnScoresBody({ data }: { data: ScoresResponse }) {
  const { release, subgraph_top: top } = data;
  const scores = data.scores;
  const prov = (s: VariantScore) => lfScore(s.label, s.params, release, top);
  const ordered = useMemo(
    () => [...scores].sort((a, b) => a.algorithm.localeCompare(b.algorithm) || a.label.localeCompare(b.label)),
    [scores],
  );
  return (
    <>
      <p className="prose">
        Computed by Linkflow Lab on a subgraph: the top {formatInt(top)} domains by Common Crawl's harmonic centrality
        and only the links between them ({formatInt(data.subgraph_nodes)} domains). Because links from outside the set
        are left out, these values differ from Common Crawl's own PageRank above. Percentiles and ranks are within the
        subgraph.
      </p>
      <div className="table-wrap card" style={{ padding: 0 }}>
        <table>
          <thead>
            <tr>
              <th>Algorithm and parameters</th>
              <th className="r">Score</th>
              <th className="r">Percentile</th>
              <th className="r">Rank</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((s) => (
              <tr key={s.params_hash}>
                <td>{s.label}</td>
                <td className="r">
                  <Num p={prov(s)}>{formatScore(s.score)}</Num>
                </td>
                <td className="r">
                  <Num p={lfPercentile(s.label, release, top)}>{formatPercentile(s.percentile)}</Num>
                </td>
                <td className="r">
                  <Num p={lfRank(s.label, release, top)}>{ordinalRank(s.rank)}</Num>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Composite data={data} />
      {data.spam_mass && <SpamMassIndicator data={data} />}
      <Sensitivity data={data} />
      <LoadErrorBoundary>
      <Suspense fallback={<p className="muted">Loading the explanation…</p>}>
        <ExplainPanel domain={data.domain} release={release} top={top} />
      </Suspense>
      </LoadErrorBoundary>
    </>
  );
}

function Composite({ data }: { data: ScoresResponse }) {
  const { release, subgraph_top: top } = data;
  const parts = data.scores.filter((s) => s.algorithm !== "spam_mass");
  const [weights, setWeights] = useState<Record<string, number>>(() =>
    Object.fromEntries(parts.map((s) => [s.params_hash, defaultWeight(s)])),
  );
  const result = computeComposite(
    parts.map((s) => ({ id: s.params_hash, percentile: s.percentile, weight: weights[s.params_hash] ?? 0 })),
  );
  const rows = parts.map((s, i) => ({
    s,
    raw: result.rows[i].weight,
    w: result.rows[i].share,
    contribution: result.rows[i].contribution,
  }));
  const composite = result.composite ?? 0;
  const total = result.composite === null ? 0 : 1;
  const used = rows.filter((r) => r.raw > 0);
  const compositeProv: Provenance = {
    algorithm: "Composite score (weighted sum of percentiles)",
    params: used.map((r) => `${r.s.label}: weight ${(100 * r.w).toFixed(1)}%`).join(" · ") || "no weights set",
    data: subgraphData(release, top),
  };

  return (
    <section aria-labelledby="composite-heading" className="card" style={{ marginTop: 20 }}>
      <h3 id="composite-heading" style={{ marginTop: 0 }}>
        Composite score
      </h3>
      <p className="small muted">
        Each algorithm's percentile, weighted by the sliders (weights are rescaled to sum to 100%). The composite is a
        presentation device that depends entirely on these weights; the breakdown shows exactly how it is formed. Spam
        mass is left out because a higher value is worse.
      </p>
      {total > 0 ? (
        <p style={{ fontSize: "1.5rem", fontWeight: 700, margin: "6px 0 12px" }}>
          <Num p={compositeProv}>{composite.toFixed(2)}</Num>
          <span className="muted small" style={{ fontWeight: 400 }}>
            {" "}
            out of 100
          </span>
        </p>
      ) : (
        <p className="warn">Give at least one algorithm a weight above zero.</p>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Algorithm</th>
              <th>Weight</th>
              <th className="r">Share</th>
              <th className="r">Percentile</th>
              <th className="r">Contribution</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ s, raw, w, contribution }) => (
              <tr key={s.params_hash}>
                <td>{s.label}</td>
                <td style={{ minWidth: 140 }}>
                  <input
                    type="range"
                    min={0}
                    max={10}
                    step={1}
                    value={raw}
                    aria-label={`Weight for ${s.label}`}
                    aria-valuetext={`${raw} of 10`}
                    onChange={(e) => setWeights((ws) => ({ ...ws, [s.params_hash]: Number(e.target.value) }))}
                  />
                </td>
                <td className="r">
                  <Num
                    p={{
                      algorithm: `Weight share of ${s.label} in the composite`,
                      params: `slider value ${raw} divided by the sum of all slider values`,
                      data: subgraphData(release, top),
                    }}
                  >
                    {(100 * w).toFixed(1)}%
                  </Num>
                </td>
                <td className="r">
                  <Num p={lfPercentile(s.label, release, top)}>{formatPercentile(s.percentile)}</Num>
                </td>
                <td className="r">
                  <Num
                    p={{
                      algorithm: `Contribution of ${s.label} to the composite`,
                      params: `weight ${(100 * w).toFixed(1)}% × percentile ${formatPercentile(s.percentile)}`,
                      data: subgraphData(release, top),
                    }}
                  >
                    {contribution.toFixed(2)}
                  </Num>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function SpamMassIndicator({ data }: { data: ScoresResponse }) {
  const mass = data.spam_mass!;
  const [threshold, setThreshold] = useState(mass.threshold);
  const variant = data.scores.find((s) => s.algorithm === "spam_mass")!;
  const m = mass.relative_mass;
  const flagged = m > threshold;
  const prov = lfScore(variant.label, variant.params, data.release, data.subgraph_top);
  let explanation: string;
  if (m <= 0) {
    explanation =
      "The trusted seed domains explain all of this domain's PageRank: links that can be traced back to them carry at least as much rank as the domain has.";
  } else if (!flagged) {
    explanation = `About ${(100 * m).toFixed(0)}% of this domain's PageRank cannot be traced back to the trusted seed domains. That is below the threshold you set.`;
  } else {
    explanation = `About ${(100 * m).toFixed(0)}% of this domain's PageRank cannot be traced back to the trusted seed domains, above the threshold you set. Link-spam schemes look like this, but so do legitimate sites the trusted seeds do not reach, such as regional or niche sites. Treat it as a reason to look closer, not a verdict.`;
  }
  return (
    <section aria-labelledby="spam-heading" className="card" style={{ marginTop: 20 }}>
      <h3 id="spam-heading" style={{ marginTop: 0 }}>
        Spam mass
      </h3>
      <p style={{ margin: "4px 0 10px" }}>
        Relative spam mass{" "}
        <b>
          <Num p={prov}>{m.toFixed(3)}</Num>
        </b>{" "}
        {flagged ? (
          <span className="badge" style={{ background: "var(--warn-bg)", color: "var(--text)" }}>
            Likely link-spam supported
          </span>
        ) : (
          <span className="badge">Not flagged</span>
        )}
      </p>
      <label htmlFor="spam-threshold">
        Flag above <b>{threshold.toFixed(2)}</b>
      </label>
      <input
        id="spam-threshold"
        type="range"
        min={0}
        max={1}
        step={0.05}
        value={threshold}
        onChange={(e) => setThreshold(Number(e.target.value))}
      />
      <p className="small" style={{ margin: "8px 0 0" }}>
        {explanation}
      </p>
      <p className="small muted" style={{ margin: "6px 0 0" }}>
        Relative mass m = 1 − p⁺/p, where p is PageRank and p⁺ is PageRank personalized on the 200 trusted seeds
        (Gyöngyi et al., 2006). Values can be negative when the trusted seeds over-explain a domain.
      </p>
    </section>
  );
}

function Sensitivity({ data }: { data: ScoresResponse }) {
  const series = data.scores
    .filter((s) => s.algorithm === "pagerank" && s.params.dangling === "teleport")
    .sort((a, b) => Number(a.params.alpha) - Number(b.params.alpha));
  const chartData = useMemo<uPlot.AlignedData>(
    () => [series.map((s) => Number(s.params.alpha)), series.map((s) => s.rank)],
    [series],
  );
  if (series.length < 2) return null;
  const { release, subgraph_top: top } = data;
  return (
    <section aria-labelledby="sensitivity-heading" className="card" style={{ marginTop: 20 }}>
      <h3 id="sensitivity-heading" style={{ marginTop: 0 }}>
        Sensitivity to the damping factor α
      </h3>
      <p className="small muted">
        This domain's PageRank rank within the subgraph at each stored α (dangling = teleport). Higher on the chart is
        a better rank. A flat line means the position does not depend on how often the random surfer teleports.
      </p>
      <UPlotChart
        optionsKey={`sens-${data.domain}`}
        data={chartData}
        height={220}
        ariaLabel={`Line chart of ${data.domain}'s PageRank rank at α = ${series.map((s) => s.params.alpha).join(", ")}. The table below lists the same values.`}
        options={(c, width, height) => ({
          width,
          height,
          legend: { show: false },
          scales: { x: { time: false, range: [0.45, 1] }, y: { distr: 3, dir: -1 } },
          axes: [
            { label: "α (damping factor)", stroke: c.text, grid: { stroke: c.border, width: 1 }, ticks: { stroke: c.border },
              splits: () => series.map((s) => Number(s.params.alpha)) },
            { label: "Rank (log)", stroke: c.text, grid: { stroke: c.border, width: 1 }, ticks: { stroke: c.border }, size: 70,
              values: (_u, splits) => splits.map((v) => (v == null ? "" : `#${formatInt(Math.round(v))}`)) },
          ],
          series: [{}, { label: "Rank", stroke: c.series1, width: 2, points: { show: true, size: 7 } }],
        })}
      />
      <div className="table-wrap" style={{ marginTop: 8 }}>
        <table>
          <thead>
            <tr>
              <th>α</th>
              <th className="r">Rank</th>
              <th className="r">Percentile</th>
            </tr>
          </thead>
          <tbody>
            {series.map((s) => (
              <tr key={s.params_hash}>
                <td>{Number(s.params.alpha).toFixed(2)}</td>
                <td className="r">
                  <Num p={lfRank(s.label, release, top)}>{ordinalRank(s.rank)}</Num>
                </td>
                <td className="r">
                  <Num p={lfPercentile(s.label, release, top)}>{formatPercentile(s.percentile)}</Num>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
