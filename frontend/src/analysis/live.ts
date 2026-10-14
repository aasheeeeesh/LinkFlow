/** Domains typed by the user, separated by commas, spaces or new lines; duplicates dropped. */
export function splitDomains(text: string): string[] {
  return [...new Set(text.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean))];
}

/** One hypothetical link per line, "source -> target" (or "source target"). Returns links and the lines that did not parse. */
export function parseLinks(text: string): { links: { source: string; target: string }[]; bad: string[] } {
  const links: { source: string; target: string }[] = [];
  const bad: string[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const parts = line.split(/\s*(?:->|→|\s)\s*/).filter(Boolean);
    if (parts.length === 2) links.push({ source: parts[0], target: parts[1] });
    else bad.push(line);
  }
  return { links, bad };
}
