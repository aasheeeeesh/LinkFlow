import { useEffect } from "react";

export function usePageTitle(title: string): void {
  useEffect(() => {
    document.title = title ? `${title} · Linkflow Lab` : "Linkflow Lab";
  }, [title]);
}
