import * as React from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, AlertCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { DashboardUnit, EntityRole } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatNumber, timeAgo } from "@/lib/utils";
import { StatusIndicator } from "@/components/dashboard/StatusIndicator";
import { TemperatureHero } from "@/components/dashboard/TemperatureHero";
import { TemperatureRangeGauge } from "@/components/dashboard/TemperatureRangeGauge";
import { TemperatureChart } from "@/components/dashboard/TemperatureChart";
import { OperationalStateStrip } from "@/components/dashboard/OperationalStateStrip";
import { DataQualityIndicator } from "@/components/dashboard/DataQualityIndicator";
import {
  TimeRangeSegmentedControl,
  type TimeRange,
} from "@/components/dashboard/TimeRangeSegmentedControl";
import { DefrostLearningPanel } from "@/features/units/DefrostLearningPanel";

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

export function UnitDetail({
  unit,
  onBack,
}: {
  unit: DashboardUnit;
  onBack: () => void;
}) {
  const { t } = useTranslation(["dashboard", "profiles", "incidents"]);
  const [range, setRange] = React.useState<TimeRange>("24h");

  const history = useQuery({
    queryKey: ["samples", unit.id, range],
    queryFn: () => api.getSamples(unit.id, { range, role: "room_temperature" }),
    refetchInterval: 30000,
  });

  const cyclesQuery = useQuery({
    queryKey: ["defrost-cycles", unit.id, range],
    queryFn: () => api.getDefrostCycles(unit.id, range),
    refetchInterval: 30000,
  });

  const hasDefrostSensor = unit.roles.some((r) => r.role === "defrost");
  const room = unit.room;
  const stripRoles = STRIP_ROLES.map((r) => unit.roles.find((x) => x.role === r)).filter(
    (x): x is NonNullable<typeof x> => Boolean(x),
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={onBack} aria-label={t("detail.back")}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-xl font-semibold leading-tight">{unit.name}</h1>
            <p className="text-xs text-muted-foreground">
              {t(`profiles:types.${unit.unit_type}`)}
              {unit.profile_name ? ` · ${unit.profile_name}` : ""}
            </p>
          </div>
        </div>
        <StatusIndicator status={unit.status} />
      </div>

      {/* current values row */}
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Card>
          <CardContent className="flex flex-col gap-3 pt-5">
            <TemperatureHero valueC={room?.numeric_c ?? null} unit={room?.unit ?? "°C"} />
            <TemperatureRangeGauge
              current={room?.numeric_c ?? null}
              lower={unit.lower_limit_c}
              upper={unit.upper_limit_c}
              warningMargin={unit.warning_margin_c}
            />
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <DataQualityIndicator quality={room?.quality} />
              <span>
                {t("card.lastUpdate")}: {timeAgo(unit.last_update)}
              </span>
            </div>
            {room?.entity_id && (
              <div className="text-xs text-muted-foreground">
                {t("detail.sourceEntity")}:{" "}
                <span className="font-mono">{room.entity_id}</span>
              </div>
            )}
            <OperationalStateStrip roles={stripRoles} />

            {!hasDefrostSensor && (
              <div className="rounded-md border border-border bg-muted/40 p-2.5 text-xs text-muted-foreground">
                <div className="font-medium text-foreground">
                  {t("incidents:defrost.noSensorTitle")}
                </div>
                {t("incidents:defrost.noSensorHint")}
              </div>
            )}
          </CardContent>
        </Card>

        {/* chart */}
        <Card>
          <CardContent className="flex flex-col gap-3 pt-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex gap-4 text-xs text-muted-foreground">
                <Stat label={t("detail.min")} value={history.data?.min_c} />
                <Stat label={t("detail.avg")} value={history.data?.avg_c} />
                <Stat label={t("detail.max")} value={history.data?.max_c} />
                <Stat
                  label={t("detail.coverage")}
                  value={
                    history.data?.coverage_ratio != null
                      ? history.data.coverage_ratio * 100
                      : null
                  }
                  suffix="%"
                  digits={0}
                />
              </div>
              <TimeRangeSegmentedControl value={range} onChange={setRange} includeCustom={false} />
            </div>

            {history.isLoading ? (
              <Skeleton className="h-[340px] w-full" />
            ) : history.isError ? (
              <div className="flex h-[340px] items-center justify-center gap-2 text-sm text-danger">
                <AlertCircle className="h-5 w-5" /> {t("error.title")}
              </div>
            ) : history.data && history.data.points.length > 0 ? (
              <>
                <TemperatureChart
                  points={history.data.points}
                  lower={history.data.lower_limit_c}
                  upper={history.data.upper_limit_c}
                  setpoint={unit.setpoint_c}
                  defrostCycles={cyclesQuery.data ?? []}
                />
                {history.data.downsampled && (
                  <p className="text-[11px] text-muted-foreground">
                    {t("detail.downsampledNote")}
                  </p>
                )}
              </>
            ) : (
              <div className="grid h-[340px] place-items-center text-sm text-muted-foreground">
                {t("detail.noSamples")}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {hasDefrostSensor && <DefrostLearningPanel unitId={unit.id} />}
    </div>
  );
}

function Stat({
  label,
  value,
  suffix = "°",
  digits = 1,
}: {
  label: string;
  value: number | null | undefined;
  suffix?: string;
  digits?: number;
}) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide">{label}</div>
      <div className="text-sm font-semibold tabular-nums text-foreground">
        {value != null ? `${formatNumber(value, { maximumFractionDigits: digits })}${suffix}` : "—"}
      </div>
    </div>
  );
}
