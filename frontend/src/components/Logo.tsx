/** Linkflow Lab mark: three nodes with links flowing into the largest one. */
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <defs>
        <marker id="lf-arrow" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="4" markerHeight="4" orient="auto">
          <path d="M0,0 L6,3 L0,6 z" fill="currentColor" />
        </marker>
      </defs>
      <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity="0.65">
        <path d="M8 8 L17.5 15" markerEnd="url(#lf-arrow)" />
        <path d="M8 24 L17.5 18.5" markerEnd="url(#lf-arrow)" />
      </g>
      <circle cx="6.5" cy="7" r="3.5" fill="var(--series-2)" />
      <circle cx="6.5" cy="25" r="3.5" fill="var(--series-3)" />
      <circle cx="23" cy="16.5" r="7" fill="var(--accent)" />
    </svg>
  );
}
