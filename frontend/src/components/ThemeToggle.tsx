import { useState } from "react";
import { applyTheme, loadTheme, type ThemeChoice } from "../theme";

const NEXT: Record<ThemeChoice, ThemeChoice> = { system: "light", light: "dark", dark: "system" };
const LABEL: Record<ThemeChoice, string> = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" };

export function ThemeToggle() {
  const [choice, setChoice] = useState<ThemeChoice>(loadTheme);
  return (
    <button
      type="button"
      className="theme-toggle icon-button"
      aria-label={`${LABEL[choice]}. Switch to ${NEXT[choice]}.`}
      onClick={() => {
        const next = NEXT[choice];
        applyTheme(next);
        setChoice(next);
      }}
    >
      {LABEL[choice]}
    </button>
  );
}
