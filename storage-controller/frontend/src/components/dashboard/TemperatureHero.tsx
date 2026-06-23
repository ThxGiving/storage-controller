import { useTranslation } from "react-i18next";
import { Thermometer } from "lucide-react";
import { cn, formatNumber } from "@/lib/utils";

/** The dominant current temperature value for a unit. */
export function TemperatureHero({
  valueC,
  unit = "°C",
  muted = false,
  className,
}: {
  valueC: number | null;
  unit?: string | null;
  muted?: boolean;
  className?: string;
}) {
  const { t } = useTranslation("dashboard");
  const hasValue = valueC != null && Number.isFinite(valueC);
  return (
    <div className={cn("flex items-end gap-2", className)}>
      <Thermometer
        className={cn("mb-1.5 h-7 w-7 shrink-0", muted ? "text-muted-foreground" : "text-primary")}
        aria-hidden
      />
      {hasValue ? (
        <>
          <span className="text-[2.75rem] font-semibold leading-none tracking-tight tabular-nums">
            {formatNumber(valueC, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
          </span>
          <span className="mb-1.5 text-lg font-medium text-muted-foreground">{unit ?? "°C"}</span>
        </>
      ) : (
        <span className="mb-1 text-lg font-medium text-muted-foreground">{t("card.noData")}</span>
      )}
    </div>
  );
}
