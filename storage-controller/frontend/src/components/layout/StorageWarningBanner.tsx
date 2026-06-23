import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Persistent banner shown when app storage reaches warning/critical/emergency. */
export function StorageWarningBanner() {
  const { t } = useTranslation("settings");
  const { data } = useQuery({
    queryKey: ["maintenance"],
    queryFn: api.getMaintenanceStatus,
    refetchInterval: 60000,
  });

  if (!data || data.level === "ok") return null;

  const tone =
    data.level === "emergency" || data.level === "critical"
      ? "border-danger/40 bg-danger/10 text-danger"
      : "border-warn/40 bg-warn/10 text-warn";

  return (
    <div
      role="alert"
      className={cn("flex items-center gap-2 border-b px-5 py-2 text-sm font-medium", tone)}
    >
      <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
      {t(`banner.${data.level}`, { pct: data.budget_used_percent })}
    </div>
  );
}
