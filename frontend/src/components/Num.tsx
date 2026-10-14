import { useId, type ReactNode } from "react";
import type { Provenance } from "../provenance";

/**
 * A displayed number with an accessible tooltip naming its algorithm, parameters and data.
 * The number is focusable so keyboard users can reveal the tooltip too.
 */
export function Num({ children, p, className }: { children: ReactNode; p: Provenance; className?: string }) {
  const id = useId();
  return (
    <span className={`num ${className ?? ""}`} tabIndex={0} aria-describedby={id}>
      {children}
      <span role="tooltip" id={id} className="tip">
        <strong>{p.algorithm}</strong>
        <span>{p.params}</span>
        <span className="tip-data">{p.data}</span>
      </span>
    </span>
  );
}
