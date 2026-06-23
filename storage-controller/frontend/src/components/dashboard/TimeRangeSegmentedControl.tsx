import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

export type TimeRange = "24h" | "7d" | "30d" | "custom";

const ORDER: TimeRange[] = ["24h", "7d", "30d", "custom"];

/**
 * Accessible segmented control for the chart time range. Implements a
 * radiogroup with roving focus and arrow-key navigation.
 */
export function TimeRangeSegmentedControl({
  value,
  onChange,
  className,
  includeCustom = true,
}: {
  value: TimeRange;
  onChange: (value: TimeRange) => void;
  className?: string;
  includeCustom?: boolean;
}) {
  const { t } = useTranslation("dashboard");
  const options = includeCustom ? ORDER : ORDER.filter((o) => o !== "custom");

  const onKeyDown = (e: React.KeyboardEvent, idx: number) => {
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      onChange(options[(idx + 1) % options.length]);
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      onChange(options[(idx - 1 + options.length) % options.length]);
    }
  };

  return (
    <div
      role="radiogroup"
      aria-label={t("range.24h")}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-lg border border-border bg-muted/50 p-0.5",
        className,
      )}
    >
      {options.map((opt, idx) => {
        const selected = opt === value;
        return (
          <button
            key={opt}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(opt)}
            onKeyDown={(e) => onKeyDown(e, idx)}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              selected
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t(`range.${opt}`)}
          </button>
        );
      })}
    </div>
  );
}
