import * as React from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, ClipboardList } from "lucide-react";
import { api } from "@/lib/api";
import type { Incident, IncidentDetail } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { IncidentBadge } from "@/components/incidents/IncidentBadge";
import { incidentStateTone } from "@/lib/incidents";
import { formatDateTime, formatDuration, formatNumber } from "@/lib/utils";

type Filter = "all" | "open" | "closed";

export function IncidentsPage() {
  const { t } = useTranslation("incidents");
  const [filter, setFilter] = React.useState<Filter>("open");
  const [selectedId, setSelectedId] = React.useState<number | null>(null);

  const unitsQuery = useQuery({ queryKey: ["units"], queryFn: api.listUnits });
  const unitName = (id: number | null) =>
    unitsQuery.data?.find((u) => u.id === id)?.name ?? (id == null ? "—" : `#${id}`);

  const incidentsQuery = useQuery({
    queryKey: ["incidents", filter],
    queryFn: () => api.listIncidents({ state: filter }),
    refetchInterval: 15000,
  });

  if (selectedId != null) {
    return <IncidentDetailView id={selectedId} onBack={() => setSelectedId(null)} />;
  }

  const incidents = incidentsQuery.data ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{t("title")}</h1>
          <p className="text-sm text-muted-foreground">{t("subtitle")}</p>
        </div>
        <div role="radiogroup" className="inline-flex rounded-lg border border-border bg-muted/50 p-0.5">
          {(["open", "closed", "all"] as Filter[]).map((f) => (
            <button
              key={f}
              role="radio"
              aria-checked={filter === f}
              onClick={() => setFilter(f)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                filter === f ? "bg-card text-foreground shadow-sm" : "text-muted-foreground"
              }`}
            >
              {t(`filter.${f}`)}
            </button>
          ))}
        </div>
      </div>

      {incidentsQuery.isLoading && <Skeleton className="h-48 w-full rounded-xl" />}

      {incidents.length === 0 && !incidentsQuery.isLoading && (
        <Card className="p-10 text-center text-sm text-muted-foreground">{t("empty")}</Card>
      )}

      {incidents.length > 0 && (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="px-4 py-3 font-medium">{t("col.type")}</th>
                  <th className="px-4 py-3 font-medium">{t("col.unit")}</th>
                  <th className="px-4 py-3 font-medium">{t("col.started")}</th>
                  <th className="px-4 py-3 font-medium">{t("col.duration")}</th>
                  <th className="px-4 py-3 font-medium">{t("col.extreme")}</th>
                  <th className="px-4 py-3 font-medium">{t("col.status")}</th>
                  <th className="px-4 py-3 font-medium">{t("col.documentation")}</th>
                </tr>
              </thead>
              <tbody>
                {incidents.map((inc: Incident) => (
                  <tr
                    key={inc.id}
                    onClick={() => setSelectedId(inc.id)}
                    className="cursor-pointer border-b border-border/60 last:border-0 hover:bg-accent/40"
                  >
                    <td className="px-4 py-2.5"><IncidentBadge type={inc.type} /></td>
                    <td className="px-4 py-2.5">{unitName(inc.storage_unit_id)}</td>
                    <td className="px-4 py-2.5 text-muted-foreground">{formatDateTime(inc.opened_at)}</td>
                    <td className="px-4 py-2.5 tabular-nums">
                      {formatDuration(inc.opened_at, inc.closed_at)}
                    </td>
                    <td className="px-4 py-2.5 tabular-nums">
                      {inc.extreme_value_c != null
                        ? `${formatNumber(inc.extreme_value_c, { maximumFractionDigits: 1 })}°`
                        : "—"}
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge tone={incidentStateTone(inc.state)}>
                        {t(`states.${inc.state}`, { defaultValue: inc.state })}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5">
                      {inc.acknowledged_at && inc.corrective_action ? (
                        <CheckCircle2 className="h-4 w-4 text-ok" aria-label="documented" />
                      ) : (
                        <Badge tone="warn">{t("badge.unacknowledged")}</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

function IncidentDetailView({ id, onBack }: { id: number; onBack: () => void }) {
  const { t } = useTranslation("incidents");
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["incident", id], queryFn: () => api.getIncident(id) });

  const [cause, setCause] = React.useState("");
  const [action, setAction] = React.useState("");
  const [note, setNote] = React.useState("");
  const initialised = React.useRef(false);

  React.useEffect(() => {
    if (query.data && !initialised.current) {
      setCause(query.data.cause ?? "");
      setAction(query.data.corrective_action ?? "");
      setNote(query.data.note ?? "");
      initialised.current = true;
    }
  }, [query.data]);

  const mutation = useMutation({
    mutationFn: (input: Parameters<typeof api.updateIncident>[1]) => api.updateIncident(id, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["incident", id] });
      qc.invalidateQueries({ queryKey: ["incidents"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  if (query.isLoading || !query.data) {
    return <Skeleton className="h-96 w-full rounded-xl" />;
  }
  const inc: IncidentDetail = query.data;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={onBack} aria-label={t("detail.back")}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <IncidentBadge type={inc.type} state={inc.state} size="md" />
        <span className="text-sm text-muted-foreground">{inc.storage_unit_name}</span>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardContent className="grid grid-cols-2 gap-3 pt-5 text-sm">
            <Fact label={t("detail.opened")} value={formatDateTime(inc.opened_at)} />
            <Fact label={t("detail.confirmed")} value={formatDateTime(inc.confirmed_at)} />
            <Fact
              label={t("detail.duration")}
              value={`${formatDuration(inc.opened_at, inc.closed_at)}${inc.closed_at ? "" : " (" + t("detail.ongoing") + ")"}`}
            />
            <Fact
              label={t("detail.extreme")}
              value={inc.extreme_value_c != null ? `${formatNumber(inc.extreme_value_c, { maximumFractionDigits: 1 })}°` : "—"}
            />
            <Fact label={t("detail.limit")} value={inc.limit_value_c != null ? `${inc.limit_value_c}°` : "—"} />
            <Fact label={t("detail.closed")} value={formatDateTime(inc.closed_at)} />
          </CardContent>
        </Card>

        {/* documentation */}
        <Card>
          <CardContent className="flex flex-col gap-3 pt-5">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <ClipboardList className="h-4 w-4" /> {t("detail.documentation")}
            </div>
            {inc.acknowledged_at ? (
              <Badge tone="ok">{t("detail.acknowledged", { user: inc.acknowledged_by ?? "—" })}</Badge>
            ) : (
              <Button
                variant="secondary"
                size="sm"
                className="self-start"
                onClick={() => mutation.mutate({ acknowledge: true })}
              >
                <CheckCircle2 className="h-4 w-4" /> {t("detail.acknowledge")}
              </Button>
            )}
            <Textarea label={t("detail.cause")} value={cause} onChange={setCause} placeholder={t("detail.causePlaceholder")} />
            <Textarea
              label={t("detail.correctiveAction")}
              value={action}
              onChange={setAction}
              placeholder={t("detail.correctiveActionPlaceholder")}
            />
            <Textarea label={t("detail.note")} value={note} onChange={setNote} />
            <Button
              className="self-end"
              disabled={mutation.isPending}
              onClick={() =>
                mutation.mutate({ cause, corrective_action: action, note })
              }
            >
              {mutation.isPending ? t("detail.saving") : t("detail.save")}
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* timeline */}
      <Card>
        <CardContent className="pt-5">
          <div className="mb-2 text-sm font-semibold">{t("detail.timeline")}</div>
          <ol className="flex flex-col gap-2">
            {inc.events.map((e, i) => (
              <li key={i} className="flex items-start gap-3 text-sm">
                <span className="mt-0.5 w-32 shrink-0 text-xs tabular-nums text-muted-foreground">
                  {formatDateTime(e.timestamp)}
                </span>
                <span>
                  {e.kind === "transition" && e.to_state
                    ? `${e.from_state ?? "—"} → ${t(`states.${e.to_state}`, { defaultValue: e.to_state })}`
                    : e.detail ?? e.kind}
                  {e.user ? ` · ${e.user}` : ""}
                </span>
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="font-medium tabular-nums">{value}</div>
    </div>
  );
}

function Textarea({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={2}
        className="rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
    </label>
  );
}
