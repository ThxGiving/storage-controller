import { useTranslation } from "react-i18next";
import { Snowflake, Thermometer } from "lucide-react";
import type { DashboardDefrost } from "@/lib/types";
import { cn, formatDuration, formatNumber } from "@/lib/utils";

/**
 * Operational defrost indicator (NOT a critical red warning). Shows active
 * defrost or post-defrost recovery with elapsed time and a recovery progress bar.
 */
export function DefrostStatusPill({ defrost }: { defrost: DashboardDefrost }) {
  const { t } = useTranslation("incidents");
  const recovering = defrost.status === "recovering";

  const elapsedRef = recovering ? defrost.recovery_started_at : defrost.started_at;
  const maxSeconds = recovering
    ? defrost.max_recovery_seconds
    : defrost.max_expected_duration_seconds;
  const elapsedMs = elapsedRef ? Date.now() - new Date(elapsedRef).getTime() : 0;
  const pct = Math.min(100, Math.max(0, (elapsedMs / 1000 / Math.max(maxSeconds, 1)) * 100));

  return (
    <div
      className={cn(
        "rounded-md border px-2 py-1.5 text-[11px]",
        recovering
          ? "border-info/40 bg-info/10 text-info"
          : "border-primary/40 bg-primary/10 text-primary",
      )}
    >
      <div className="flex items-center gap-1.5 font-medium">
        {recovering ? (
          <Thermometer className="h-3.5 w-3.5" aria-hidden />
        ) : (
          <Snowflake className="h-3.5 w-3.5" aria-hidden />
        )}
        {recovering ? t("defrost.recovering") : t("defrost.active")}
        <span className="ml-auto tabular-nums opacity-80">
          {t("defrost.elapsed")} {formatDuration(elapsedRef)}
        </span>
      </div>
      <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-current/15">
        <div
          className="h-full rounded-full bg-current"
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={Math.round(pct)}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
      {recovering && defrost.recovery_target_c != null && (
        <div className="mt-1 opacity-80">
          {t("defrost.target")}: {formatNumber(defrost.recovery_target_c, { maximumFractionDigits: 1 })}°
        </div>
      )}
    </div>
  );
}
