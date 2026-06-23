import { useTranslation } from "react-i18next";
import { RefreshCw, Clock } from "lucide-react";
import type { DashboardResponse } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/layout/StatusPill";
import { formatDateTime, timeAgo } from "@/lib/utils";

export function DashboardHeader({
  data,
  onRefresh,
  refreshing,
}: {
  data: DashboardResponse;
  onRefresh: () => void;
  refreshing?: boolean;
}) {
  const { t } = useTranslation("dashboard");
  const s = data.summary;

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border bg-card/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-muted-foreground">{t("homeAssistant")}</span>
          <StatusPill status={data.connection.status} />
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" aria-hidden />
            {t("header.lastSample")}: {timeAgo(data.last_sample_at)}
          </span>
          <span className="hidden sm:inline" title={formatDateTime(data.generated_at)}>
            {t("header.timezone")}: {data.timezone}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={onRefresh}
            aria-label={t("header.refresh")}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
            <span className="hidden sm:inline">{t("header.refresh")}</span>
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Metric label={t("header.units")} value={s.total} tone="neutral" />
        <Metric label={t("header.normal")} value={s.normal} tone="ok" />
        <Metric
          label={t("header.outsideRange")}
          value={s.outside_range + s.near_limit}
          tone={s.outside_range > 0 ? "danger" : "warn"}
        />
        <Metric
          label={t("header.unavailable")}
          value={s.unavailable + s.disconnected + s.configuration_error + s.stale}
          tone="neutral"
        />
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "ok" | "warn" | "danger" | "neutral";
}) {
  const color =
    tone === "ok"
      ? "text-ok"
      : tone === "warn"
        ? "text-warn"
        : tone === "danger"
          ? "text-danger"
          : "text-foreground";
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`text-2xl font-semibold tabular-nums ${color}`}>{value}</div>
    </div>
  );
}
