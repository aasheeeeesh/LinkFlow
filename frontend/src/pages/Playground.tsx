import cytoscape, { type Core, type NodeSingular } from "cytoscape";
import edgehandles from "cytoscape-edgehandles";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import type uPlot from "uplot";
import type { Graph } from "../algorithms/graph";
import { harmonicCentrality } from "../algorithms/harmonic";
import { HitsRun, type HitsState } from "../algorithms/hits";
import { DANGLING_STRATEGIES, PageRankRun, type Dangling, type PageRankState } from "../algorithms/pagerank";
import { Num } from "../components/Num";
import { UPlotChart } from "../components/UPlotChart";
import { PRESETS, type PlaygroundAlgorithm, type Preset } from "../playground/presets";
import { PLAYGROUND_DATA, type Provenance } from "../provenance";
import { cssVar, useThemeVersion } from "../theme";
import { usePageTitle } from "../usePageTitle";

let edgehandlesRegistered = false;
function registerEdgehandles() {
  if (!edgehandlesRegistered) {
    cytoscape.use(edgehandles);
    edgehandlesRegistered = true;
  }
}

interface EdgeHandles {
  enableDrawMode(): void;
  disableDrawMode(): void;
  destroy(): void;
}

interface PgNode {
  id: number;
  label: string;
  x: number;
  y: number;
}
interface PgEdge {
  source: number;
  target: number;
}

type View =
  | { kind: "pagerank"; state: PageRankState }
  | { kind: "hits"; state: HitsState }
  | { kind: "harmonic"; scores: Float64Array };

/** A view tagged with the graph structure it was computed on; score index i belongs to node i of that graph. */
interface Computed {
  key: string;
  view: View;
}

const TOL = 1e-8;
const NO_RESIDUALS: number[] = [];
const RUN_RATE = 40; // iterations per second while "Run to convergence" animates
const MAX_STEPS_PER_TICK = 50;
const PR_MAX_ITER = 200;
const HITS_MAX_ITER = 100;

const DANGLING_LABELS: Record<Dangling, { name: string; help: string }> = {
  teleport: { name: "Teleport", help: "Rank held by dangling nodes is redistributed through the teleport vector v." },
  uniform: { name: "Uniform", help: "Rank held by dangling nodes is spread evenly over all nodes." },
  self_loop: { name: "Self-loop", help: "Each dangling node links to itself and keeps its rank." },
  remove_readd: {
    name: "Remove & re-add (1999 paper)",
    help: "Strip dangling nodes repeatedly, rank the remaining core, add them back, then run one extra iteration per stripping round (Page et al. 1999, section 2.7).",
  },
};

const ALGORITHM_LABELS: Record<PlaygroundAlgorithm, string> = {
  pagerank: "PageRank",
  hits: "HITS (hubs and authorities)",
  harmonic: "Harmonic centrality",
};

function labelFor(index: number): string {
  return index < 26 ? String.fromCharCode(65 + index) : `N${index + 1}`;
}

function nextLabel(nodes: PgNode[]): string {
  const used = new Set(nodes.map((n) => n.label));
  for (let i = 0; ; i++) if (!used.has(labelFor(i))) return labelFor(i);
}

function fromPreset(p: Preset, firstId: number): { nodes: PgNode[]; edges: PgEdge[]; seeds: number[] } {
  const nodes = p.nodes.map((n, i) => ({ id: firstId + i, ...n }));
  const byLabel = new Map(nodes.map((n) => [n.label, n.id]));
  return {
    nodes,
    edges: p.edges.map(([s, t]) => ({ source: byLabel.get(s)!, target: byLabel.get(t)! })),
    seeds: p.settings.seeds.map((l) => byLabel.get(l)!),
  };
}

const fmt = (x: number) => (x === 0 ? "0" : Math.abs(x) < 1e-4 ? x.toExponential(2) : x.toFixed(4));

