import { useTranslation } from "react-i18next";
import { Activity, AlertTriangle, CloudOff, HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { TONE_CLASSES, qualityTone } from "@/lib/status";

const ICONS: Record<string, typeof Activity> = {
  valid: Activity,
  unavailable: CloudOff,
  unknown: HelpCircle,
  invalid: AlertTriangle,
  implausible: AlertTriangle,
  stale: AlertTriangle,
  missing: CloudOff,
};

/** Compact data-quality chip (icon + label), not color-only. */
export function DataQualityIndicator({
  quality,
  className,
}: {
  quality: string | null | undefined;
  className?: string;
}) {
  const { t } = useTranslation("dashboard");
  const q = quality ?? "missing";
  const tone = TONE_CLASSES[qualityTone(q)];
  const Icon = ICONS[q] ?? HelpCircle;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium",
        tone.text,
        tone.bg,
        className,
      )}
      title={t(`quality.${q}`, { defaultValue: q })}
    >
      <Icon className="h-3 w-3" aria-hidden />
      {t(`quality.${q}`, { defaultValue: q })}
    </span>
  );
}
