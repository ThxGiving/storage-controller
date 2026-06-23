import * as React from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  History,
  Download,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Ban,
} from "lucide-react";
import { api } from "@/lib/api";
import type { HistoryDateRange, HistoryImportJob, HistoryRange, StorageUnit } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const RANGES: HistoryRange[] = ["last_30_days", "last_90_days", "current_month", "all"];

const fmtDate = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleDateString() : "—";
const fmtRange = (r: HistoryDateRange) => `${fmtDate(r.start)}–${fmtDate(r.end)}`;

/** Per-unit Home Assistant history import, shown on the storage-units management
 *  page below the list. One compact row per unit — never a single global box. */
export function HistoryImportSection({
  units,
  promptUnitId,
}: {
  units: StorageUnit[];
  promptUnitId?: number | null;
}) {
  const { t } = useTranslation(["history"]);
  if (units.length === 0) return null;

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-primary/15 text-primary">
          <History className="h-5 w-5" />
        </div>
        <div>
          <CardTitle>{t("history:title")}</CardTitle>
          <p className="text-sm text-muted-foreground">{t("history:subtitle")}</p>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col divide-y divide-border">
          {units.map((u) => (
            <Row
              key={u.id}
              unit={u}
              entityId={u.assignments.find((a) => a.role === "room_temperature")?.entity_id ?? null}
              prompt={promptUnitId === u.id}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function Row({
  unit,
  entityId,
  prompt,
}: {
  unit: StorageUnit;
  entityId: string | null;
  prompt: boolean;
}) {
  const { t } = useTranslation(["history"]);
  const qc = useQueryClient();
  const [range, setRange] = React.useState<HistoryRange>("last_30_days");

  const avail = useQuery({
    queryKey: ["history-avail", unit.id, entityId],
    queryFn: () => api.getHistoryAvailability(unit.id, entityId as string),
    enabled: entityId !== null,
  });
  const job = useQuery({
    queryKey: ["history-import", unit.id],
    queryFn: () => api.getHistoryImport(unit.id),
    enabled: entityId !== null,
    refetchInterval: (q) => (q.state.data?.status === "importing" ? 2000 : false),
  });
  React.useEffect(() => {
    if (avail.data?.recommended_range) setRange(avail.data.recommended_range);
  }, [avail.data]);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["history-import", unit.id] });
  const start = useMutation({
    mutationFn: () => api.startHistoryImport(unit.id, { entity_id: entityId as string, range }),
    onSuccess: invalidate,
  });
  const cancel = useMutation({
    mutationFn: () => api.cancelHistoryImport(unit.id),
    onSuccess: invalidate,
  });

  // No primary temperature sensor → show that clearly, nothing to import.
  if (entityId === null) {
    return (
      <div className="flex flex-wrap items-center gap-3 py-2.5">
        <span className="min-w-[140px] font-medium">{unit.name}</span>
        <Badge tone="neutral">{t("history:noSensorBadge")}</Badge>
      </div>
    );
  }

  const j: HistoryImportJob | null | undefined = job.data;
  const a = avail.data;
  const importing = j?.status === "importing" || start.isPending;
  const resumable = j?.status === "failed" || j?.status === "partial" || j?.status === "cancelled";
  const noData = a?.state === "no_history" && !resumable;

  const btnLabel = importing
    ? t("history:status.importing")
    : resumable
      ? t("history:resume")
      : j?.status === "completed"
        ? t("history:extend")
        : t("history:start");

  const highlightPrompt = prompt && a && a.state !== "no_history" && j?.status !== "completed";

  return (
    <div
      className={`flex flex-col gap-1.5 py-2.5 ${
        highlightPrompt ? "-mx-3 rounded-md bg-primary/5 px-3 ring-1 ring-primary/30" : ""
      }`}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="min-w-[140px] font-medium">{unit.name}</span>

        {a && (
          <Badge
            tone={a.state === "raw_available" ? "ok" : a.state === "stats_only" ? "info" : "neutral"}
          >
            {!a.connected ? t("history:availability.disconnected") : t(`history:availability.${a.state}`)}
          </Badge>
        )}
        {a && (a.earliest || a.latest) && (
          <span className="text-xs text-muted-foreground">
            {fmtDate(a.earliest)} – {fmtDate(a.latest)}
          </span>
        )}

        <div className="ml-auto flex items-center gap-2">
          <select
            value={range}
            onChange={(e) => setRange(e.target.value as HistoryRange)}
            disabled={importing}
            className="h-9 rounded-md border border-input bg-background px-2 text-sm"
          >
            {RANGES.map((r) => (
              <option key={r} value={r}>
                {t(`history:range.${r}`)}
              </option>
            ))}
          </select>
          <Button size="sm" onClick={() => start.mutate()} disabled={importing || noData}>
            <Download className={`h-3.5 w-3.5 ${importing ? "animate-pulse" : ""}`} />
            {btnLabel}
          </Button>
          {importing && (
            <Button size="sm" variant="outline" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
              <Ban className="h-3.5 w-3.5" /> {t("history:cancel")}
            </Button>
          )}
        </div>
      </div>

      {highlightPrompt && (
        <p className="text-sm font-medium text-primary">{t("history:prompt")}</p>
      )}

      {j && <StatusLine job={j} />}
    </div>
  );
}

function StatusLine({ job: j }: { job: HistoryImportJob }) {
  const { t } = useTranslation(["history"]);

  if (j.status === "importing") {
    const pct = j.chunks_total > 0 ? Math.round((j.chunks_done / j.chunks_total) * 100) : 0;
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <RefreshCw className="h-3.5 w-3.5 animate-spin" />
        <span>{t("history:status.importing")}</span>
        {j.chunks_total > 0 && (
          <>
            <span className="h-1.5 w-28 overflow-hidden rounded-full bg-muted">
              <span
                className="block h-full rounded-full bg-primary transition-all"
                style={{ width: `${pct}%` }}
              />
            </span>
            <span className="tabular-nums">
              {pct}% ({j.chunks_done}/{j.chunks_total})
            </span>
          </>
        )}
      </div>
    );
  }
  if (j.status === "no_history") {
    return <span className="text-sm text-muted-foreground">{t("history:status.no_history")}</span>;
  }

  // Imported / failed windows, shown explicitly so a partial import is actionable.
  const imported = j.imported_ranges.map(fmtRange).join(", ");
  const failed = j.failed_ranges.map(fmtRange).join(", ");
  const statsNote = j.stats_count > 0 ? ` · ${t("history:status.statsNote")}` : "";

  if (j.status === "completed") {
    return (
      <span className="flex items-center gap-1.5 text-sm text-ok">
        <CheckCircle2 className="h-4 w-4" />
        {t("history:status.completed", { from: fmtDate(j.raw_from ?? j.stats_from), to: fmtDate(j.raw_to ?? j.stats_to) })}
        {statsNote}
      </span>
    );
  }
  if (j.status === "cancelled") {
    return (
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
        <Ban className="h-4 w-4 text-muted-foreground" />
        <span className="text-muted-foreground">{t("history:status.cancelled")}</span>
        {imported && <span className="text-ok">{t("history:importedRanges", { ranges: imported })}</span>}
      </span>
    );
  }
  // partial or failed → show exactly which windows succeeded vs failed.
  const Icon = j.status === "failed" ? XCircle : AlertTriangle;
  const tone = j.status === "failed" ? "text-danger" : "text-warn";
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
      <Icon className={`h-4 w-4 ${tone}`} />
      {imported && <span className="text-ok">{t("history:importedRanges", { ranges: imported })}</span>}
      {failed && <span className="text-danger">{t("history:failedRanges", { ranges: failed })}</span>}
      {!imported && !failed && <span className={tone}>{t("history:status.failed")}</span>}
      {statsNote && <span className="text-muted-foreground">{statsNote}</span>}
    </span>
  );
}
