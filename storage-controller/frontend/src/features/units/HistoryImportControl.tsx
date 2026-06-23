import * as React from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, RefreshCw, History, AlertTriangle, CheckCircle2 } from "lucide-react";
import { api } from "@/lib/api";
import type { HistoryRange } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const RANGES: HistoryRange[] = ["last_30_days", "last_90_days", "current_month", "all"];

/** Embedded in the unit detail (not a separate menu). Checks HA history
 *  availability for the unit's primary sensor and runs a background import. */
export function HistoryImportControl({
  unitId,
  roomEntityId,
}: {
  unitId: number;
  roomEntityId: string | null;
}) {
  const { t } = useTranslation(["history", "common"]);
  const qc = useQueryClient();
  const [range, setRange] = React.useState<HistoryRange>("last_30_days");

  const avail = useQuery({
    queryKey: ["history-avail", unitId, roomEntityId],
    queryFn: () => api.getHistoryAvailability(unitId, roomEntityId!),
    enabled: !!roomEntityId,
  });
  const job = useQuery({
    queryKey: ["history-import", unitId],
    queryFn: () => api.getHistoryImport(unitId),
    refetchInterval: (q) => (q.state.data?.status === "importing" ? 2000 : false),
  });

  React.useEffect(() => {
    if (avail.data?.recommended_range) setRange(avail.data.recommended_range);
  }, [avail.data]);

  const start = useMutation({
    mutationFn: () => api.startHistoryImport(unitId, { entity_id: roomEntityId!, range }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["history-import", unitId] }),
  });

  const d = (s: string | null) => (s ? new Date(s).toLocaleString() : "—");
  const j = job.data;
  const importing = j?.status === "importing" || start.isPending;
  const a = avail.data;
  const availLabel = !a
    ? null
    : !a.connected
      ? t("history:availability.disconnected")
      : t(`history:availability.${a.state}`);

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-primary/15 text-primary">
          <History className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <CardTitle>{t("history:title")}</CardTitle>
          <p className="text-sm text-muted-foreground">{t("history:subtitle")}</p>
        </div>
        {availLabel && (
          <Badge tone={a?.state === "raw_available" ? "ok" : a?.state === "stats_only" ? "info" : "neutral"}>
            {availLabel}
          </Badge>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {!roomEntityId ? (
          <p className="text-sm text-muted-foreground">{t("history:noSensor")}</p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-muted-foreground">{t("history:import")}</span>
              <select
                value={range}
                onChange={(e) => setRange(e.target.value as HistoryRange)}
                disabled={importing}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm"
              >
                {RANGES.map((r) => (
                  <option key={r} value={r}>{t(`history:range.${r}`)}</option>
                ))}
              </select>
              <Button
                size="sm"
                onClick={() => start.mutate()}
                disabled={importing || a?.state === "no_history"}
              >
                <Download className={`h-3.5 w-3.5 ${importing ? "animate-pulse" : ""}`} />
                {importing ? t("history:status.importing") : t("history:start")}
              </Button>
            </div>

            {j && <JobLine job={j} d={d} onRetry={() => start.mutate()} retrying={start.isPending} />}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function JobLine({
  job,
  d,
  onRetry,
  retrying,
}: {
  job: import("@/lib/types").HistoryImportJob;
  d: (s: string | null) => string;
  onRetry: () => void;
  retrying: boolean;
}) {
  const { t } = useTranslation(["history"]);
  if (job.status === "importing") {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <RefreshCw className="h-3.5 w-3.5 animate-spin" /> {t("history:status.importing")}
      </div>
    );
  }
  if (job.status === "failed") {
    return (
      <div className="flex items-center gap-2 text-sm text-danger">
        <AlertTriangle className="h-4 w-4" /> {t("history:status.failed")}
        <Button size="sm" variant="outline" onClick={onRetry} disabled={retrying}>
          <RefreshCw className="h-3.5 w-3.5" /> {t("history:retry")}
        </Button>
      </div>
    );
  }
  if (job.status === "no_history") {
    return <p className="text-sm text-muted-foreground">{t("history:status.no_history")}</p>;
  }
  const from = job.raw_from ?? job.stats_from;
  const to = job.raw_to ?? job.stats_to;
  return (
    <div className="flex flex-col gap-0.5 text-sm">
      <span className="flex items-center gap-2 text-ok">
        <CheckCircle2 className="h-4 w-4" />
        {job.status === "partial"
          ? t("history:status.partial")
          : t("history:status.completed", { from: d(from), to: d(to) })}
      </span>
      <span className="text-xs text-muted-foreground">
        {job.raw_count > 0 && t("history:status.completed_raw", { n: job.raw_count })}
        {job.raw_count > 0 && job.stats_count > 0 && " · "}
        {job.stats_count > 0 && t("history:status.completed_stats", { n: job.stats_count })}
      </span>
    </div>
  );
}
