import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { TONE_CLASSES } from "@/lib/status";
import { incidentVisual } from "@/lib/incidents";

/** Compact incident chip: icon + type label (+ optional state). Not color-only. */
export function IncidentBadge({
  type,
  state,
  size = "sm",
  className,
}: {
  type: string;
  state?: string;
  size?: "sm" | "md";
  className?: string;
}) {
  const { t } = useTranslation("incidents");
  const v = incidentVisual(type);
  const tone = TONE_CLASSES[v.tone];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md font-medium ring-1 ring-inset",
        tone.text,
        tone.bg,
        tone.ring,
        size === "sm" ? "px-1.5 py-0.5 text-[11px]" : "px-2 py-1 text-xs",
        className,
      )}
    >
      <v.Icon className={size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5"} aria-hidden />
      {t(`types.${type}`, { defaultValue: type })}
      {state ? (
        <span className="opacity-70">· {t(`states.${state}`, { defaultValue: state })}</span>
      ) : null}
    </span>
  );
}
