import { useEffect, useMemo, useState } from "react";
import type uPlot from "uplot";
import { analysisApi, ApiError, type ConvergenceResponse, type RunHistory } from "../api";
import { Num } from "../components/Num";
import { UPlotChart } from "../components/UPlotChart";
import { formatInt } from "../format";
import { subgraphData } from "../provenance";
import { cssVar } from "../theme";
import { usePageTitle } from "../usePageTitle";

const PALETTE = ["--series-1", "--series-2", "--series-3", "--danger", "--accent", "--text-muted"];

const runName = (r: RunHistory) => (r.run === r.label || r.run === "pagerank" || r.run.startsWith("topic:") || r.run === "trustrank" ? r.label : `${r.label} — ${r.run}`);

export function ConvergenceLab() {
  usePageTitle("Convergence Lab");
  const [data, setData] = useState<ConvergenceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    const ctrl = new AbortController();
    analysisApi
      .convergence(ctrl.signal)
      .then((d) => {
        setData(d);
        // Start with the four PageRank α runs, the clearest comparison.
        setSelected(new Set(d.runs.filter((r) => r.run === "pagerank" && r.label.includes("teleport")).map((r) => `${r.params_hash}|${r.run}`)));
      })
      .catch((e: unknown) => {
        if ((e as Error).name !== "AbortError") setError(e instanceof ApiError ? e.message : String(e));
      });
    return () => ctrl.abort();
  }, []);

  const iterative = useMemo(() => (data ? data.runs.filter((r) => r.residuals.length > 0) : []), [data]);
  const shown = iterative.filter((r) => selected.has(`${r.params_hash}|${r.run}`));
  const chartData = useMemo<uPlot.AlignedData>(() => {
    const maxLen = Math.max(1, ...shown.map((r) => r.residuals.length));
    const xs = Array.from({ length: maxLen }, (_, i) => i + 1);
    return [xs, ...shown.map((r) => xs.map((_, i) => (r.residuals[i] > 0 ? r.residuals[i] : null)))];
  }, [shown]);
  const key = shown.map((r) => `${r.params_hash}|${r.run}`).join(",");

  return (
    <>
      <h1>Convergence Lab</h1>
      <p className="lede">
        How fast each stored computation converged: the L1 residual ‖p<sub>k</sub> − p<sub>k−1</sub>‖₁ after every
        iteration of the power method, on the {data ? formatInt(data.subgraph_top) : "top"}-domain subgraph.
      </p>
      {error && <p className="note">{error}</p>}
      {data && (
        <>
          <section className="card" aria-labelledby="chart-heading">
            <h2 id="chart-heading" style={{ marginTop: 0, fontSize: "1.1rem" }}>
              Residual per iteration (log scale)
            </h2>
            {shown.length === 0 ? (
              <p className="muted">Tick at least one run below to plot it.</p>
            ) : (
              <UPlotChart
                optionsKey={key}
                data={chartData}
                height={320}
                ariaLabel={`Line chart of residual per iteration for ${shown.map(runName).join("; ")}. The table below lists iteration counts.`}
                options={(c, width, height) => ({
                  width,
                  height,
                  scales: { x: { time: false }, y: { distr: 3 } },
                  axes: [
                    { label: "Iteration", stroke: c.text, grid: { stroke: c.border, width: 1 }, ticks: { stroke: c.border } },
                    { label: "L1 residual", stroke: c.text, grid: { stroke: c.border, width: 1 }, ticks: { stroke: c.border },
                      size: 70, values: (_u, splits) => splits.map((v) => (v == null ? "" : v.toExponential(0))) },
                  ],
                  series: [
                    { label: "Iteration" },
                    ...shown.map((r, i) => ({ label: runName(r), stroke: cssVar(PALETTE[i % PALETTE.length]), width: 2,
                      dash: i >= PALETTE.length ? [6, 4] : undefined, points: { show: false } })),
                  ],
                })}
              />
            )}
            <p className="small muted" style={{ marginBottom: 0 }}>
              For comparison, the 1999 PageRank report states that its computation on a database of 322 million links
              converged to a reasonable tolerance in roughly 52 iterations. That figure is quoted here; it is not
              plotted, because the report does not publish its residual curve. {subgraphData(data.release, data.subgraph_top)}.
            </p>
          </section>

          <h2>Runs</h2>
          <div className="table-wrap card" style={{ padding: 0 }}>
            <table>
              <thead>
                <tr>
                  <th>Plot</th>
                  <th>Computation</th>
                  <th className="r">Iterations</th>
                  <th>Converged</th>
                  <th className="r">Final residual</th>
                  <th className="r">Seconds</th>
                </tr>
              </thead>
              <tbody>
                {data.runs.map((r) => {
                  const id = `${r.params_hash}|${r.run}`;
                  const iterativeRun = r.residuals.length > 0;
                  const runProv = { algorithm: runName(r), params: "power iteration until the L1 residual is below 1e-8 or 1,000 iterations", data: subgraphData(data.release, data.subgraph_top) };
                  return (
                    <tr key={id}>
                      <td>
                        {iterativeRun && (
                          <input
                            type="checkbox"
                            aria-label={`Plot ${runName(r)}`}
                            checked={selected.has(id)}
                            onChange={() =>
                              setSelected((s) => {
                                const next = new Set(s);
                                if (next.has(id)) next.delete(id);
                                else next.add(id);
                                return next;
                              })
                            }
                          />
                        )}
                      </td>
                      <td>{runName(r)}</td>
                      <td className="r">
                        {iterativeRun ? <Num p={runProv}>{formatInt(r.iterations)}</Num> : <span className="muted">BFS, {r.iterations} levels</span>}
                      </td>
                      <td>{iterativeRun ? (r.converged ? "yes" : "no: stopped at the limit") : "exact"}</td>
                      <td className="r">
                        {iterativeRun ? <Num p={runProv}>{r.residuals[r.residuals.length - 1].toExponential(2)}</Num> : "–"}
                      </td>
                      <td className="r">
                        <Num p={{ ...runProv, algorithm: `Wall-clock time of ${runName(r)}` }}>{r.seconds.toFixed(1)}</Num>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="small muted">
            Remove &amp; re-add finishes with a fixed number of extra iterations (one per stripping round), so its final
            residual is not a convergence test. Seed distance is a breadth-first search, not an iteration.
          </p>
        </>
      )}
    </>
  );
}
