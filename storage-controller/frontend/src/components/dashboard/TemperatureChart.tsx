import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import { useTranslation } from "react-i18next";
import type { DefrostCycle, HistoryPoint } from "@/lib/types";

interface Props {
  points: HistoryPoint[];
  lower?: number | null;
  upper?: number | null;
  setpoint?: number | null;
  defrostCycles?: DefrostCycle[];
  height?: number;
}

function isDark() {
  return (
    typeof document !== "undefined" &&
    document.documentElement.classList.contains("dark")
  );
}

/**
 * Large temperature time-series chart. Gaps (null) are not connected, so
 * unavailable/missing periods are visibly empty rather than interpolated.
 * Threshold and setpoint lines use print-safe colors.
 */
export function TemperatureChart({
  points,
  lower,
  upper,
  setpoint,
  defrostCycles = [],
  height = 340,
}: Props) {
  const { t, i18n } = useTranslation("dashboard");

  const option = useMemo(() => {
    const dark = isDark();
    // Defrost (subtle band) and recovery (different subtle band) periods.
    const markAreas: Array<Array<Record<string, unknown>>> = [];
    for (const c of defrostCycles) {
      const start = new Date(c.started_at).getTime();
      const end = c.ended_at ? new Date(c.ended_at).getTime() : Date.now();
      markAreas.push([
        { xAxis: start, itemStyle: { color: "#38bdf820" } },
        { xAxis: end },
      ]);
      if (c.recovery_started_at) {
        const rs = new Date(c.recovery_started_at).getTime();
        const re = c.recovered_at ? new Date(c.recovered_at).getTime() : Date.now();
        markAreas.push([
          { xAxis: rs, itemStyle: { color: "#a78bfa20" } },
          { xAxis: re },
        ]);
      }
    }
    const axis = dark ? "#94a3b8" : "#475569";
    const grid = dark ? "#1e293b" : "#e2e8f0";
    const data = points.map((p) => [new Date(p.t).getTime(), p.v]);

    const marks: Array<Record<string, unknown>> = [];
    if (upper != null)
      marks.push({
        yAxis: upper,
        lineStyle: { color: "#ef4444", type: "dashed", width: 1.25 },
        label: { formatter: `${upper}°`, color: "#ef4444", position: "insideEndTop" },
      });
    if (lower != null)
      marks.push({
        yAxis: lower,
        lineStyle: { color: "#3b82f6", type: "dashed", width: 1.25 },
        label: { formatter: `${lower}°`, color: "#3b82f6", position: "insideEndBottom" },
      });
    if (setpoint != null)
      marks.push({
        yAxis: setpoint,
        lineStyle: { color: "#10b981", type: "dotted", width: 1.25 },
        label: { formatter: `${setpoint}°`, color: "#10b981", position: "insideEndTop" },
      });

    return {
      grid: { left: 44, right: 16, top: 16, bottom: 48 },
      tooltip: {
        trigger: "axis",
        valueFormatter: (v: number | null) =>
          v == null
            ? "—"
            : new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 }).format(v) + " °C",
      },
      xAxis: {
        type: "time",
        axisLine: { lineStyle: { color: grid } },
        axisLabel: { color: axis, hideOverlap: true },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { color: axis, formatter: "{value}°" },
        splitLine: { lineStyle: { color: grid } },
      },
      dataZoom: [
        { type: "inside", throttle: 50 },
        { type: "slider", height: 18, bottom: 8, borderColor: grid },
      ],
      series: [
        {
          name: t("detail.current"),
          type: "line",
          data,
          showSymbol: false,
          connectNulls: false,
          smooth: false,
          sampling: "lttb",
          lineStyle: { width: 1.75, color: "#0ea5e9" },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "#0ea5e933" },
                { offset: 1, color: "#0ea5e900" },
              ],
            },
          },
          markLine: marks.length
            ? { silent: true, symbol: "none", data: marks }
            : undefined,
          markArea: markAreas.length
            ? { silent: true, data: markAreas as never }
            : undefined,
        },
      ],
    };
  }, [points, lower, upper, setpoint, defrostCycles, i18n.language, t]);

  return (
    <ReactECharts
      option={option}
      style={{ height, width: "100%" }}
      opts={{ renderer: "svg" }}
      notMerge
    />
  );
}
