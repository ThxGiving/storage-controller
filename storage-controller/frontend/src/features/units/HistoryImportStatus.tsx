import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { History } from "lucide-react";
import { api } from "@/lib/api";

const fmtDate = (s: string | null) => (s ? new Date(s).toLocaleDateString() : "—");

/** Read-only history-import status for the unit detail view. The import itself is
 *  started/managed on the storage-units management page, not here. */
export function HistoryImportStatus({ unitId }: { unitId: number }) {
  const { t } = useTranslation(["history"]);
  const job = useQuery({
    queryKey: ["history-import", unitId],
    queryFn: () => api.getHistoryImport(unitId),
    refetchInterval: (q) => (q.state.data?.status === "importing" ? 3000 : false),
  });
  const j = job.data;

  let line = t("history:detailNone");
  if (j?.status === "importing") line = t("history:status.importing");
  else if (j?.status === "completed")
    line = t("history:status.completed", { from: fmtDate(j.raw_from ?? j.stats_from), to: fmtDate(j.raw_to ?? j.stats_to) });
  else if (j?.status === "partial") line = t("history:detailPartial");
  else if (j?.status === "failed") line = t("history:status.failed");
  else if (j?.status === "cancelled") line = t("history:status.cancelled");

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
      <History className="h-3.5 w-3.5" />
      <span className="font-medium">{t("history:title")}:</span>
      <span>{line}</span>
      <span className="ml-auto italic">{t("history:manageHint")}</span>
    </div>
  );
}
