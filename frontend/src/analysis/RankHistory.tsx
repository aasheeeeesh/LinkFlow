import { useEffect, useState } from "react";
import { ApiError, liveApi, type HistoryResponse } from "../api";
import { Num } from "../components/Num";
import { UPlotChart } from "../components/UPlotChart";
import { formatInt, ordinalRank } from "../format";
import { historyRank, type Provenance } from "../provenance";
import { historySeries, shortRelease } from "./history";

type Load = { status: "loading" } | { status: "ok"; data: HistoryResponse } | { status: "unavailable"; message: string };

const domainCount = (release: string): Provenance => ({
  algorithm: "Number of domains in the release",
  params: "Rows in Common Crawl's domain rank file; ranks are positions out of this many",
  data: `Common Crawl domain graph, release ${release}`,
});

/** Common Crawl PageRank and harmonic-centrality ranks of one domain across releases, oldest first. */
export function RankHistory({ domain }: { domain: string }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });

  useEffect(() => {
    const ctrl = new AbortController();
    setLoad({ status: "loading" });
    liveApi
      .history(domain, ctrl.signal)
      .then((data) => setLoad({ status: "ok", data }))
      .catch((e: unknown) => {
        if ((e as Error).name === "AbortError") return;
        setLoad({ status: "unavailable", message: e instanceof ApiError ? e.message : String(e) });
      });
    return () => ctrl.abort();
  }, [domain]);

  return (
    <section aria-labelledby="history-heading" style={{ marginTop: 32 }}>
      <h2 id="history-heading">Rank history</h2>
      {load.status === "loading" && <p className="muted" aria-live="polite">Loading rank history…</p>}
      {load.status === "unavailable" && <p className="note">{load.message}</p>}
      {load.status === "ok" && <HistoryBody data={load.data} />}
    </section>
  );
}

function HistoryBody({ data }: { data: HistoryResponse }) {
  const { points } = data;
  const labels = points.map((p) => shortRelease(p.release));
  return (
    <>
      <p className="muted small">
        Common Crawl's own ranks for {data.domain} in each release, oldest first. Each release ranks a different number
        of domains, so a change in rank can come from the graph growing or shrinking as well as from links to this domain.
      </p>
      {points.length >= 2 ? (
        <div className="card">
          <UPlotChart
            optionsKey={`${data.domain}-${points.length}`}
            data={historySeries(points)}
            height={260}
            ariaLabel={`Line chart of ${data.domain}'s Common Crawl PageRank rank and harmonic-centrality rank over ${points.length} releases, rank 1 at the top. The table below lists the values.`}
            options={(c, width, height) => ({
              width,
              height,
              // Pad the x range by a third of a release so the first and last labels are not clipped.
              scales: { x: { time: false, range: (_u, min, max) => [min - 0.35, max + 0.35] }, y: { distr: 3, dir: -1 } },
              axes: [
                { stroke: c.text, grid: { stroke: c.border, width: 1 }, ticks: { stroke: c.border }, incrs: [1],
                  values: (_u, splits) => splits.map((v) => (Number.isInteger(v) ? labels[v] ?? "" : "")) },
                { label: "Rank (log scale, 1 at top)", stroke: c.text, grid: { stroke: c.border, width: 1 },
                  ticks: { stroke: c.border }, size: 80, values: (_u, splits) => splits.map((v) => (v == null ? "" : formatInt(v))) },
              ],
              series: [
                { label: "Release", value: (_u, v) => (v == null ? "" : labels[v] ?? "") },
                { label: "PageRank rank", stroke: c.series1, width: 2, points: { show: true, size: 6 } },
                { label: "Harmonic centrality rank", stroke: c.series2, width: 2, dash: [6, 4], points: { show: true, size: 6 } },
              ],
            })}
          />
        </div>
      ) : (
        <p className="note">Only the current release is available for this domain, so there is no line to draw yet.</p>
      )}
      <div className="table-wrap card" style={{ padding: 0, marginTop: 12 }}>
        <table>
          <caption className="sr-only">Rank of {data.domain} per Common Crawl release</caption>
          <thead>
            <tr>
              <th>Release</th>
              <th className="r">PageRank rank</th>
              <th className="r">Harmonic centrality rank</th>
              <th className="r">Domains in release</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.release}>
                <td>
                  {shortRelease(p.release)} <span className="muted small">{p.release}</span>
                </td>
                <td className="r">
                  <Num p={historyRank("pagerank", p.release, p.domains)}>{ordinalRank(p.pr_rank)}</Num>
                </td>
                <td className="r">
                  <Num p={historyRank("harmonic", p.release, p.domains)}>{ordinalRank(p.hc_rank)}</Num>
                </td>
                <td className="r">
                  <Num p={domainCount(p.release)}>{formatInt(p.domains)}</Num>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.not_in_release.length > 0 && (
        <p className="small muted">
          Not in the rank file of: {data.not_in_release.map(shortRelease).join(", ")}.
        </p>
      )}
      {data.not_loaded.length > 0 && (
        <p className="small muted">
          Earlier releases not loaded on this server: {data.not_loaded.map(shortRelease).join(", ")}. An operator loads
          them with <code>python -m backend.jobs.load_history</code>.
        </p>
      )}
    </>
  );
}
