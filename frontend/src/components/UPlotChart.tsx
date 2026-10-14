import { useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { cssVar, useThemeVersion } from "../theme";

export interface ChartColors {
  text: string;
  muted: string;
  border: string;
  series1: string;
  series2: string;
  series3: string;
}

function readColors(): ChartColors {
  return {
    text: cssVar("--text"),
    muted: cssVar("--text-muted"),
    border: cssVar("--border"),
    series1: cssVar("--series-1"),
    series2: cssVar("--series-2"),
    series3: cssVar("--series-3"),
  };
}

/**
 * uPlot wrapper. The chart is rebuilt when `optionsKey` or the colour theme changes and
 * receives new data via setData otherwise. Width follows the container.
 */
export function UPlotChart({
  options,
  optionsKey,
  data,
  height = 240,
  ariaLabel,
}: {
  options: (colors: ChartColors, width: number, height: number) => uPlot.Options;
  optionsKey: string;
  data: uPlot.AlignedData;
  height?: number;
  ariaLabel: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const plot = useRef<uPlot | null>(null);
  const latestData = useRef(data);
  const latestOptions = useRef(options);
  latestData.current = data;
  latestOptions.current = options;
  const themeVersion = useThemeVersion();

  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const width = Math.max(200, el.clientWidth);
    const u = new uPlot(latestOptions.current(readColors(), width, height), latestData.current, el);
    plot.current = u;
    const ro = new ResizeObserver(() => {
      const w = Math.max(200, el.clientWidth);
      if (Math.abs(w - u.width) > 1) u.setSize({ width: w, height });
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      u.destroy();
      plot.current = null;
    };
  }, [optionsKey, themeVersion, height]);

  useEffect(() => {
    plot.current?.setData(data);
  }, [data]);

  return <div ref={container} className="chart" role="img" aria-label={ariaLabel} />;
}
