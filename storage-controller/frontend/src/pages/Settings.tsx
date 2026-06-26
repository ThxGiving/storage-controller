import * as React from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Languages, Palette, Clock, Gauge, Database, HardDrive, RefreshCw } from "lucide-react";
import { SmtpSettingsCard } from "./Schedules";
import { api } from "@/lib/api";
import type { AppSettings } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { formatBytes, formatDateTime } from "@/lib/utils";
import { getStoredPreference, setLanguagePreference } from "@/i18n";
import { SUPPORTED_LOCALES, SYSTEM_LANGUAGE } from "@/i18n/locales";
import { DefrostDiagnosticsCard } from "@/features/diagnostics/DefrostDiagnosticsCard";
import { BackupRestoreCard } from "@/features/backup/BackupRestoreCard";

export function SettingsPage() {
  const { t } = useTranslation(["settings", "common"]);
  const qc = useQueryClient();
  const [pref, setPref] = React.useState(getStoredPreference());

  const settingsQuery = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const maintenanceQuery = useQuery({
    queryKey: ["maintenance"],
    queryFn: api.getMaintenanceStatus,
    refetchInterval: 30000,
  });

  const [form, setForm] = React.useState<Partial<AppSettings>>({});
  React.useEffect(() => {
    if (settingsQuery.data) setForm(settingsQuery.data);
  }, [settingsQuery.data]);

  const save = useMutation({
    mutationFn: (input: Partial<AppSettings>) => api.updateSettings(input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  const runMaintenance = useMutation({
    mutationFn: () => api.runMaintenance(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["maintenance"] }),
  });

  const set = (k: keyof AppSettings, v: string | number) =>
    setForm((f) => ({ ...f, [k]: v }));

  const s = settingsQuery.data;
  const m = maintenanceQuery.data;

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-semibold">{t("settings:title")}</h1>
        <p className="text-sm text-muted-foreground">{t("settings:subtitle")}</p>
      </div>

      {/* Email / SMTP */}
      <SmtpSettingsCard />

      {/* Language */}
      <Section icon={<Languages className="h-5 w-5" />} title={t("settings:language")} hint={t("settings:languageHint")}>
        <select
          value={pref}
          onChange={(e) => {
            setPref(e.target.value);
            setLanguagePreference(e.target.value);
          }}
          className="h-10 w-full max-w-xs rounded-md border border-input bg-background px-3 text-sm"
        >
          <option value={SYSTEM_LANGUAGE}>{t("settings:languageSystem")}</option>
          {SUPPORTED_LOCALES.map((l) => (
            <option key={l.code} value={l.code}>{l.nativeName}</option>
          ))}
        </select>
      </Section>

      {/* Timezone */}
      <Section icon={<Clock className="h-5 w-5" />} title={t("settings:timezone")} hint={t("settings:timezoneHint")}>
        <div className="flex flex-wrap items-center gap-3">
          <Input
            value={form.timezone ?? ""}
            onChange={(e) => set("timezone", e.target.value)}
            className="max-w-xs"
            placeholder="Europe/Berlin"
          />
          {s && <Badge tone="info">{s.timezone} · {s.timezone_label}</Badge>}
        </div>
      </Section>

      {/* Recording limits */}
      <Section icon={<Gauge className="h-5 w-5" />} title={t("settings:recording")} hint={t("settings:recordingHint")}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("settings:heartbeat")}>
            <Input type="number" value={form.heartbeat_interval_seconds ?? ""} onChange={(e) => set("heartbeat_interval_seconds", Number(e.target.value))} />
          </Field>
          <Field label={t("settings:minDelta")}>
            <Input type="number" step="0.1" value={form.min_temp_delta_c ?? ""} onChange={(e) => set("min_temp_delta_c", Number(e.target.value))} />
          </Field>
        </div>
      </Section>

      {/* Retention */}
      <Section icon={<Database className="h-5 w-5" />} title={t("settings:retention")} hint={t("settings:retentionHint")}>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label={t("settings:retentionRaw")}>
            <Input type="number" value={form.retention_raw_days ?? ""} onChange={(e) => set("retention_raw_days", Number(e.target.value))} />
          </Field>
          <Field label={t("settings:retentionAgg15")}>
            <Input type="number" value={form.retention_agg15_days ?? ""} onChange={(e) => set("retention_agg15_days", Number(e.target.value))} />
          </Field>
          <Field label={t("settings:retentionAggHourly")}>
            <Input type="number" value={form.retention_agg_hourly_days ?? ""} onChange={(e) => set("retention_agg_hourly_days", Number(e.target.value))} />
          </Field>
        </div>
      </Section>

      {/* Storage budget + usage */}
      <Section icon={<HardDrive className="h-5 w-5" />} title={t("settings:storage")}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("settings:budget")}>
            <Input
              type="number"
              value={form.storage_budget_bytes != null ? Math.round(form.storage_budget_bytes / 1024 / 1024) : ""}
              onChange={(e) => set("storage_budget_bytes", Number(e.target.value) * 1024 * 1024)}
            />
          </Field>
          <div className="grid grid-cols-3 gap-2">
            <Field label="⚠︎ %"><Input type="number" value={form.warning_pct ?? ""} onChange={(e) => set("warning_pct", Number(e.target.value))} /></Field>
            <Field label="◆ %"><Input type="number" value={form.critical_pct ?? ""} onChange={(e) => set("critical_pct", Number(e.target.value))} /></Field>
            <Field label="‼ %"><Input type="number" value={form.emergency_pct ?? ""} onChange={(e) => set("emergency_pct", Number(e.target.value))} /></Field>
          </div>
        </div>

        {m && (
          <div className="mt-4 flex flex-col gap-2">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">{t("settings:usage")}</span>
              <span className="flex items-center gap-2">
                <Badge tone={levelTone(m.level)}>{t(`settings:level.${m.level}`)}</Badge>
                <span className="tabular-nums text-muted-foreground">
                  {formatBytes(m.app_total_bytes)} / {formatBytes(m.budget_bytes)} ({m.budget_used_percent}%)
                </span>
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={`h-full ${levelBar(m.level)}`}
                style={{ width: `${Math.min(100, m.budget_used_percent)}%` }}
              />
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              {m.categories.map((c) => (
                <span key={c.name}>{t(`settings:category.${c.name}`, { defaultValue: c.name })}: {formatBytes(c.bytes)}</span>
              ))}
              <span>{t("settings:free")}: {formatBytes(m.free_bytes)} ({m.free_percent}%)</span>
            </div>
            <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
              <span>{t("settings:lastRun")}: {formatDateTime(m.last_run)}</span>
              <span>{t("settings:nextRun")}: {formatDateTime(m.next_run)}</span>
              <Button size="sm" variant="outline" onClick={() => runMaintenance.mutate()} disabled={runMaintenance.isPending}>
                <RefreshCw className={`h-3.5 w-3.5 ${runMaintenance.isPending ? "animate-spin" : ""}`} />
                {runMaintenance.isPending ? t("settings:running") : t("settings:runNow")}
              </Button>
            </div>
          </div>
        )}
      </Section>

      <div className="flex items-center justify-end gap-3">
        {save.isSuccess && <span className="text-sm text-ok">{t("settings:saved")}</span>}
        <Button onClick={() => save.mutate(form)} disabled={save.isPending}>
          {save.isPending ? t("settings:saving") : t("settings:save")}
        </Button>
      </div>

      <BackupRestoreCard />

      <DefrostDiagnosticsCard />

      <Section icon={<Palette className="h-5 w-5" />} title={t("settings:about")}>
        <p className="text-sm text-muted-foreground">
          {t("settings:demoData")}: {t("settings:demoHint")}
        </p>
      </Section>
    </div>
  );
}

function levelTone(level: string): "ok" | "warn" | "danger" | "neutral" {
  return level === "emergency" || level === "critical" ? "danger" : level === "warning" ? "warn" : "ok";
}
function levelBar(level: string): string {
  return level === "emergency" || level === "critical" ? "bg-danger" : level === "warning" ? "bg-warn" : "bg-ok";
}

function Section({
  icon,
  title,
  hint,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-primary/15 text-primary">{icon}</div>
        <div>
          <CardTitle>{title}</CardTitle>
          {hint && <p className="text-sm text-muted-foreground">{hint}</p>}
        </div>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}
