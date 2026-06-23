import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import type { DashboardSpark } from "@/lib/types";

interface Props {
  points: DashboardSpark[];
  lower?: number | null;
  upper?: number | null;
  height?: number;
  color?: string;
}

/**
 * 24h mini temperature chart. Null values render as visible gaps
 * (connectNulls=false). Threshold lines are drawn when configured.
 */
export function TemperatureSparkline({
  points,
  lower,
  upper,
  height = 56,
  color = "#38bdf8",
}: Props) {
  const option = useMemo(() => {
    const data = points.map((p) => [new Date(p.t).getTime(), p.v]);
    const markLines: Array<Record<string, unknown>> = [];
    if (upper != null)
      markLines.push({ yAxis: upper, lineStyle: { color: "#f87171", type: "dashed", width: 1 } });
    if (lower != null)
      markLines.push({ yAxis: lower, lineStyle: { color: "#60a5fa", type: "dashed", width: 1 } });

    return {
      grid: { left: 2, right: 2, top: 6, bottom: 2 },
      xAxis: { type: "time", show: false },
      yAxis: { type: "value", show: false, scale: true },
      tooltip: { show: false },
      animation: false,
      series: [
        {
          type: "line",
          data,
          showSymbol: false,
          connectNulls: false,
          smooth: false,
          lineStyle: { width: 1.75, color },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: color + "44" },
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
  }, [points, lower, upper, color]);

  return (
    <ReactECharts
      option={option}
      style={{ height, width: "100%" }}
      opts={{ renderer: "svg" }}
      notMerge
    />
  );
}
