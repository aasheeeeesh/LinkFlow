import type { HistoryPoint } from "../api";

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];

/** "cc-main-2026-apr-may-jun" -> "Apr–Jun 2026"; "cc-main-2025-26-dec-jan-feb" -> "Dec 2025–Feb 2026". */
export function shortRelease(release: string): string {
  const m = /^cc-main-(\d{4})(?:-(\d{2}))?-([a-z]{3})-[a-z]{3}-([a-z]{3})$/.exec(release);
  if (!m || !MONTHS.includes(m[3]) || !MONTHS.includes(m[4])) return release;
  const cap = (s: string) => s[0].toUpperCase() + s.slice(1);
  if (m[2]) return `${cap(m[3])} ${m[1]}–${cap(m[4])} ${m[1].slice(0, 2)}${m[2]}`;
  return `${cap(m[3])}–${cap(m[4])} ${m[1]}`;
}

/** uPlot data: x = release index (oldest first), then PageRank rank and harmonic rank (null when absent). */
export function historySeries(points: HistoryPoint[]): [number[], (number | null)[], (number | null)[]] {
  return [points.map((_, i) => i), points.map((p) => p.pr_rank ?? null), points.map((p) => p.hc_rank ?? null)];
}