export function Playground() {
  usePageTitle("Playground");
  const initial = useMemo(() => fromPreset(PRESETS[0], 1), []);
  const nextId = useRef(initial.nodes.length + 1);
  const [nodes, setNodes] = useState<PgNode[]>(initial.nodes);
  const [edges, setEdges] = useState<PgEdge[]>(initial.edges);
  const [seeds, setSeeds] = useState<number[]>(initial.seeds);
  const [algorithm, setAlgorithm] = useState<PlaygroundAlgorithm>(PRESETS[0].settings.algorithm);
  const [alpha, setAlpha] = useState(PRESETS[0].settings.alpha);
  const [dangling, setDangling] = useState<Dangling>(PRESETS[0].settings.dangling);
  const [teleport, setTeleport] = useState<"uniform" | "seeds">(PRESETS[0].settings.teleport);
  const [mode, setMode] = useState<"link" | "move">("link");
  const [preset, setPreset] = useState<Preset | null>(PRESETS[0]);
  const [computed, setComputed] = useState<Computed | null>(null);
  const [running, setRunning] = useState(false);
  const [resetToken, setResetToken] = useState(0);
  const [hover, setHover] = useState<{ id: number; x: number; y: number } | null>(null);
  const [linkFrom, setLinkFrom] = useState("");
  const [linkTo, setLinkTo] = useState("");
  const runRef = useRef<PageRankRun | HitsRun | null>(null);
  const runKey = useRef("");
  const cyRef = useRef<Core | null>(null);
  const ehRef = useRef<EdgeHandles | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const fitPending = useRef(true);
  const themeVersion = useThemeVersion();

  const index = useMemo(() => new Map(nodes.map((n, i) => [n.id, i])), [nodes]);
  const labelOf = useCallback((id: number) => nodes.find((n) => n.id === id)?.label ?? "?", [nodes]);
  const structureKey = `${nodes.map((n) => n.id).join(",")}|${edges.map((e) => `${e.source}>${e.target}`).join(",")}`;
  const graph: Graph = useMemo(
    () => ({ n: nodes.length, edges: edges.map((e) => [index.get(e.source)!, index.get(e.target)!] as [number, number]) }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [structureKey],
  );
  // A string key, so dragging a node (a new `nodes` array with the same structure) does not restart the run.
  const seedKey = seeds
    .map((s) => index.get(s))
    .filter((i): i is number => i !== undefined)
    .sort((a, b) => a - b)
    .join(",");
  const seedIdx = useMemo(() => (seedKey ? seedKey.split(",").map(Number) : []), [seedKey]);
  const seeded = algorithm === "pagerank" && teleport === "seeds" && seedIdx.length > 0;
  const nodesRef = useRef(nodes);
  nodesRef.current = nodes;

  // (Re)start the computation whenever the graph or a parameter changes.
  useEffect(() => {
    setRunning(false);
    runKey.current = structureKey;
    if (graph.n === 0) {
      runRef.current = null;
      setComputed(null);
      return;
    }
    if (algorithm === "pagerank") {
      const run = new PageRankRun(graph, {
        alpha,
        tol: TOL,
        maxIter: PR_MAX_ITER,
        dangling,
        seeds: teleport === "seeds" ? seedIdx : null,
      });
      runRef.current = run;
      setComputed({ key: structureKey, view: { kind: "pagerank", state: run.current } });
    } else if (algorithm === "hits") {
      const run = new HitsRun(graph, TOL, HITS_MAX_ITER);
      runRef.current = run;
      setComputed({ key: structureKey, view: { kind: "hits", state: run.current } });
    } else {
      runRef.current = null;
      setComputed({ key: structureKey, view: { kind: "harmonic", scores: harmonicCentrality(graph) } });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, algorithm, alpha, dangling, teleport, seedIdx, resetToken]);

  const publish = useCallback(() => {
    const run = runRef.current;
    if (!run) return;
    const key = runKey.current;
    if (run instanceof PageRankRun) setComputed({ key, view: { kind: "pagerank", state: run.current } });
    else setComputed({ key, view: { kind: "hits", state: run.current } });
  }, []);

  const step = useCallback(() => {
    runRef.current?.step();
    publish();
  }, [publish]);

  // In the render right after an edit, the previous result still belongs to the old graph;
  // show nothing until the effect above has recomputed for the new one.
  const view: View | null = computed && computed.key === structureKey ? computed.view : null;

  // "Run to convergence" animates at about RUN_RATE iterations per second. It is time-based rather
  // than one iteration per animation frame, so throttled frames (background or embedded views)
  // make it catch up instead of crawling.
  useEffect(() => {
    if (!running) return;
    let last = performance.now();
    let budget = 1;
    let timer = 0;
    const tick = () => {
      const run = runRef.current;
      if (!run) return setRunning(false);
      const now = performance.now();
      budget += ((now - last) / 1000) * RUN_RATE;
      last = now;
      const steps = Math.min(MAX_STEPS_PER_TICK, Math.floor(budget));
      budget -= steps;
      for (let i = 0; i < steps && !run.current.done; i++) run.step();
      if (steps > 0) publish();
      if (run.current.done) setRunning(false);
      else timer = window.setTimeout(tick, 20);
    };
    timer = window.setTimeout(tick, 0);
    return () => window.clearTimeout(timer);
  }, [running, publish]);

  const done = view?.kind === "pagerank" || view?.kind === "hits" ? view.state.done : true;

  // ---- graph editing ------------------------------------------------------------------
  const addNodeAt = useCallback((x: number, y: number) => {
    const id = nextId.current++;
    setNodes((ns) => [...ns, { id, label: nextLabel(ns), x, y }]);
    setPreset(null);
  }, []);

  const addEdge = useCallback((source: number, target: number) => {
    if (source === target) return;
    const exists = (id: number) => nodesRef.current.some((n) => n.id === id);
    if (!exists(source) || !exists(target)) return; // e.g. a stale choice in the "Add link" form
    setEdges((es) => (es.some((e) => e.source === source && e.target === target) ? es : [...es, { source, target }]));
    setPreset(null);
  }, []);

  const removeEdge = useCallback((source: number, target: number) => {
    setEdges((es) => es.filter((e) => !(e.source === source && e.target === target)));
    setPreset(null);
  }, []);

  const removeNode = useCallback((id: number) => {
    setNodes((ns) => ns.filter((n) => n.id !== id));
    setEdges((es) => es.filter((e) => e.source !== id && e.target !== id));
    setSeeds((ss) => ss.filter((s) => s !== id));
    setPreset(null);
  }, []);

  // Clear "Add link" choices that point at nodes which no longer exist.
  useEffect(() => {
    const ids = new Set(nodes.map((n) => String(n.id)));
    if (linkFrom && !ids.has(linkFrom)) setLinkFrom("");
    if (linkTo && !ids.has(linkTo)) setLinkTo("");
  }, [nodes, linkFrom, linkTo]);

  const toggleSeed = useCallback((id: number) => {
    setSeeds((ss) => (ss.includes(id) ? ss.filter((s) => s !== id) : [...ss, id]));
  }, []);

  const loadPreset = (p: Preset) => {
    const g = fromPreset(p, nextId.current);
    nextId.current += g.nodes.length;
    setNodes(g.nodes);
    setEdges(g.edges);
    setSeeds(g.seeds);
    setAlgorithm(p.settings.algorithm);
    setAlpha(p.settings.alpha);
    setDangling(p.settings.dangling);
    setTeleport(p.settings.teleport);
    setPreset(p);
    fitPending.current = true;
  };

  const clearGraph = () => {
    setNodes([]);
    setEdges([]);
    setSeeds([]);
    setPreset(null);
  };

  const addNodeButton = () => {
    const cy = cyRef.current;
    const ext = cy ? cy.extent() : { x1: 0, y1: 0, x2: 600, y2: 450 };
    const pad = 40;
    addNodeAt(
      ext.x1 + pad + Math.random() * Math.max(1, ext.x2 - ext.x1 - 2 * pad),
      ext.y1 + pad + Math.random() * Math.max(1, ext.y2 - ext.y1 - 2 * pad),
    );
  };

  // Latest handlers for Cytoscape callbacks, which are registered once.
  const handlers = useRef({ addNodeAt, addEdge, removeEdge, nodeTap: (_id: number) => {}, moveNode: (_id: number, _x: number, _y: number) => {} });
  handlers.current = {
    addNodeAt,
    addEdge,
    removeEdge,
    nodeTap: (id) => {
      if (algorithm === "pagerank" && teleport === "seeds") toggleSeed(id);
    },
    moveNode: (id, x, y) => setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, x, y } : n))),
  };

  // ---- Cytoscape ------------------------------------------------------------------------
  useEffect(() => {
    registerEdgehandles();
    const cy = cytoscape({
      container: canvasRef.current,
      elements: [],
      layout: { name: "preset" },
      minZoom: 0.4,
      maxZoom: 1.6,
      userZoomingEnabled: false,
      boxSelectionEnabled: false,
      autounselectify: true,
    });
    const eh = (cy as unknown as { edgehandles: (o: object) => EdgeHandles }).edgehandles({
      canConnect: (s: NodeSingular, t: NodeSingular) => !s.same(t) && s.edgesTo(t).empty(),
      edgeParams: () => ({}),
      hoverDelay: 50,
      snap: true,
      snapThreshold: 30,
      noEdgeEventsInDraw: true,
      disableBrowserGestures: true,
    });
    cy.on("ehcomplete", (_e, source: NodeSingular, target: NodeSingular, added: cytoscape.EdgeSingular) => {
      added.remove();
      handlers.current.addEdge(Number(source.id()), Number(target.id()));
    });
    cy.on("tap", (e) => {
      if (e.target === cy) handlers.current.addNodeAt(e.position.x, e.position.y);
    });
    cy.on("tap", "edge", (e) => {
      handlers.current.removeEdge(Number(e.target.data("source")), Number(e.target.data("target")));
    });
    cy.on("tap", "node", (e) => handlers.current.nodeTap(Number(e.target.id())));
    cy.on("dragfree", "node", (e) => {
      const p = e.target.position();
      handlers.current.moveNode(Number(e.target.id()), p.x, p.y);
    });
    cy.on("mouseover", "node", (e) => setHover({ id: Number(e.target.id()), x: e.renderedPosition.x, y: e.renderedPosition.y }));
    cy.on("mouseout", "node", () => setHover(null));
    // Drawing a link suppresses node mouseout, so clear the hover card on these too.
    cy.on("ehstart ehstop ehcomplete tapstart", () => setHover(null));
    cy.on("mousemove", (e) => {
      if (e.target === cy) setHover(null);
    });
    cy.on("mouseover", "edge", (e) => e.target.addClass("hovered"));
    cy.on("mouseout", "edge", (e) => e.target.removeClass("hovered"));
    cyRef.current = cy;
    ehRef.current = eh;
    return () => {
      eh.destroy();
      cy.destroy();
      cyRef.current = null;
      ehRef.current = null;
    };
  }, []);

  useEffect(() => {
    const eh = ehRef.current;
    if (!eh) return;
    if (mode === "link") eh.enableDrawMode();
    else eh.disableDrawMode();
  }, [mode]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const c = {
      node: cssVar("--node"),
      seed: cssVar("--node-seed"),
      edge: cssVar("--edge"),
      text: cssVar("--text"),
      bg: cssVar("--surface"),
      danger: cssVar("--danger"),
      accent: cssVar("--accent"),
    };
    cy.style([
      {
        selector: "node",
        style: {
          "background-color": c.node,
          width: "data(size)",
          height: "data(size)",
          label: "data(label)",
          "text-wrap": "wrap",
          "text-valign": "bottom",
          "text-halign": "center",
          "text-margin-y": 4,
          color: c.text,
          "font-size": 13,
          "font-weight": 600,
          "text-background-color": c.bg,
          "text-background-opacity": 0.8,
          "text-background-padding": "2px",
          "border-width": 2,
          "border-color": c.bg,
        },
      },
      { selector: "node.seed", style: { "border-width": 5, "border-color": c.seed } },
      {
        selector: "edge",
        style: {
          width: 2.5,
          "line-color": c.edge,
          "target-arrow-color": c.edge,
          "target-arrow-shape": "triangle",
          "arrow-scale": 1.3,
          "curve-style": "bezier",
          "overlay-padding": 6,
        },
      },
      { selector: "edge.hovered", style: { "line-color": c.danger, "target-arrow-color": c.danger, width: 4 } },
      { selector: ".eh-handle", style: { "background-color": c.accent, width: 12, height: 12, label: "" } },
      { selector: ".eh-hover", style: { "background-color": c.accent } },
      { selector: ".eh-source", style: { "border-width": 4, "border-color": c.accent } },
      { selector: ".eh-target", style: { "border-width": 4, "border-color": c.accent } },
      {
        selector: ".eh-preview, .eh-ghost-edge",
        style: { "line-color": c.accent, "target-arrow-color": c.accent, "source-arrow-color": c.accent },
      },
      { selector: ".eh-ghost-edge.eh-preview-active", style: { opacity: 0 } },
    ]);
  }, [themeVersion]);

  const displayScores: Float64Array | null =
    view?.kind === "pagerank" ? view.state.scores : view?.kind === "hits" ? view.state.authorities : view?.kind === "harmonic" ? view.scores : null;

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const max = displayScores ? Math.max(...displayScores, 0) : 0;
    cy.batch(() => {
      const wantNodes = new Set(nodes.map((n) => String(n.id)));
      const wantEdges = new Set(edges.map((e) => `e${e.source}-${e.target}`));
      cy.edges().forEach((e) => {
        if (!wantEdges.has(e.id())) e.remove();
      });
      cy.nodes().forEach((n) => {
        if (!wantNodes.has(n.id())) n.remove();
      });
      nodes.forEach((n, i) => {
        const score = displayScores ? displayScores[i] : 0;
        const size = 26 + (max > 0 ? 54 * Math.sqrt(score / max) : 0);
        const data = { id: String(n.id), label: `${n.label}\n${fmt(score)}`, size };
        const el = cy.getElementById(String(n.id));
        if (el.empty()) cy.add({ group: "nodes", data, position: { x: n.x, y: n.y } });
        else el.data(data);
        cy.getElementById(String(n.id)).toggleClass("seed", algorithm === "pagerank" && teleport === "seeds" && seeds.includes(n.id));
      });
      edges.forEach((e) => {
        const id = `e${e.source}-${e.target}`;
        if (cy.getElementById(id).empty()) cy.add({ group: "edges", data: { id, source: String(e.source), target: String(e.target) } });
      });
    });
    if (fitPending.current && nodes.length) {
      cy.fit(undefined, 50);
      fitPending.current = false;
    }
  }, [nodes, edges, displayScores, seeds, teleport, algorithm]);

  // ---- derived display -------------------------------------------------------------------
  const iterations = view?.kind === "pagerank" || view?.kind === "hits" ? view.state.iteration : 0;
  const residuals = view?.kind === "pagerank" || view?.kind === "hits" ? view.state.residuals : NO_RESIDUALS;
  const converged = view?.kind === "pagerank" || view?.kind === "hits" ? view.state.converged : true;
  const maxIter = algorithm === "hits" ? HITS_MAX_ITER : PR_MAX_ITER;

  const teleportText = seeded ? `seeds ${seedIdx.map((i) => nodes[i].label).join(", ")}` : "uniform";
  const prProvenance: Provenance = {
    algorithm: seeded ? "Personalized PageRank" : "PageRank",
    params: `α = ${alpha.toFixed(2)} · dangling = ${DANGLING_LABELS[dangling].name} · teleport = ${teleportText} · tol = 1e-8 · max ${PR_MAX_ITER} iterations · after ${iterations} iteration${iterations === 1 ? "" : "s"}`,
    data: PLAYGROUND_DATA,
  };
  const hitsProvenance = (which: "authority" | "hub"): Provenance => ({
    algorithm: `HITS ${which} score (L2-normalised)`,
    params: `a = Aᵀh, h = Aa · tol = 1e-8 · max ${HITS_MAX_ITER} iterations · after ${iterations} iteration${iterations === 1 ? "" : "s"}`,
    data: PLAYGROUND_DATA,
  });
  const harmonicProvenance: Provenance = {
    algorithm: "Harmonic centrality (exact)",
    params: "H(x) = Σ 1/d(y, x) over every other node y, one breadth-first search per node",
    data: PLAYGROUND_DATA,
  };
  const residualProvenance: Provenance = {
    algorithm: `L1 residual of ${algorithm === "hits" ? "HITS" : prProvenance.algorithm}`,
    params:
      algorithm === "hits"
        ? "‖a_k − a_(k−1)‖₁ + ‖h_k − h_(k−1)‖₁; the run stops when it falls below 1e-8"
        : "‖p_k − p_(k−1)‖₁; the run stops when it falls below 1e-8",
    data: PLAYGROUND_DATA,
  };

  const rows = nodes
    .map((n, i) => ({
      node: n,
      main: displayScores ? displayScores[i] : 0,
      hub: view?.kind === "hits" ? view.state.hubs[i] : 0,
    }))
    .sort((a, b) => b.main - a.main || a.node.label.localeCompare(b.node.label));

  const chartData = useMemo<uPlot.AlignedData>(() => {
    const xs = residuals.map((_, i) => i + 1);
    return [xs, residuals.map((r) => (r > 0 ? r : null)), xs.map(() => TOL)];
  }, [residuals]);

  const hovered = hover ? nodes.find((n) => n.id === hover.id) : undefined;
  const hoveredIndex = hovered ? index.get(hovered.id)! : -1;

  const submitLink = (e: FormEvent) => {
    e.preventDefault();
    if (linkFrom && linkTo && linkFrom !== linkTo) addEdge(Number(linkFrom), Number(linkTo));
  };

  const prPhase =
    view?.kind === "pagerank" && dangling === "remove_readd"
      ? view.state.phase === "core"
        ? `ranking the core of ${view.state.coreSize} nodes (${view.state.strippingRounds} stripping round${view.state.strippingRounds === 1 ? "" : "s"})`
        : `re-adding stripped nodes: ${view.state.strippingRounds} extra iteration${view.state.strippingRounds === 1 ? "" : "s"}`
      : null;

  return (
    <>
      <h1>Playground</h1>
      <p className="lede">
        Build a small link graph and watch the algorithms work one iteration at a time. Everything runs in your browser.
      </p>

      <section aria-labelledby="presets-heading">
        <h2 id="presets-heading" className="visually-hidden">
          Presets
        </h2>
        <div className="preset-list" role="group" aria-label="Load a preset graph">
          {PRESETS.map((p) => (
            <button key={p.id} type="button" onClick={() => loadPreset(p)} aria-pressed={preset?.id === p.id}>
              {p.name}
            </button>
          ))}
        </div>
        {preset && (
          <p className="note" aria-live="polite">
            <strong>{preset.name}.</strong> {preset.explanation}
          </p>
        )}
      </section>

      <div className="pg-layout">
        <div>
          <div className="pg-toolbar">
            <div className="segmented" role="group" aria-label="Canvas mode">
              <button type="button" aria-pressed={mode === "link"} onClick={() => setMode("link")}>
                Draw links
              </button>
              <button type="button" aria-pressed={mode === "move"} onClick={() => setMode("move")}>
                Move nodes
              </button>
            </div>
            <button type="button" onClick={addNodeButton}>
              Add node
            </button>
            <button type="button" onClick={() => cyRef.current?.fit(undefined, 50)}>
              Fit to view
            </button>
            <button type="button" onClick={clearGraph}>
              Clear graph
            </button>
          </div>
          <div className="pg-canvas" onMouseLeave={() => setHover(null)}>
            <div
              ref={canvasRef}
              style={{ position: "absolute", inset: 0 }}
              role="application"
              aria-label="Graph canvas. Click empty space to add a node, drag from one node to another to add a link, click a link to delete it. The node and link lists below offer the same actions by keyboard."
            />
            {hovered && displayScores && (
              <div
                className="pg-hover"
                style={{
                  left: Math.max(4, Math.min(hover!.x + 16, (canvasRef.current?.clientWidth ?? 600) - 310)),
                  top: Math.max(4, Math.min(hover!.y + 16, (canvasRef.current?.clientHeight ?? 520) - 120)),
                }}
                aria-hidden="true"
              >
                <strong>{hovered.label}</strong>:{" "}
                {view?.kind === "hits"
                  ? `authority ${fmt(view.state.authorities[hoveredIndex])}, hub ${fmt(view.state.hubs[hoveredIndex])}`
                  : fmt(displayScores[hoveredIndex])}
                <br />
                {view?.kind === "pagerank" && `${prProvenance.algorithm} · ${prProvenance.params}`}
                {view?.kind === "hits" && hitsProvenance("authority").params}
                {view?.kind === "harmonic" && harmonicProvenance.params}
                <br />
                <span style={{ opacity: 0.8 }}>{PLAYGROUND_DATA}</span>
              </div>
            )}
            <div className="pg-canvas-hint">
              {mode === "link" ? "Drag node to node to link" : "Drag nodes to move them"} · click empty space to add a node · click a
              link to delete it
              {algorithm === "pagerank" && teleport === "seeds" ? " · click a node to toggle it as a seed" : ""}
            </div>
          </div>

          <section aria-labelledby="residual-heading" className="card" style={{ marginTop: 16 }}>
            <h2 id="residual-heading" style={{ marginTop: 0, fontSize: "1.1rem" }}>
              Residual per iteration
            </h2>
            {view?.kind === "harmonic" ? (
              <p className="muted">Harmonic centrality is computed exactly by breadth-first search, so there are no iterations.</p>
            ) : residuals.length === 0 ? (
              <p className="muted">Press Step or Run to convergence to see how far each iteration moves the scores.</p>
            ) : (
              <UPlotChart
                optionsKey={algorithm}
                data={chartData}
                height={220}
                ariaLabel={`Line chart of the L1 residual after each of ${residuals.length} iterations on a logarithmic scale, with the stopping tolerance 1e-8 as a dashed line.`}
                options={(c, width, height) => ({
                  width,
                  height,
                  scales: { x: { time: false }, y: { distr: 3 } },
                  axes: [
                    { label: "Iteration", stroke: c.text, grid: { stroke: c.border, width: 1 }, ticks: { stroke: c.border } },
                    {
                      label: "L1 residual (log)",
                      stroke: c.text,
                      grid: { stroke: c.border, width: 1 },
                      ticks: { stroke: c.border },
                      size: 70,
                      values: (_u, splits) => splits.map((v) => (v == null ? "" : v.toExponential(0))),
                    },
                  ],
                  series: [
                    { label: "Iteration" },
                    { label: "Residual", stroke: c.series1, width: 2, points: { show: true, size: 4 } },
                    { label: "Tolerance 1e-8", stroke: c.series2, width: 1.5, dash: [6, 4], points: { show: false } },
                  ],
                })}
              />
            )}
            <p className="small muted" style={{ marginBottom: 0 }}>
              {algorithm === "hits" ? "HITS" : prProvenance.algorithm}
              {algorithm === "pagerank" ? `, α = ${alpha.toFixed(2)}, dangling = ${DANGLING_LABELS[dangling].name}, teleport = ${teleportText}` : ""}
              . {PLAYGROUND_DATA}.
            </p>
          </section>
        </div>

        <div className="pg-controls">
          <fieldset>
            <legend>Algorithm</legend>
            <select aria-label="Algorithm" value={algorithm} onChange={(e) => setAlgorithm(e.target.value as PlaygroundAlgorithm)}>
              {(Object.keys(ALGORITHM_LABELS) as PlaygroundAlgorithm[]).map((a) => (
                <option key={a} value={a}>
                  {ALGORITHM_LABELS[a]}
                </option>
              ))}
            </select>
            {algorithm !== "pagerank" && (
              <p className="small muted" style={{ margin: "8px 0 0" }}>
                {algorithm === "hits"
                  ? "HITS has no damping factor, teleport or dangling handling; node size shows the authority score."
                  : "Harmonic centrality has no parameters; node size shows the score."}
              </p>
            )}
          </fieldset>

          <fieldset disabled={algorithm !== "pagerank"}>
            <legend>PageRank parameters</legend>
            <label htmlFor="alpha">
              Damping factor α = <b>{alpha.toFixed(2)}</b>
            </label>
            <input
              id="alpha"
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={alpha}
              aria-valuetext={`alpha ${alpha.toFixed(2)}`}
              onChange={(e) => setAlpha(Number(e.target.value))}
            />
            <p className="small muted" style={{ margin: "0 0 10px" }}>
              Probability of following a link; 1 − α is the probability of teleporting.
            </p>
            <label htmlFor="dangling">Dangling nodes</label>
            <select id="dangling" value={dangling} onChange={(e) => setDangling(e.target.value as Dangling)} style={{ width: "100%" }}>
              {DANGLING_STRATEGIES.map((d) => (
                <option key={d} value={d}>
                  {DANGLING_LABELS[d].name}
                </option>
              ))}
            </select>
            <p className="small muted" style={{ margin: "4px 0 10px" }}>
              {DANGLING_LABELS[dangling].help}
            </p>
            <div role="radiogroup" aria-labelledby="teleport-label">
              <div id="teleport-label" style={{ fontWeight: 500 }}>
                Teleport
              </div>
              <label className="radio-row">
                <input type="radio" name="teleport" checked={teleport === "uniform"} onChange={() => setTeleport("uniform")} />
                Uniform over all nodes
              </label>
              <label className="radio-row">
                <input type="radio" name="teleport" checked={teleport === "seeds"} onChange={() => setTeleport("seeds")} />
                Chosen seed nodes (personalized PageRank)
              </label>
            </div>
            {teleport === "seeds" && algorithm === "pagerank" && (
              <p className={seedIdx.length ? "small muted" : "small warn"} style={{ margin: "6px 0 0" }}>
                {seedIdx.length
                  ? `Seeds: ${seedIdx.map((i) => nodes[i].label).join(", ")}. Click nodes or use the checkboxes below to change them.`
                  : "No seeds chosen yet, so teleport is uniform. Click nodes or tick them in the score list."}
              </p>
            )}
          </fieldset>

          <fieldset>
            <legend>Run</legend>
            <div className="row">
              <button type="button" onClick={step} disabled={algorithm === "harmonic" || done || running || !view}>
                Step
              </button>
              {running ? (
                <button type="button" className="primary" onClick={() => setRunning(false)}>
                  Stop
                </button>
              ) : (
                <button type="button" className="primary" onClick={() => setRunning(true)} disabled={algorithm === "harmonic" || done || !view}>
                  Run to convergence
                </button>
              )}
              <button type="button" onClick={() => setResetToken((t) => t + 1)} disabled={algorithm === "harmonic" || !view}>
                Reset
              </button>
            </div>
            {algorithm !== "harmonic" && view && (
              <p className="status-line" aria-live="polite" style={{ margin: "10px 0 0" }}>
                Iteration <b>{iterations}</b> of at most {maxIter}
                {residuals.length > 0 && (
                  <>
                    {" "}
                    · residual{" "}
                    <b>
                      <Num p={residualProvenance}>{residuals[residuals.length - 1].toExponential(2)}</Num>
                    </b>
                  </>
                )}
                <br />
                {iterations === 0
                  ? "Scores start uniform."
                  : prPhase
                    ? converged
                      ? "The core converged (residual below 1e-8)."
                      : done
                        ? "The core stopped at the iteration limit without converging."
                        : "The core has not converged yet."
                    : converged
                      ? "Converged: residual below 1e-8."
                      : done
                        ? "Stopped at the iteration limit without converging."
                        : "Not converged yet."}
                {prPhase && (
                  <>
                    <br />
                    Remove &amp; re-add: {prPhase}.
                    {done && view?.kind === "pagerank" && view.state.strippingRounds > 0 && (
                      <> The re-add iterations are a fixed count, so their residual is not a convergence test.</>
                    )}
                  </>
                )}
              </p>
            )}
          </fieldset>

          <fieldset>
            <legend>Scores, highest first</legend>
            {nodes.length === 0 ? (
              <p className="muted small">The graph is empty. Click the canvas or press Add node.</p>
            ) : (
              <div className="scores-list">
                <table>
                  <thead>
                    <tr>
                      <th>Node</th>
                      {view?.kind === "hits" ? (
                        <>
                          <th className="r">Authority</th>
                          <th className="r">Hub</th>
                        </>
                      ) : (
                        <th className="r">{view?.kind === "harmonic" ? "Harmonic" : prProvenance.algorithm}</th>
                      )}
                      {algorithm === "pagerank" && teleport === "seeds" && <th>Seed</th>}
                      <th>
                        <span className="visually-hidden">Remove</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map(({ node, main, hub }) => (
                      <tr key={node.id}>
                        <td>
                          {node.label}
                          {algorithm === "pagerank" && teleport === "seeds" && seeds.includes(node.id) && (
                            <span className="seed-dot" title="Seed" />
                          )}
                        </td>
                        {view?.kind === "hits" ? (
                          <>
                            <td className="r">
                              <Num p={hitsProvenance("authority")}>{fmt(main)}</Num>
                            </td>
                            <td className="r">
                              <Num p={hitsProvenance("hub")}>{fmt(hub)}</Num>
                            </td>
                          </>
                        ) : (
                          <td className="r">
                            <Num p={view?.kind === "harmonic" ? harmonicProvenance : prProvenance}>{fmt(main)}</Num>
                          </td>
                        )}
                        {algorithm === "pagerank" && teleport === "seeds" && (
                          <td>
                            <input
                              type="checkbox"
                              aria-label={`Use ${node.label} as a seed`}
                              checked={seeds.includes(node.id)}
                              onChange={() => toggleSeed(node.id)}
                            />
                          </td>
                        )}
                        <td>
                          <button type="button" className="icon-button" aria-label={`Remove node ${node.label}`} onClick={() => removeNode(node.id)}>
                            Remove
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </fieldset>

          <fieldset>
            <legend>Links ({edges.length})</legend>
            <form className="row" onSubmit={submitLink}>
              <label className="visually-hidden" htmlFor="link-from">
                Link from
              </label>
              <select id="link-from" value={linkFrom} onChange={(e) => setLinkFrom(e.target.value)}>
                <option value="">From…</option>
                {nodes.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.label}
                  </option>
                ))}
              </select>
              <span aria-hidden="true">→</span>
              <label className="visually-hidden" htmlFor="link-to">
                Link to
              </label>
              <select id="link-to" value={linkTo} onChange={(e) => setLinkTo(e.target.value)}>
                <option value="">To…</option>
                {nodes.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.label}
                  </option>
                ))}
              </select>
              <button
                type="submit"
                disabled={
                  !linkFrom ||
                  !linkTo ||
                  linkFrom === linkTo ||
                  edges.some((e) => e.source === Number(linkFrom) && e.target === Number(linkTo))
                }
              >
                Add link
              </button>
            </form>
            <ul style={{ listStyle: "none", padding: 0, margin: "8px 0 0", maxHeight: 200, overflowY: "auto" }}>
              {edges.map((e) => (
                <li key={`${e.source}-${e.target}`} className="row" style={{ justifyContent: "space-between", padding: "2px 0" }}>
                  <span>
                    {labelOf(e.source)} → {labelOf(e.target)}
                  </span>
                  <button
                    type="button"
                    className="icon-button"
                    aria-label={`Delete link ${labelOf(e.source)} to ${labelOf(e.target)}`}
                    onClick={() => removeEdge(e.source, e.target)}
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          </fieldset>
        </div>
      </div>
    </>
  );
}
