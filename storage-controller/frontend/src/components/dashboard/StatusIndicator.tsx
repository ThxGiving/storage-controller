import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { STATUS_VISUALS, TONE_CLASSES } from "@/lib/status";
import type { OperationalStatus } from "@/lib/types";

/**
 * Operational status as an icon + text label (never color alone). Used on cards
 * and in the dashboard header.
 */
export function StatusIndicator({
  status,
  size = "md",
  className,
}: {
  status: OperationalStatus;
  size?: "sm" | "md";
  className?: string;
}) {
  const { t } = useTranslation("dashboard");
  const v = STATUS_VISUALS[status] ?? STATUS_VISUALS.disconnected;
  const tone = TONE_CLASSES[v.tone];
  const label = t(`status.${v.i18nKey}`);
  return (
    <span
      role="status"
      aria-label={label}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md font-medium ring-1 ring-inset",
        tone.text,
        tone.bg,
        tone.ring,
        size === "sm" ? "px-1.5 py-0.5 text-[11px]" : "px-2 py-1 text-xs",
        className,
      )}
    >
      <v.Icon className={size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5"} aria-hidden />
      {label}
    </span>
  );
}
