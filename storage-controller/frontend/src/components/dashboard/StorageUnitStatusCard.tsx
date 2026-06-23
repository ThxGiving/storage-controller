import { useTranslation } from "react-i18next";
import { ChevronRight } from "lucide-react";
import type { DashboardUnit, EntityRole } from "@/lib/types";
import { cn, formatNumber, timeAgo } from "@/lib/utils";
import { StatusIndicator } from "./StatusIndicator";
import { TemperatureHero } from "./TemperatureHero";
import { TemperatureRangeGauge } from "./TemperatureRangeGauge";
import { TemperatureSparkline } from "./TemperatureSparkline";
import { OperationalStateStrip } from "./OperationalStateStrip";
import { DataQualityIndicator } from "./DataQualityIndicator";
import { DefrostStatusPill } from "./DefrostStatusPill";
import { IncidentBadge } from "@/components/incidents/IncidentBadge";
import { formatDuration } from "@/lib/utils";

const STRIP_ROLES: EntityRole[] = [
  "evaporator_temperature",
  "setpoint",
  "compressor",
  "fan",
  "defrost",
  "controller",
  "light",
  "door",
  "alarm",
];

export function StorageUnitStatusCard({
  unit,
  onOpen,
}: {
  unit: DashboardUnit;
  onOpen: (unit: DashboardUnit) => void;
}) {
  const { t } = useTranslation(["dashboard", "profiles"]);
  const room = unit.room;
  const muted =
    unit.status === "unavailable" ||
    unit.status === "disconnected" ||
    unit.status === "configuration_error";

  const stripRoles = STRIP_ROLES.map((r) => unit.roles.find((x) => x.role === r)).filter(
    (x): x is NonNullable<typeof x> => Boolean(x),
  );

  return (
    <button
      type="button"
      onClick={() => onOpen(unit)}
      aria-label={`${unit.name} — ${t("card.openDetail")}`}
      className={cn(
        "group flex flex-col gap-3 rounded-xl border border-border bg-card p-4 text-left",
        "shadow-card transition-colors hover:border-primary/40 focus-visible:outline-none",
        "focus-visible:ring-2 focus-visible:ring-ring",
      )}
    >
      {/* header */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-semibold leading-tight">{unit.name}</div>
          <div className="truncate text-xs text-muted-foreground">
            {t(`profiles:types.${unit.unit_type}`)}
            {unit.profile_name ? ` · ${unit.profile_name}` : ""}
          </div>
        </div>
        <StatusIndicator status={unit.status} />
      </div>

      {/* hero + spark */}
      <div className="flex items-end justify-between gap-2">
        <TemperatureHero valueC={room?.numeric_c ?? null} unit={room?.unit ?? "°C"} muted={muted} />
        <div className="h-14 w-28 shrink-0 sm:w-36">
          {unit.spark.length > 0 ? (
            <TemperatureSparkline
              points={unit.spark}
              lower={unit.lower_limit_c}
              upper={unit.upper_limit_c}
              height={56}
            />
          ) : (
            <div className="grid h-full place-items-center text-[11px] text-muted-foreground">
              {t("card.noData")}
            </div>
          )}
        </div>
      </div>

      {/* range gauge */}
      <TemperatureRangeGauge
        current={room?.numeric_c ?? null}
        lower={unit.lower_limit_c}
        upper={unit.upper_limit_c}
        warningMargin={unit.warning_margin_c}
      />

      {/* meta row */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <DataQualityIndicator quality={room?.quality} />
        <span>
          {t("card.lastUpdate")}: {timeAgo(unit.last_update)}
        </span>
        {unit.setpoint_c != null && (
          <span>
            {t("card.setpoint")}: {formatNumber(unit.setpoint_c, { maximumFractionDigits: 1 })}°
          </span>
        )}
      </div>

      {/* defrost (operational, not a critical warning) */}
      {unit.defrost && <DefrostStatusPill defrost={unit.defrost} />}

      {/* active incidents */}
      {unit.active_incidents.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {unit.active_incidents.slice(0, 3).map((inc) => (
            <span key={inc.id} className="inline-flex items-center gap-1">
              <IncidentBadge type={inc.type} state={inc.state} />
              <span className="text-[11px] tabular-nums text-muted-foreground">
                {formatDuration(inc.opened_at)}
              </span>
            </span>
          ))}
        </div>
      )}

      {/* operational strip */}
      <OperationalStateStrip roles={stripRoles} />

      <div className="mt-auto flex items-center justify-end pt-1 text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
        {t("card.openDetail")}
        <ChevronRight className="h-3.5 w-3.5" aria-hidden />
      </div>
    </button>
  );
}
