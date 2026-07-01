import * as React from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Mail,
  CalendarClock,
  Plus,
  Pencil,
  Trash2,
  Play,
  Power,
  History,
  Send,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  XCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";
import type { Schedule, ScheduleInput, ScheduleRun, SmtpSettingsInput } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

const SELECT = "h-9 rounded-md border border-input bg-background px-2 text-sm";

export function SchedulesPage() {
  return (
    <div className="flex flex-col gap-5">
      <ScheduleSection />
    </div>
  );
}

// --------------------------------------------------------------------------- //
// SMTP settings
// --------------------------------------------------------------------------- //

export function SmtpSettingsCard() {
  const { t } = useTranslation(["schedules", "common"]);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["email-settings"], queryFn: api.getEmailSettings });
  const [form, setForm] = React.useState<SmtpSettingsInput | null>(null);
  const [password, setPassword] = React.useState("");
  const [testRecipient, setTestRecipient] = React.useState("");
  const [testMsg, setTestMsg] = React.useState<{ ok: boolean; text: string } | null>(null);

  React.useEffect(() => {
    if (q.data && form === null) {
      setForm({
        host: q.data.host, port: q.data.port, security_mode: q.data.security_mode,
        auth_enabled: q.data.auth_enabled, username: q.data.username,
        sender_name: q.data.sender_name, sender_email: q.data.sender_email,
        reply_to: q.data.reply_to, connection_timeout_seconds: q.data.connection_timeout_seconds,
        verify_certificates: q.data.verify_certificates, allow_insecure_plain: q.data.allow_insecure_plain,
        default_to: q.data.default_to, default_cc: q.data.default_cc, default_bcc: q.data.default_bcc,
        max_attachment_bytes: q.data.max_attachment_bytes, site_name: q.data.site_name,
      });
    }
  }, [q.data, form]);

  const save = useMutation({
    mutationFn: () =>
      api.updateEmailSettings({ ...(form as SmtpSettingsInput), password: password || undefined }),
    onSuccess: () => {
      setPassword("");
      qc.invalidateQueries({ queryKey: ["email-settings"] });
    },
  });
  const clearPw = useMutation({
    mutationFn: () => api.updateEmailSettings({ ...(form as SmtpSettingsInput), clear_password: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["email-settings"] }),
  });
  const testConn = useMutation({
    mutationFn: () => save.mutateAsync().then(() => api.testSmtpConnection()),
    onSuccess: (r) => {
      setTestMsg({ ok: r.ok, text: r.ok ? t("schedules:smtp.testConnOk") : r.message || t("schedules:smtp.testFailed") });
      qc.invalidateQueries({ queryKey: ["email-settings"] });
    },
  });
  const testEmail = useMutation({
    mutationFn: () => save.mutateAsync().then(() => api.sendTestEmail(testRecipient)),
    onSuccess: (r) =>
      setTestMsg({ ok: r.ok, text: r.ok ? t("schedules:smtp.testEmailOk") : r.message || t("schedules:smtp.testFailed") }),
  });

  if (!form || !q.data) return null;
  const set = (patch: Partial<SmtpSettingsInput>) => setForm({ ...form, ...patch });
  const csv = (v: string[]) => v.join(", ");
  const parseCsv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-primary/15 text-primary">
          <Mail className="h-5 w-5" />
        </div>
        <div>
          <CardTitle>{t("schedules:smtp.title")}</CardTitle>
          <p className="text-sm text-muted-foreground">{t("schedules:smtp.subtitle")}</p>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t("schedules:smtp.host")}>
            <Input value={form.host ?? ""} onChange={(e) => set({ host: e.target.value })} />
          </Field>
          <Field label={t("schedules:smtp.port")}>
            <Input type="number" value={form.port} onChange={(e) => set({ port: Number(e.target.value) })} />
          </Field>
          <Field label={t("schedules:smtp.security")}>
            <select className={SELECT} value={form.security_mode}
              onChange={(e) => set({ security_mode: e.target.value })}>
              <option value="starttls">STARTTLS (587)</option>
              <option value="implicit_tls">Implicit TLS (465)</option>
              <option value="plain">{t("schedules:smtp.plain")}</option>
            </select>
          </Field>
        </div>

        {form.security_mode === "plain" && (
          <p className="rounded-md bg-warn/10 px-3 py-2 text-xs text-warn">
            {t("schedules:smtp.plainWarning")}
          </p>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.auth_enabled}
              onChange={(e) => set({ auth_enabled: e.target.checked })} />
            {t("schedules:smtp.authEnabled")}
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.verify_certificates}
              onChange={(e) => set({ verify_certificates: e.target.checked })} />
            {t("schedules:smtp.verifyCerts")}
          </label>
        </div>

        {form.auth_enabled && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("schedules:smtp.username")}>
              <Input value={form.username ?? ""} onChange={(e) => set({ username: e.target.value })} />
            </Field>
            <Field label={t("schedules:smtp.password")}>
              <div className="flex gap-2">
                <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                  placeholder={q.data.password_configured ? t("schedules:smtp.passwordSet") : ""} />
                {q.data.password_configured && (
                  <Button variant="outline" size="sm" type="button" onClick={() => clearPw.mutate()}>
                    {t("schedules:smtp.clear")}
                  </Button>
                )}
              </div>
            </Field>
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("schedules:smtp.senderName")}>
            <Input value={form.sender_name ?? ""} onChange={(e) => set({ sender_name: e.target.value })} />
          </Field>
          <Field label={t("schedules:smtp.senderEmail")}>
            <Input value={form.sender_email ?? ""} onChange={(e) => set({ sender_email: e.target.value })} />
          </Field>
          <Field label={t("schedules:smtp.replyTo")}>
            <Input value={form.reply_to ?? ""} onChange={(e) => set({ reply_to: e.target.value })} />
          </Field>
          <Field label={t("schedules:smtp.siteName")}>
            <Input value={form.site_name ?? ""} onChange={(e) => set({ site_name: e.target.value })} />
          </Field>
        </div>

        <Field label={t("schedules:smtp.defaultTo")}>
          <Input value={csv(form.default_to)} onChange={(e) => set({ default_to: parseCsv(e.target.value) })}
            placeholder="ops@example.com, qa@example.com" />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("schedules:smtp.defaultCc")}>
            <Input value={csv(form.default_cc)} onChange={(e) => set({ default_cc: parseCsv(e.target.value) })} />
          </Field>
          <Field label={t("schedules:smtp.defaultBcc")}>
            <Input value={csv(form.default_bcc)} onChange={(e) => set({ default_bcc: parseCsv(e.target.value) })} />
          </Field>
        </div>

        {q.data.last_test_at && (
          <p className="text-xs text-muted-foreground">
            {t("schedules:smtp.lastTest")}: {new Date(q.data.last_test_at).toLocaleString()} —{" "}
            {q.data.last_test_ok ? t("schedules:smtp.ok") : q.data.last_test_error}
          </p>
        )}
        {testMsg && (
          <p className={`text-sm ${testMsg.ok ? "text-ok" : "text-danger"}`}>{testMsg.text}</p>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {t("common:actions.save")}
          </Button>
          <Button variant="outline" onClick={() => testConn.mutate()} disabled={testConn.isPending}>
            <RefreshCw className={`h-4 w-4 ${testConn.isPending ? "animate-spin" : ""}`} />
            {t("schedules:smtp.testConnection")}
          </Button>
          <div className="ml-auto flex items-center gap-2">
            <Input className="w-56" placeholder={t("schedules:smtp.testRecipient")}
              value={testRecipient} onChange={(e) => setTestRecipient(e.target.value)} />
            <Button variant="outline" onClick={() => testEmail.mutate()}
              disabled={testEmail.isPending || !testRecipient}>
              <Send className="h-4 w-4" /> {t("schedules:smtp.sendTest")}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// --------------------------------------------------------------------------- //
// Schedules
// --------------------------------------------------------------------------- //

function ScheduleSection() {
  const { t } = useTranslation(["schedules"]);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["schedules"], queryFn: api.listSchedules });
  const [editing, setEditing] = React.useState<Schedule | null | undefined>(undefined);
  const [historyFor, setHistoryFor] = React.useState<Schedule | null>(null);
  const invalidate = () => qc.invalidateQueries({ queryKey: ["schedules"] });

  const del = useMutation({ mutationFn: api.deleteSchedule, onSuccess: invalidate });
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      enabled ? api.disableSchedule(id) : api.enableSchedule(id),
    onSuccess: invalidate,
  });
  const runNow = useMutation({
    mutationFn: ({ id, send }: { id: number; send: boolean }) => api.runScheduleNow(id, send),
    onSuccess: invalidate,
  });

  const schedules = q.data ?? [];
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-primary/15 text-primary">
            <CalendarClock className="h-5 w-5" />
          </div>
          <div>
            <CardTitle>{t("schedules:list.title")}</CardTitle>
            <p className="text-sm text-muted-foreground">{t("schedules:list.subtitle")}</p>
          </div>
        </div>
        <Button onClick={() => setEditing(null)}>
          <Plus className="h-4 w-4" /> {t("schedules:list.new")}
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {schedules.length === 0 && (
          <p className="py-6 text-center text-sm text-muted-foreground">{t("schedules:list.empty")}</p>
        )}
        {schedules.map((s) => (
          <div key={s.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border border-border p-3">
            <div className="min-w-[160px]">
              <div className="flex items-center gap-2 font-medium">
                {s.name}
                <Badge tone={s.enabled ? "ok" : "neutral"}>
                  {s.enabled ? t("schedules:enabled") : t("schedules:disabled")}
                </Badge>
              </div>
              <div className="text-xs text-muted-foreground">
                {t("schedules:monthlyOn", { day: s.run_day, time: s.run_time })} · {s.timezone}
              </div>
            </div>
            <div className="text-xs text-muted-foreground">
              <div>{t("schedules:nextRun")}: {formatDateTime(s.next_run_utc)}</div>
              <div>
                {t("schedules:recipients")}: {s.recipient_count} · {s.attachment_formats.join(", ").toUpperCase()}
                {" · "}{s.locale.toUpperCase()}
              </div>
            </div>
            {s.last_result && <ResultBadge state={s.last_result} />}
            <div className="ml-auto flex items-center gap-1">
              <Button variant="ghost" size="sm" title={t("schedules:runNow")}
                onClick={() => runNow.mutate({ id: s.id, send: true })} disabled={runNow.isPending}>
                <Play className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="sm" title={t("schedules:history")}
                onClick={() => setHistoryFor(s)}>
                <History className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="sm" title={s.enabled ? t("schedules:disable") : t("schedules:enable")}
                onClick={() => toggle.mutate({ id: s.id, enabled: s.enabled })}>
                <Power className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setEditing(s)}>
                <Pencil className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="sm"
                onClick={() => confirm(t("schedules:confirmDelete", { name: s.name })) && del.mutate(s.id)}>
                <Trash2 className="h-4 w-4 text-danger" />
              </Button>
            </div>
            <p className="w-full text-xs text-muted-foreground">
              {t("schedules:runNowHint", { period: s.run_now_period })}
            </p>
          </div>
        ))}
      </CardContent>

      {editing !== undefined && (
        <ScheduleEditor schedule={editing} onClose={() => setEditing(undefined)}
          onSaved={() => { setEditing(undefined); invalidate(); }} />
      )}
      {historyFor && <RunHistory schedule={historyFor} onClose={() => setHistoryFor(null)} />}
    </Card>
  );
}

