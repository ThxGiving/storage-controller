import * as React from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Boxes, Database, Server, Activity } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { StatusPill } from "@/components/layout/StatusPill";
import { Sparkline } from "@/components/Sparkline";
import { formatDateTime, formatNumber } from "@/lib/utils";

export function Overview() {
  const { t } = useTranslation("dashboard");
  const statusQuery = useQuery({
    queryKey: ["status"],
    queryFn: api.getStatus,
    refetchInterval: 10000,
  });

  const s = statusQuery.data;
  const ha = s?.home_assistant;

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-semibold">{t("title")}</h1>
        <p className="text-sm text-muted-foreground">{t("subtitle")}</p>
      </div>

      <Card className="gradient-frost overflow-hidden">
        <CardContent className="flex flex-wrap items-center justify-between gap-4 pt-5">
          <div className="flex items-center gap-4">
            <div className="grid h-12 w-12 place-items-center rounded-xl bg-primary/15 text-primary">
              <Server className="h-6 w-6" />
            </div>
            <div>
              <div className="text-sm text-muted-foreground">{t("homeAssistant")}</div>
              <div className="mt-1">
                {ha ? <StatusPill status={ha.status} /> : <span className="text-sm">…</span>}
              </div>
              {ha?.detail && (
                <div className="mt-1 text-xs text-muted-foreground">{ha.detail}</div>
              )}
            </div>
          </div>
          <div className="flex gap-6 text-sm">
            <Metric label={t("entities")} value={formatNumber(ha?.entity_count)} />
            <Metric label={t("lastEvent")} value={formatDateTime(ha?.last_event_at)} />
            <Metric label={t("reconnects")} value={formatNumber(ha?.reconnect_attempts)} />
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={<Boxes className="h-5 w-5" />}
          label={t("storageUnits")}
          value={formatNumber(s?.storage_unit_count)}
        />
        <StatCard
          icon={<Database className="h-5 w-5" />}
          label={t("database")}
          value={s?.database_ok ? t("ok") : "—"}
          tone={s?.database_ok ? "ok" : "neutral"}
        />
        <StatCard
          icon={<Activity className="h-5 w-5" />}
          label={t("version")}
          value={s?.version ?? "—"}
        />
        <Card>
          <CardContent className="pt-5">
            <div className="mb-1 text-xs text-muted-foreground">{t("trendPreview")}</div>
            <Sparkline data={[6.1, 6.0, 6.3, 6.5, 6.2, 5.9, 6.0]} upper={8} lower={0} />
          </CardContent>
        </Card>
      </div>

      <p className="text-xs text-muted-foreground">{t("phaseNote")}</p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-medium tabular-nums">{value}</div>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  tone = "neutral",
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  tone?: "neutral" | "ok";
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 pt-5">
        <div
          className={`grid h-11 w-11 place-items-center rounded-xl ${
            tone === "ok" ? "bg-ok/15 text-ok" : "bg-accent text-muted-foreground"
          }`}
        >
          {icon}
        </div>
        <div>
          <div className="text-xs text-muted-foreground">{label}</div>
          <div className="text-xl font-semibold tabular-nums">{value}</div>
        </div>
      </CardContent>
    </Card>
  );
}
