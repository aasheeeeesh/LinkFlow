/**
 * Composite score: weighted sum of percentiles with weights rescaled to sum to 1.
 * Mirrors backend/algorithms/scoring.py composite_score.
 */

export interface CompositeInput {
  id: string;
  percentile: number;
  weight: number; // raw, non-negative slider value
}

export interface CompositeRow extends CompositeInput {
  share: number; // weight / sum of weights, 0..1
  contribution: number; // share * percentile
}

export interface CompositeResult {
  /** null when every weight is zero: there is no composite to show. */
  composite: number | null;
  rows: CompositeRow[];
}

export function computeComposite(inputs: CompositeInput[]): CompositeResult {
  if (inputs.some((i) => i.weight < 0 || !Number.isFinite(i.weight))) throw new Error("weights must be non-negative");
  const total = inputs.reduce((t, i) => t + i.weight, 0);
  const rows = inputs.map((i) => {
    const share = total > 0 ? i.weight / total : 0;
    return { ...i, share, contribution: share * i.percentile };
  });
  return { composite: total > 0 ? rows.reduce((t, r) => t + r.contribution, 0) : null, rows };
}
