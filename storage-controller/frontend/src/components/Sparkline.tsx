import ReactECharts from "echarts-for-react";

interface SparklineProps {
  data: number[];
  lower?: number | null;
  upper?: number | null;
  color?: string;
  height?: number;
}

/**
 * Compact temperature sparkline with optional threshold lines. In Phase 1+2 the
 * series is illustrative (no persisted samples yet — that arrives in Phase 3),
 * so callers pass a short synthetic/last-value series.
 */
export function Sparkline({
  data,
  lower,
  upper,
  color = "#38bdf8",
  height = 48,
}: SparklineProps) {
  const markLines: { yAxis: number; lineStyle: { color: string; type: string } }[] = [];
  if (upper != null) markLines.push({ yAxis: upper, lineStyle: { color: "#f87171", type: "dashed" } });
  if (lower != null) markLines.push({ yAxis: lower, lineStyle: { color: "#60a5fa", type: "dashed" } });

  const option = {
    grid: { left: 0, right: 0, top: 4, bottom: 0 },
    xAxis: { type: "category", show: false, boundaryGap: false },
    yAxis: { type: "value", show: false, scale: true },
    tooltip: { show: false },
    animation: false,
    series: [
      {
        type: "line",
        data,
        smooth: true,
        symbol: "none",
        lineStyle: { width: 2, color },
        areaStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: color + "55" },
              { offset: 1, color: color + "00" },
            ],
          },
        },
        markLine: markLines.length
          ? { silent: true, symbol: "none", data: markLines, label: { show: false } }
          : undefined,
      },
    ],
  };

  return (
    <ReactECharts
      option={option}
      style={{ height, width: "100%" }}
      opts={{ renderer: "svg" }}
    />
  );
}
