import { lazy, Suspense, useEffect, useRef } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { Logo } from "./components/Logo";
import { LoadErrorBoundary } from "./components/LoadErrorBoundary";
import { ThemeToggle } from "./components/ThemeToggle";
import { Compare } from "./pages/Compare";
import { DomainPage } from "./pages/DomainPage";
import { Home } from "./pages/Home";
import { NotFoundPage } from "./pages/NotFoundPage";

// The graph editor (Cytoscape) and the Markdown renderer are only loaded when visited.
const Playground = lazy(() => import("./pages/Playground").then((m) => ({ default: m.Playground })));
const About = lazy(() => import("./pages/About").then((m) => ({ default: m.About })));
const Disagreements = lazy(() => import("./pages/Disagreements").then((m) => ({ default: m.Disagreements })));
const Live = lazy(() => import("./pages/Live").then((m) => ({ default: m.Live })));
const ConvergenceLab = lazy(() => import("./pages/ConvergenceLab").then((m) => ({ default: m.ConvergenceLab })));

export function App() {
  const location = useLocation();
  const main = useRef<HTMLElement>(null);
  const first = useRef(true);

  // Move focus to the new page's content on navigation so keyboard and screen-reader users land there.
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    main.current?.focus();
  }, [location.pathname]);

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <div className="site-header-inner">
          <Link to="/" className="brand" aria-label="Linkflow Lab home">
            <Logo />
            <span>Linkflow Lab</span>
          </Link>
          <nav className="site-nav" aria-label="Main">
            <NavLink to="/" end>
              Lookup
            </NavLink>
            <NavLink to="/compare">Compare</NavLink>
            <NavLink to="/disagreements">Disagreements</NavLink>
            <NavLink to="/convergence">Convergence Lab</NavLink>
            <NavLink to="/live">Live analysis</NavLink>
            <NavLink to="/playground">Playground</NavLink>
            <NavLink to="/about">About &amp; methodology</NavLink>
          </nav>
          <ThemeToggle />
        </div>
      </header>
      <main id="main" ref={main} tabIndex={-1} style={{ outline: "none" }}>
        <LoadErrorBoundary key={location.pathname}>
        <Suspense fallback={<p className="muted">Loading…</p>}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/domain/:domain" element={<DomainPage />} />
            <Route path="/compare" element={<Compare />} />
            <Route path="/disagreements" element={<Disagreements />} />
            <Route path="/convergence" element={<ConvergenceLab />} />
            <Route path="/live" element={<Live />} />
            <Route path="/playground" element={<Playground />} />
            <Route path="/about" element={<About />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </Suspense>
        </LoadErrorBoundary>
      </main>
      <footer className="site-footer">
        <div className="site-footer-inner">
          <p style={{ margin: 0 }}>
            Linkflow Lab is an independent, open link-analysis project built on the{" "}
            <a href="https://commoncrawl.org/web-graphs">Common Crawl web graph</a>. It is not affiliated with Google or
            Common Crawl. <Link to="/about">How every number is computed</Link>.
          </p>
        </div>
      </footer>
    </>
  );
}
