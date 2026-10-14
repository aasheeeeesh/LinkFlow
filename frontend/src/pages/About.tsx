import DOMPurify from "dompurify";
import { Marked, type Tokens } from "marked";
import { useMemo } from "react";
import dataDoc from "../../../docs/DATA.md?raw";
import methodology from "../../../docs/METHODOLOGY.md?raw";
import { Disclosures } from "../components/Disclosures";
import { usePageTitle } from "../usePageTitle";

const slug = (text: string) =>
  text
    .toLowerCase()
    .replace(/<[^>]+>/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");

/** Rendered inline HTML -> plain text, with entities such as &#39; decoded. */
const plainText = (html: string) => new DOMParser().parseFromString(html, "text/html").body.textContent ?? "";

function render(md: string, idPrefix: string): { html: string; toc: { id: string; text: string }[] } {
  const toc: { id: string; text: string }[] = [];
  const marked = new Marked({
    gfm: true,
    renderer: {
      heading(this: { parser: { parseInline: (t: Tokens.Generic[]) => string } }, { tokens, depth, text }: Tokens.Heading) {
        const id = `${idPrefix}-${slug(text)}`;
        const inner = this.parser.parseInline(tokens);
        if (depth === 2) toc.push({ id, text: plainText(inner) });
        return `<h${depth} id="${id}">${inner}</h${depth}>\n`;
      },
    },
  });
  const html = DOMPurify.sanitize(marked.parse(md, { async: false }) as string);
  return { html, toc };
}

export function About() {
  usePageTitle("About & methodology");
  const method = useMemo(() => render(methodology, "m"), []);
  const data = useMemo(() => render(dataDoc, "d"), []);
  return (
    <>
      <h1>About &amp; methodology</h1>
      <p className="lede">
        Linkflow Lab is an open, transparent link-analysis site. It is not Google's PageRank and does not claim to be:
        it runs published algorithms on Common Crawl's public web graph and documents every choice below.
      </p>
      <Disclosures />
      <nav aria-label="Methodology contents" className="card" style={{ marginTop: 16 }}>
        <strong>Contents</strong>
        <ul style={{ columns: "2 260px", margin: "8px 0 0" }}>
          {method.toc.map((t) => (
            <li key={t.id}>
              <a href={`#${t.id}`}>{t.text}</a>
            </li>
          ))}
          <li>
            <a href="#data-documentation">Data documentation</a>
          </li>
        </ul>
      </nav>
      <article className="prose" dangerouslySetInnerHTML={{ __html: method.html }} />
      <hr style={{ margin: "40px 0", border: 0, borderTop: "1px solid var(--border)" }} />
      <article className="prose" id="data-documentation" dangerouslySetInnerHTML={{ __html: data.html }} />
    </>
  );
}
