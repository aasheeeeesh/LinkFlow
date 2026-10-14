const intFmt = new Intl.NumberFormat("en-US");

export const formatInt = (x: number) => intFmt.format(x);

/** Scores spanning many orders of magnitude: scientific below 1e-3, else 4 significant digits. */
export function formatScore(x: number): string {
  if (x === 0) return "0";
  const a = Math.abs(x);
  if (a < 1e-3 || a >= 1e6) return x.toExponential(3);
  return x.toPrecision(4);
}

/**
 * Percentile with enough decimals that values below 100 never round up to "100":
 * rank 38 of 118M is 99.999970, not 100. Only the top score prints as exactly 100.
 */
export function formatPercentile(p: number): string {
  if (p >= 100) return "100";
  const decimals = Math.min(8, Math.max(1, Math.ceil(-Math.log10(100 - p)) + 1));
  return p.toFixed(decimals);
}

export const ordinalRank = (r: number) => `#${formatInt(r)}`;
