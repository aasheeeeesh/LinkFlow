/** The three disclosures required on the About page and in the domain page footer. */
export function Disclosures({ headingLevel = 2 }: { headingLevel?: 2 | 3 }) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <section aria-labelledby="disclosures-heading" className="card">
      <Heading id="disclosures-heading" style={{ marginTop: 0 }}>
        Read these numbers carefully
      </Heading>
      <ul className="disclosures">
        <li>
          <strong>This is not Google's PageRank.</strong> Linkflow Lab is independent of Google, and Google has not
          published PageRank values since 2016. Nothing here reflects how Google ranks pages.
        </li>
        <li>
          <strong>Scores are domain-level, not page-level.</strong> Every host under a registered domain (for example
          all of <code>*.example.com</code>) is merged into one node, and links between those hosts are not counted.
        </li>
        <li>
          <strong>The graph measures what Common Crawl crawled.</strong> Common Crawl prioritizes crawling by harmonic
          centrality, so domains that are already central are over-represented in the very graph that measures them.
          Treat scores as relative, not absolute.
        </li>
      </ul>
    </section>
  );
}
