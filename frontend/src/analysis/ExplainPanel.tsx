import cytoscape from "cytoscape";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { analysisApi, ApiError, type ExplainResponse } from "../api";
import { Num } from "../components/Num";
import { formatInt, formatScore } from "../format";
import { subgraphData, type Provenance } from "../provenance";
import { cssVar, useThemeVersion } from "../theme";

export function ExplainPanel({ domain, release, top }: { domain: string; release: string; top: number }) {
  const [data, setData] = useState<ExplainResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setData(null);
    setError(null);
    analysisApi
      .explain(domain, ctrl.signal)
      .then(setData)
      .catch((e: unknown) => {
        if ((e as Error).name !== "AbortError") setError(e instanceof ApiError ? e.message : String(e));
      });
    return () => ctrl.abort();
  }, [domain]);

  return (
    <section aria-labelledby="explain-heading" className="card" style={{ marginTop: 20 }}>
      <h3 id="explain-heading" style={{ marginTop: 0 }}>
        Explain this score
      </h3>
      {error && <p className="error">{error}</p>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && <ExplainBody data={data} release={release} top={top} />}
    </section>
  );
}

function ExplainBody({ data, release, top }: { data: ExplainResponse; release: string; top: number }) {
  const prov = (what: string, params: string): Provenance => ({
    algorithm: `${what} (${data.label})`,
    params,
    data: subgraphData(release, top),
  });
  const parts = [
    { key: "links", label: "Links from other domains", part: data.from_links, color: "var(--series-1)",
      params: `α × Σ p(v)/out(v) over all ${formatInt(data.in_links)} in-links` },
    { key: "teleport", label: "Teleportation", part: data.from_teleport, color: "var(--series-2)",
      params: `(1 − α)/n with α = ${data.alpha} and n = ${formatInt(data.nodes)}` },
    { key: "dangling", label: "Rank redistributed from dangling domains", part: data.from_dangling, color: "var(--series-3)",
      params: "α × (total score of domains without out-links) / n" },
  ];
  return (
    <>
      <p className="small muted" style={{ marginTop: 0 }}>
        Using {data.label}. In PageRank a domain v passes α · p(v) / out(v) to each domain it links to, where p(v) is its
        score and out(v) its number of out-links within the subgraph. The three parts below add up to this domain's
        score of{" "}
        <Num p={prov("PageRank score", "the fixed point of the power iteration")}>{formatScore(data.score)}</Num>.
      </p>
      <div className="explain-bar" role="img" aria-label={parts.map((p) => `${p.label}: ${p.part.percent.toFixed(1)}%`).join("; ")}>
        {parts.map((p) => (
          <span key={p.key} style={{ width: `${Math.max(0, p.part.percent)}%`, background: p.color }} />
        ))}
      </div>
      <ul className="explain-legend">
        {parts.map((p) => (
          <li key={p.key}>
            <span className="swatch" style={{ background: p.color }} aria-hidden="true" />
            {p.label}:{" "}
            <b>
              <Num p={prov(`${p.label}, share of the score`, p.params)}>{p.part.percent.toFixed(2)}%</Num>
            </b>
          </li>
        ))}
      </ul>

      {data.contributors.length === 0 ? (
        <p>No domain in the subgraph links here, so the score comes entirely from teleportation and dangling rank.</p>
      ) : (
        <>
          <h4 style={{ marginBottom: 6 }}>
            Top {data.shown} of {formatInt(data.in_links)} linking domains
          </h4>
          <EgoGraph data={data} />
          <div className="table-wrap" style={{ marginTop: 10 }}>
            <table>
              <thead>
                <tr>
                  <th>Linking domain</th>
                  <th className="r">Its score p(v)</th>
                  <th className="r">Its out-links</th>
                  <th className="r">Share passed here</th>
                  <th className="r">% of this score</th>
                </tr>
              </thead>
              <tbody>
                {data.contributors.map((c) => (
                  <tr key={c.domain}>
                    <td>
                      <Link to={`/domain/${c.domain}`}>{c.domain}</Link>
                    </td>
                    <td className="r">
                      <Num p={prov(`PageRank of ${c.domain}`, "score of the linking domain")}>{formatScore(c.score)}</Num>
                    </td>
                    <td className="r">
                      <Num p={prov(`Out-links of ${c.domain}`, "links to other domains inside the subgraph")}>{formatInt(c.out_degree)}</Num>
                    </td>
                    <td className="r">
                      <Num p={prov("Share passed along this link", `α × p(v) / out(v) = ${data.alpha} × ${formatScore(c.score)} / ${formatInt(c.out_degree)}`)}>
                        {formatScore(c.share)}
                      </Num>
                    </td>
                    <td className="r">
                      <Num p={prov("Share as a percentage of this domain's score", "share / p(this domain) × 100")}>
                        {c.percent.toFixed(2)}%
                      </Num>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

function EgoGraph({ data }: { data: ExplainResponse }) {
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const themeVersion = useThemeVersion();

  useEffect(() => {
    if (!ref.current) return;
    const maxShare = Math.max(...data.contributors.map((c) => c.share), 1e-300);
    const share = new Map(data.contributors.map((c) => [c.domain, c.share]));
    const c = {
      node: cssVar("--node"), center: cssVar("--series-2"), edge: cssVar("--edge"), text: cssVar("--text"), bg: cssVar("--surface"),
    };
    const cy = cytoscape({
      container: ref.current,
      userZoomingEnabled: false,
      boxSelectionEnabled: false,
      autoungrabify: true,
      elements: [
        ...data.ego.nodes.map((d) => ({
          data: { id: d, label: d, size: d === data.domain ? 46 : 14 + 30 * Math.sqrt((share.get(d) ?? 0) / maxShare) },
          classes: d === data.domain ? "center" : "",
        })),
        ...data.ego.edges.map(([s, t]) => ({
          data: { id: `${s}>${t}`, source: s, target: t, w: t === data.domain ? 1 + 5 * ((share.get(s) ?? 0) / maxShare) : 1 },
          classes: t === data.domain ? "into" : "among",
        })),
      ],
      style: [
        { selector: "node", style: { width: "data(size)", height: "data(size)", "background-color": c.node, label: "data(label)",
          "font-size": 10, color: c.text, "text-valign": "bottom", "text-margin-y": 3, "text-background-color": c.bg,
          "text-background-opacity": 0.75, "text-background-padding": "1px" } },
        { selector: "node.center", style: { "background-color": c.center, "font-size": 12, "font-weight": 700 } },
        { selector: "edge", style: { "curve-style": "bezier", "target-arrow-shape": "triangle", "line-color": c.edge,
          "target-arrow-color": c.edge, width: "data(w)", opacity: 0.85 } },
        { selector: "edge.among", style: { opacity: 0.25, width: 1 } },
      ],
      layout: { name: "concentric", concentric: (n: cytoscape.NodeSingular) => (n.hasClass("center") ? 2 : 1), levelWidth: () => 1, minNodeSpacing: 18, padding: 20 },
    });
    cy.on("tap", "node", (e) => {
      const d = e.target.id();
      if (d !== data.domain) navigate(`/domain/${d}`);
    });
    return () => cy.destroy();
  }, [data, navigate, themeVersion]);

  return (
    <div
      ref={ref}
      className="ego-graph"
      role="img"
      aria-label={`Graph of ${data.domain} and the ${data.shown} domains passing it the most PageRank; edge width shows the share. The table below lists the same values.`}
    />
  );
}
