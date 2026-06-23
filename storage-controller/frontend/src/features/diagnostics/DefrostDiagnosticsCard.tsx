import * as React from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Stethoscope, AlertTriangle, CheckCircle2, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type { DefrostMappingDiagnostic } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { timeAgo } from "@/lib/utils";

export function DefrostDiagnosticsCard() {
  const { t } = useTranslation(["diagnostics", "common"]);
  const query = useQuery({
    queryKey: ["defrost-diagnostics"],
    queryFn: api.getDefrostDiagnostics,
    refetchInterval: 30000,
  });

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-primary/15 text-primary">
          <Stethoscope className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <CardTitle>{t("diagnostics:title")}</CardTitle>
          <p className="text-sm text-muted-foreground">{t("diagnostics:subtitle")}</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => query.refetch()} disabled={query.isFetching}>
          <RefreshCw className={`h-3.5 w-3.5 ${query.isFetching ? "animate-spin" : ""}`} />
          {t("diagnostics:refresh")}
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {!query.data || query.data.mappings.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("diagnostics:noMappings")}</p>
        ) : (
          query.data.mappings.map((m) => <MappingRow key={m.defrost_entity_id} m={m} />)
        )}
      </CardContent>
    </Card>
  );
}

function MappingRow({ m }: { m: DefrostMappingDiagnostic }) {
  const { t } = useTranslation(["diagnostics"]);
  const [showEvents, setShowEvents] = React.useState(false);
  const ok = m.problem === null;

  return (
    <div className="rounded-md border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        {ok ? (
          <CheckCircle2 className="h-4 w-4 text-ok" />
        ) : (
          <AlertTriangle className="h-4 w-4 text-warn" />
        )}
        <span className="font-medium">{m.storage_unit_name}</span>
        <span className="font-mono text-xs text-muted-foreground">{m.defrost_entity_id}</span>
        <Badge tone={ok ? "ok" : "warn"} className="ml-auto">
          {t(`diagnostics:engineState.${stateKey(m.engine_state)}`, {
            defaultValue: m.engine_state,
          })}
        </Badge>
      </div>

      {!ok && (
        <div className="mt-2 flex items-start gap-2 rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{problemText(t, m)}</span>
        </div>
      )}

      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
        <Field label={t("diagnostics:fields.rawState")}>
          <span className="font-mono">{m.raw_state ?? "—"}</span>
        </Field>
        <Field label={t("diagnostics:fields.normalized")}>
          {m.normalized_bool === null
            ? t("diagnostics:boolean.null")
            : m.normalized_bool
              ? t("diagnostics:boolean.true")
              : t("diagnostics:boolean.false")}
          {m.normalization_reason !== "ok" && (
            <span className="text-muted-foreground"> ({m.normalization_reason})</span>
          )}
        </Field>
        <Field label={t("diagnostics:fields.activeCycle")}>
          {m.active_cycle_id != null ? `#${m.active_cycle_id}` : "—"}
        </Field>
        <Field label={t("diagnostics:fields.lastCycle")}>
          {m.last_cycle_started ? timeAgo(m.last_cycle_started) : "—"}
        </Field>
        <Field label={t("diagnostics:fields.lastEvent")}>
          {m.last_event_received ? timeAgo(m.last_event_received) : "—"}
        </Field>
        <Field label={t("diagnostics:fields.lastEngineEval")}>
          {m.last_engine_evaluation ? timeAgo(m.last_engine_evaluation) : "—"}
        </Field>
        {m.value_mapping.configured && (
          <Field label={t("diagnostics:fields.valueMapping")}>
            <span className="font-mono">
              +[{m.value_mapping.active.join(", ")}] −[{m.value_mapping.inactive.join(", ")}]
            </span>
          </Field>
        )}
      </dl>

      <button
        type="button"
        className="mt-2 text-xs text-primary hover:underline"
        onClick={() => setShowEvents((s) => !s)}
      >
        {t("diagnostics:recent.title")}
      </button>
      {showEvents && <RecentEvents entityId={m.defrost_entity_id} />}
    </div>
  );
}

function RecentEvents({ entityId }: { entityId: string }) {
  const { t } = useTranslation(["diagnostics"]);
  const { data } = useQuery({
    queryKey: ["recent-events", entityId],
    queryFn: () => api.getRecentEvents(entityId, 20),
    refetchInterval: 15000,
  });
  if (!data || data.events.length === 0) {
    return <p className="mt-1 text-xs text-muted-foreground">{t("diagnostics:recent.empty")}</p>;
  }
  return (
    <ul className="mt-1 flex flex-col divide-y divide-border rounded-md border border-border">
      {data.events.map((e, i) => (
        <li key={i} className="flex flex-wrap items-center gap-x-3 px-2 py-1.5 text-[11px]">
          <span className="text-muted-foreground">{timeAgo(e.timestamp)}</span>
          <span className="font-mono">
            {e.old_raw ?? "—"} → {e.new_raw ?? "—"}
          </span>
          <span className="text-muted-foreground">
            ({e.normalized_old ?? "—"} → {e.normalized_new ?? "—"})
          </span>
          <span className="ml-auto font-medium">{e.result}</span>
        </li>
      ))}
    </ul>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function stateKey(s: string): string {
  return ["no_cycle", "active", "recovering"].includes(s) ? s : "no_cycle";
}

function problemText(
  t: (k: string, o?: Record<string, unknown>) => string,
  m: DefrostMappingDiagnostic,
): string {
  if (m.problem?.startsWith("normalization_failed")) {
    return t("diagnostics:problem.normalization_failed", { raw: m.raw_state ?? "?" });
  }
  return t(`diagnostics:problem.${m.problem}`, { defaultValue: m.problem ?? "" });
}