function ResultBadge({ state }: { state: string }) {
  const { t } = useTranslation(["schedules"]);
  const tone =
    state === "completed" ? "ok" : state === "partially_failed" ? "warn"
      : state === "failed" ? "danger" : "neutral";
  return <Badge tone={tone as never}>{t(`schedules:state.${state}`, state)}</Badge>;
}

function ScheduleEditor({
  schedule, onClose, onSaved,
}: { schedule: Schedule | null; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation(["schedules", "common"]);
  const units = useQuery({ queryKey: ["units"], queryFn: api.listUnits });
  const [err, setErr] = React.useState<string | null>(null);
  const [f, setF] = React.useState<ScheduleInput>(() => ({
    name: schedule?.name ?? "",
    enabled: schedule?.enabled ?? true,
    storage_unit_ids: schedule?.storage_unit_ids ?? [],
    locale: schedule?.locale ?? "de",
    timezone: schedule?.timezone ?? "Europe/Berlin",
    detail_level: schedule?.detail_level ?? "standard",
    recipients_to: schedule?.recipients_to ?? [],
    recipients_cc: schedule?.recipients_cc ?? [],
    recipients_bcc: schedule?.recipients_bcc ?? [],
    attachment_formats: schedule?.attachment_formats ?? ["pdf"],
    run_day: schedule?.run_day ?? 1,
    run_time: schedule?.run_time ?? "06:00",
    catch_up_mode: schedule?.catch_up_mode ?? "one",
  }));
  const set = (p: Partial<ScheduleInput>) => setF({ ...f, ...p });
  const csv = (v: string[]) => v.join(", ");
  const parse = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

  const save = useMutation({
    mutationFn: () => (schedule ? api.updateSchedule(schedule.id, f) : api.createSchedule(f)),
    onSuccess: onSaved,
    onError: () => setErr(t("schedules:editor.saveError")),
  });

  const toggleFormat = (fmt: string) =>
    set({
      attachment_formats: f.attachment_formats.includes(fmt)
        ? f.attachment_formats.filter((x) => x !== fmt)
        : [...f.attachment_formats, fmt],
    });

  return (
    <Modal open onClose={onClose} title={schedule ? t("schedules:editor.edit") : t("schedules:editor.create")}>
      <div className="flex flex-col gap-3">
        <Field label={t("schedules:editor.name")}>
          <Input value={f.name} onChange={(e) => set({ name: e.target.value })} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("schedules:editor.runDay")}>
            <Input type="number" min={1} max={28} value={f.run_day}
              onChange={(e) => set({ run_day: Number(e.target.value) })} />
          </Field>
          <Field label={t("schedules:editor.runTime")}>
            <Input value={f.run_time} onChange={(e) => set({ run_time: e.target.value })} placeholder="06:00" />
          </Field>
          <Field label={t("schedules:editor.timezone")}>
            <Input value={f.timezone} onChange={(e) => set({ timezone: e.target.value })} />
          </Field>
          <Field label={t("schedules:editor.locale")}>
            <select className={SELECT} value={f.locale} onChange={(e) => set({ locale: e.target.value })}>
              <option value="de">Deutsch</option>
              <option value="en">English</option>
            </select>
          </Field>
        </div>

        <Field label={t("schedules:editor.units")}>
          <div className="flex flex-wrap gap-2">
            {(units.data ?? []).map((u) => (
              <label key={u.id} className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-sm">
                <input type="checkbox" checked={f.storage_unit_ids.includes(u.id)}
                  onChange={(e) =>
                    set({
                      storage_unit_ids: e.target.checked
                        ? [...f.storage_unit_ids, u.id]
                        : f.storage_unit_ids.filter((x) => x !== u.id),
                    })} />
                {u.name}
              </label>
            ))}
          </div>
        </Field>

        <Field label={t("schedules:editor.recipientsTo")}>
          <Input value={csv(f.recipients_to)} onChange={(e) => set({ recipients_to: parse(e.target.value) })}
            placeholder="ops@example.com" />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("schedules:editor.cc")}>
            <Input value={csv(f.recipients_cc)} onChange={(e) => set({ recipients_cc: parse(e.target.value) })} />
          </Field>
          <Field label={t("schedules:editor.bcc")}>
            <Input value={csv(f.recipients_bcc)} onChange={(e) => set({ recipients_bcc: parse(e.target.value) })} />
          </Field>
        </div>

        <Field label={t("schedules:editor.formats")}>
          <div className="flex gap-3">
            {["pdf", "csv", "json"].map((fmt) => (
              <label key={fmt} className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={f.attachment_formats.includes(fmt)}
                  disabled={fmt === "pdf"} onChange={() => toggleFormat(fmt)} />
                {fmt.toUpperCase()}
              </label>
            ))}
          </div>
        </Field>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("schedules:editor.catchUp")}>
            <select className={SELECT} value={f.catch_up_mode}
              onChange={(e) => set({ catch_up_mode: e.target.value })}>
              <option value="one">{t("schedules:editor.catchUpOne")}</option>
              <option value="none">{t("schedules:editor.catchUpNone")}</option>
            </select>
          </Field>
          <label className="mt-6 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={f.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
            {t("schedules:enabled")}
          </label>
        </div>

        {err && <p className="text-sm text-danger">{err}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={onClose}>{t("common:actions.cancel")}</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !f.name}>
            {t("common:actions.save")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function RunHistory({ schedule, onClose }: { schedule: Schedule; onClose: () => void }) {
  const { t } = useTranslation(["schedules"]);
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["schedule-runs", schedule.id],
    queryFn: () => api.listScheduleRuns(schedule.id),
    refetchInterval: 4000,
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["schedule-runs", schedule.id] });
  const resend = useMutation({ mutationFn: api.resendDelivery, onSuccess: refresh });
  const send = useMutation({ mutationFn: api.sendExistingReport, onSuccess: refresh });
  const cancel = useMutation({ mutationFn: api.cancelRun, onSuccess: refresh });

  return (
    <Modal open onClose={onClose} title={`${t("schedules:history")} — ${schedule.name}`}>
      <div className="flex flex-col gap-2">
        {(q.data ?? []).length === 0 && (
          <p className="py-4 text-center text-sm text-muted-foreground">{t("schedules:noRuns")}</p>
        )}
        {(q.data ?? []).map((r: ScheduleRun) => (
          <div key={r.id} className="rounded-md border border-border p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{r.period_label}</span>
              <Badge tone="neutral">{t(`schedules:trigger.${r.trigger}`, r.trigger)}</Badge>
              <RunStateBadge state={r.state} />
              <span className="ml-auto text-xs text-muted-foreground">
                {r.started_at ? formatDateTime(r.started_at) : ""}
              </span>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span>{t("schedules:run.generation")}: {r.report_status ?? "—"}</span>
              {r.report_uuid && (
                <a className="text-primary underline" href={`api/reports/${r.report_id}/pdf`} target="_blank" rel="noreferrer">
                  {t("schedules:run.downloadPdf")}
                </a>
              )}
              {r.delivery && (
                <span>
                  {t("schedules:run.delivery")}: {t(`schedules:dstate.${r.delivery.state}`, r.delivery.state)}
                  {r.delivery.attempt_count > 0 && ` (${r.delivery.attempt_count}×)`}
                </span>
              )}
              {r.delivery?.recipients_masked?.length ? (
                <span>→ {r.delivery.recipients_masked.join(", ")}</span>
              ) : null}
            </div>
            {(r.generation_error || r.delivery?.last_error) && (
              <p className="mt-1 text-xs text-danger">{r.generation_error || r.delivery?.last_error}</p>
            )}
            <div className="mt-2 flex gap-2">
              {r.report_status === "completed" && (!r.delivery || r.delivery.state !== "completed") && (
                <Button size="sm" variant="outline" onClick={() => send.mutate(r.id)}>
                  <Send className="h-3.5 w-3.5" /> {t("schedules:run.send")}
                </Button>
              )}
              {r.delivery && ["failed", "partially_failed", "completed"].includes(r.delivery.state) && (
                <Button size="sm" variant="outline" onClick={() => resend.mutate(r.id)}>
                  <RefreshCw className="h-3.5 w-3.5" /> {t("schedules:run.resend")}
                </Button>
              )}
              {["pending", "sending"].includes(r.state) && (
                <Button size="sm" variant="ghost" onClick={() => cancel.mutate(r.id)}>
                  {t("schedules:run.cancel")}
                </Button>
              )}
            </div>
          </div>
        ))}
      </div>
    </Modal>
  );
}

function RunStateBadge({ state }: { state: string }) {
  const { t } = useTranslation(["schedules"]);
  const map: Record<string, { tone: string; Icon: typeof CheckCircle2 }> = {
    completed: { tone: "ok", Icon: CheckCircle2 },
    partially_failed: { tone: "warn", Icon: AlertTriangle },
    failed: { tone: "danger", Icon: XCircle },
  };
  const m = map[state];
  return (
    <Badge tone={(m?.tone ?? "neutral") as never}>
      {m && <m.Icon className="mr-1 inline h-3 w-3" />}
      {t(`schedules:state.${state}`, state)}
    </Badge>
  );
}
