import { useTranslation } from "react-i18next";
import { cn, formatNumber } from "@/lib/utils";

interface Props {
  current: number | null;
  lower: number | null;
  upper: number | null;
  warningMargin?: number;
  className?: string;
}

/**
 * Compact horizontal range indicator: lower limit, warning zones, current
 * position and upper limit. Always shows numeric values — never color-only.
 */
export function TemperatureRangeGauge({
  current,
  lower,
  upper,
  warningMargin = 0,
  className,
}: Props) {
  const { t } = useTranslation("dashboard");

  // Build a display domain with padding so the bar has context beyond limits.
  const lo = lower ?? (current != null ? current - 5 : 0);
  const hi = upper ?? (current != null ? current + 5 : 10);
  const span = Math.max(hi - lo, 0.1);
  const pad = span * 0.25;
  const domainLo = lo - pad;
  const domainHi = hi + pad;
  const domain = domainHi - domainLo;

  const pct = (v: number) => clamp(((v - domainLo) / domain) * 100, 0, 100);

  const lowerPct = lower != null ? pct(lower) : null;
  const upperPct = upper != null ? pct(upper) : null;
  const currentPct = current != null ? pct(current) : null;

  const outOfRange =
    current != null &&
    ((lower != null && current < lower) || (upper != null && current > upper));

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <div
        className="relative h-2.5 w-full rounded-full bg-muted"
        role="img"
        aria-label={
          current != null
            ? `${t("gauge.current")} ${formatNumber(current, { maximumFractionDigits: 1 })} °C`
            : t("card.noData")
        }
      >
        {/* permitted band */}
        {lowerPct != null && upperPct != null && (
          <div
            className="absolute inset-y-0 rounded-full bg-ok/25"
            style={{ left: `${lowerPct}%`, right: `${100 - upperPct}%` }}
          />
        )}
        {/* warning zones just inside each limit */}
        {upperPct != null && warningMargin > 0 && (
          <div
            className="absolute inset-y-0 bg-warn/30"
            style={{
              left: `${pct((upper ?? 0) - warningMargin)}%`,
              right: `${100 - upperPct}%`,
            }}
          />
        )}
        {lowerPct != null && warningMargin > 0 && (
          <div
            className="absolute inset-y-0 bg-warn/30"
            style={{
              left: `${lowerPct}%`,
              right: `${100 - pct((lower ?? 0) + warningMargin)}%`,
            }}
          />
        )}
        {/* limit ticks */}
        {lowerPct != null && <Tick pct={lowerPct} />}
        {upperPct != null && <Tick pct={upperPct} />}
        {/* current marker */}
        {currentPct != null && (
          <div
            className={cn(
              "absolute top-1/2 h-4 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-background",
              outOfRange ? "bg-danger" : "bg-foreground",
            )}
            style={{ left: `${currentPct}%` }}
          />
        )}
      </div>
      <div className="flex justify-between text-[11px] tabular-nums text-muted-foreground">
        <span>{lower != null ? `${formatNumber(lower, { maximumFractionDigits: 1 })}°` : "—"}</span>
        <span>{upper != null ? `${formatNumber(upper, { maximumFractionDigits: 1 })}°` : "—"}</span>
      </div>
    </div>
  );
}

function Tick({ pct }: { pct: number }) {
  return (
    <div
      className="absolute inset-y-0 w-px bg-foreground/40"
      style={{ left: `${pct}%` }}
      aria-hidden
    />
  );
}

function clamp(v: number, lo: number, hi: number) {
  return Math.min(Math.max(v, lo), hi);
}
