import * as React from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Snowflake, CheckCircle2, RotateCcw, AlertTriangle, Info } from "lucide-react";
import { api } from "@/lib/api";
import type { DefrostCycle, DefrostLearningStatus, LearnedDefrostModel } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { formatNumber, timeAgo } from "@/lib/utils";

const LEARNABLE = new Set(["expected_defrost", "expected_defrost_excursion"]);

/** Advanced/diagnostic view of a unit's defrost learning. Hidden unless a
 *  defrost entity is assigned and defrost-aware evaluation is enabled. */
export function DefrostLearningPanel({ unitId }: { unitId: number }) {
  const { t } = useTranslation(["defrost", "common"]);
  const qc = useQueryClient();

  const query = useQuery({
    queryKey: ["defrost-learning", unitId],
    queryFn: () => api.getDefrostLearning(unitId),
    refetchInterval: 60000,
  });

  const approve = useMutation({
    mutationFn: () => api.approveDefrostLearning(unitId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["defrost-learning", unitId] }),
  });
  const reset = useMutation({
    mutationFn: () => api.resetDefrostLearning(unitId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["defrost-learning", unitId] }),
  });

  const data = query.data;
  // Only meaningful once the toggle + entity are in place.
  if (!data || !data.enabled) return null;

  const busy = approve.isPending || reset.isPending;

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-primary/15 text-primary">
          <Snowflake className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <CardTitle className="flex items-center gap-2">
            {t("defrost:title")}
            <Badge tone={stateTone(data.state)}>{t(`defrost:state.${stateKey(data.state)}`)}</Badge>
          </CardTitle>
          <p className="text-sm text-muted-foreground">{t("defrost:subtitle")}</p>
        </div>
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        <p className="text-sm text-muted-foreground">{t(`defrost:${hintKey(data.state)}`)}</p>

        <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <Metric label={t("defrost:validCycles")}>
            <span className="tabular-nums">{data.valid_cycle_count}</span>
            <span className="text-muted-foreground"> / {data.min_cycles}</span>
          </Metric>
          <Metric label={t("defrost:confidence")}>
            {t(`defrost:confidenceLevel.${data.confidence}`)}{" "}
            <span className="text-xs text-muted-foreground tabular-nums">
              ({Math.round(data.confidence_score * 100)}%)
            </span>
          </Metric>
        </div>

        {data.state !== "approved" && data.valid_cycle_count < data.min_cycles && (
          <p className="text-xs text-muted-foreground">
            {t("defrost:remainingCycles", {
              remaining: data.min_cycles - data.valid_cycle_count,
            })}
          </p>
        )}

        {data.drift_warning && (
          <Banner tone="warn" icon={<AlertTriangle className="h-4 w-4" />}>
            <span className="font-medium">{t("defrost:drift")}.</span>{" "}
            {t("defrost:driftHint", { detail: data.drift_detail ?? "" })}
          </Banner>
        )}

        {/* Approved (active) model */}
        {data.approved && <ModelGrid model={data.approved} />}

        {/* Pending suggestion (only when nothing approved yet) */}
        {!data.approved && data.suggestion && <ModelGrid model={data.suggestion} />}

        {data.outlier_count > 0 && (
          <p className="text-xs text-muted-foreground">
            {t("defrost:outliers", { list: data.outliers.join(", ") })}
          </p>
        )}

        {/* Diagnostic: why each observed cycle did or didn't count toward learning. */}
        <div className="flex flex-col gap-1.5">
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
            {t("defrost:recentCycles")}
          </div>
          {data.recent_cycles.length === 0 ? (
            <p className="text-xs text-muted-foreground">{t("defrost:cycle.empty")}</p>
          ) : (
            <ul className="flex flex-col divide-y divide-border rounded-md border border-border">
              {data.recent_cycles.slice(0, 8).map((c) => (
                <CycleRow key={c.id} cycle={c} />
              ))}
            </ul>
          )}
        </div>

        <Banner tone="info" icon={<Info className="h-4 w-4" />}>
          {t("defrost:safetyNote")}
        </Banner>

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-3">
          {data.state === "suggestion_ready" && (
            <Button onClick={() => approve.mutate()} disabled={busy}>
              <CheckCircle2 className="h-4 w-4" />
              {approve.isPending ? t("defrost:actions.running") : t("defrost:actions.approve")}
            </Button>
          )}
          {(data.approved || data.suggestion) && (
            <Button
              variant="outline"
              onClick={() => {
                if (window.confirm(t("defrost:resetConfirm"))) reset.mutate();
              }}
              disabled={busy}
            >
              <RotateCcw className="h-4 w-4" />
              {reset.isPending ? t("defrost:actions.running") : t("defrost:actions.reset")}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function ModelGrid({ model }: { model: LearnedDefrostModel }) {
  const { t } = useTranslation(["defrost", "common"]);
  const min = (s: number | null) =>
    s == null ? "—" : `${formatNumber(s / 60, { maximumFractionDigits: 0 })} ${t("defrost:units.minutes")}`;
  const deg = (c: number | null) =>
    c == null ? "—" : `${formatNumber(c, { maximumFractionDigits: 1 })} °C`;

  return (
    <div className="grid gap-x-6 gap-y-2 rounded-md border border-border bg-muted/30 p-3 text-sm sm:grid-cols-3">
      <Metric label={t("defrost:metrics.typicalDuration")}>{min(model.typical_defrost_seconds)}</Metric>
      <Metric label={t("defrost:metrics.maxDuration")}>{min(model.max_defrost_seconds)}</Metric>
      <Metric label={t("defrost:metrics.typicalRecovery")}>{min(model.typical_recovery_seconds)}</Metric>
      <Metric label={t("defrost:metrics.typicalRoomPeak")}>{deg(model.typical_room_peak_c)}</Metric>
      <Metric label={t("defrost:metrics.maxRoomPeak")}>{deg(model.max_room_peak_c)}</Metric>
      <Metric label={t("defrost:metrics.maxEvapPeak")}>{deg(model.max_evaporator_peak_c)}</Metric>
      <Metric label={t("defrost:metrics.interval")}>{min(model.typical_interval_seconds)}</Metric>
      <Metric label={t("defrost:metrics.variation")}>{deg(model.room_peak_variation_c)}</Metric>
      <Metric label={t("defrost:metrics.safetyMargin")}>{deg(model.safety_margin_c)}</Metric>
    </div>
  );
}

function CycleRow({ cycle }: { cycle: DefrostCycle }) {
  const { t } = useTranslation(["defrost"]);
  const counts = cycle.status === "completed" && LEARNABLE.has(cycle.classification ?? "");
  const start = cycle.started_at ? new Date(cycle.started_at).getTime() : null;
  const end = cycle.ended_at ? new Date(cycle.ended_at).getTime() : null;
  const durMin = start && end && end > start ? Math.round((end - start) / 60000) : null;
  const statusKey = ["active", "recovering", "completed", "abnormal", "incomplete"].includes(
    cycle.status,
  )
    ? cycle.status
    : "active";

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-xs">
      <Badge tone={counts ? "ok" : cycle.status === "abnormal" ? "warn" : "neutral"}>
        {t(`defrost:cycle.status.${statusKey}`)}
      </Badge>
      <span className="text-muted-foreground">{timeAgo(cycle.started_at)}</span>
      <span className="tabular-nums">
        {durMin != null ? `${durMin} ${t("defrost:units.minutes")}` : "—"}
      </span>
      <span className="tabular-nums">
        {cycle.peak_room_temperature_c != null
          ? `↑ ${formatNumber(cycle.peak_room_temperature_c, { maximumFractionDigits: 1 })} °C`
          : t("defrost:cycle.noPeak")}
      </span>
      <span className={`ml-auto ${counts ? "text-ok" : "text-muted-foreground"}`}>
        {counts ? t("defrost:cycle.counts") : t("defrost:cycle.ignored")}
      </span>
    </li>
  );
}

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="font-semibold text-foreground">{children}</div>
    </div>
  );
}

function Banner({
  tone,
  icon,
  children,
}: {
  tone: "info" | "warn";
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  const cls =
    tone === "warn"
      ? "border-warn/40 bg-warn/10 text-warn"
      : "border-border bg-muted/40 text-muted-foreground";
  return (
    <div className={`flex items-start gap-2 rounded-md border px-3 py-2 text-xs ${cls}`}>
      <span className="mt-0.5 shrink-0">{icon}</span>
      <span>{children}</span>
    </div>
  );
}

function stateKey(state: DefrostLearningStatus["state"]): string {
  return state === "suggestion_ready" ? "suggestionReady" : state === "no_entity" ? "noEntity" : state;
}
function hintKey(state: DefrostLearningStatus["state"]): string {
  if (state === "approved") return "approvedHint";
  if (state === "suggestion_ready") return "suggestionHint";
  return "observingHint";
}
function stateTone(state: DefrostLearningStatus["state"]): "ok" | "info" | "neutral" {
  if (state === "approved") return "ok";
  if (state === "suggestion_ready") return "info";
  return "neutral";
}
