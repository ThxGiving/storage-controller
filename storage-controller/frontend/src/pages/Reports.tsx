import * as React from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, FileDown, Trash2, Eye, Sparkles, Image as ImageIcon } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { Report, ReportBranding, ReportCreate, ReportDetailLevel } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Modal } from "@/components/ui/modal";

const DETAILS: ReportDetailLevel[] = ["compact", "standard", "detailed"];
const now = new Date();

export function ReportsPage() {
  const { t, i18n } = useTranslation(["reports", "common"]);
  const qc = useQueryClient();

  const units = useQuery({ queryKey: ["units"], queryFn: api.listUnits });
  const reports = useQuery({
    queryKey: ["reports"],
    queryFn: api.listReports,
    refetchInterval: 5000,
  });

  const [month, setMonth] = React.useState(now.getMonth() + 1);
  const [year, setYear] = React.useState(now.getFullYear());
  const [selected, setSelected] = React.useState<number[]>([]);
  const [locale, setLocale] = React.useState(i18n.language.startsWith("de") ? "de" : "en");
  const [detail, setDetail] = React.useState<ReportDetailLevel>("standard");
  const [preview, setPreview] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (units.data && selected.length === 0) {
      setSelected(units.data.filter((u) => u.report_enabled !== false).map((u) => u.id));
    }
  }, [units.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const body = (allow = false): ReportCreate => ({
    year,
    month,
    storage_unit_ids: selected,
    locale,
    detail_level: detail,
    allow_duplicate: allow,
  });

  const previewMut = useMutation({
    mutationFn: () => api.previewReport(body()),
    onSuccess: (r) => setPreview(r.html),
    onError: (e) => setError((e as Error).message),
  });

  const createMut = useMutation({
    mutationFn: (allow: boolean) => api.createReport(body(allow)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["reports"] }),
    onError: async (e) => {
      if (e instanceof ApiError && e.code === "duplicate_report") {
        if (window.confirm(t("reports:duplicate"))) createMut.mutate(true);
      } else {
        setError((e as Error).message);
      }
    },
  });

  const del = useMutation({
    mutationFn: (id: number) => api.deleteReport(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["reports"] }),
  });

  const monthName = (m: number) => t(`reports:months.${m}`);
  const canGenerate = selected.length > 0 && !createMut.isPending;

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-semibold">{t("reports:title")}</h1>
        <p className="text-sm text-muted-foreground">{t("reports:subtitle")}</p>
      </div>

      {/* Config */}
      <Card>
        <CardHeader className="flex-row items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-primary/15 text-primary">
            <FileText className="h-5 w-5" />
          </div>
          <CardTitle>{t("reports:config.title")}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid gap-3 sm:grid-cols-4">
            <Field label={t("reports:config.month")}>
              <select className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" value={month} onChange={(e) => setMonth(Number(e.target.value))}>
                {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                  <option key={m} value={m}>{monthName(m)}</option>
                ))}
              </select>
            </Field>
            <Field label={t("reports:config.year")}>
              <Input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} />
            </Field>
            <Field label={t("reports:config.locale")}>
              <select className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" value={locale} onChange={(e) => setLocale(e.target.value)}>
                <option value="en">English</option>
                <option value="de">Deutsch</option>
              </select>
            </Field>
            <Field label={t("reports:config.detail")}>
              <select className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" value={detail} onChange={(e) => setDetail(e.target.value as ReportDetailLevel)}>
                {DETAILS.map((d) => <option key={d} value={d}>{t(`reports:detail.${d}`)}</option>)}
              </select>
            </Field>
          </div>

          <div>
            <Label>{t("reports:config.units")}</Label>
            <div className="mt-1.5 flex flex-wrap gap-2">
              {units.data?.map((u) => {
                const on = selected.includes(u.id);
                return (
                  <button
                    key={u.id}
                    type="button"
                    onClick={() =>
                      setSelected((s) => (on ? s.filter((x) => x !== u.id) : [...s, u.id]))
                    }
                    className={`rounded-full border px-3 py-1 text-xs ${
                      on ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground"
                    }`}
                  >
                    {u.name}
                  </button>
                );
              })}
            </div>
            {selected.length === 0 && (
              <p className="mt-1 text-xs text-danger">{t("reports:config.noUnits")}</p>
            )}
          </div>

          {error && (
            <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => previewMut.mutate()} disabled={selected.length === 0 || previewMut.isPending}>
              <Eye className="h-4 w-4" /> {t("reports:config.preview")}
            </Button>
            <Button onClick={() => createMut.mutate(false)} disabled={!canGenerate}>
              <Sparkles className="h-4 w-4" />
              {createMut.isPending ? t("reports:config.generating") : t("reports:config.generate")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* List */}
      <Card>
        <CardHeader><CardTitle>{t("reports:list.title")}</CardTitle></CardHeader>
        <CardContent>
          {!reports.data || reports.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("reports:list.empty")}</p>
          ) : (
            <div className="flex flex-col divide-y divide-border">
              {reports.data.map((r) => (
                <ReportRow key={r.id} r={r} monthName={monthName} onDelete={(id) => {
                  if (window.confirm(t("reports:list.confirmDelete"))) del.mutate(id);
                }} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <BrandingCard />

      <Modal open={preview !== null} onClose={() => setPreview(null)} title={t("reports:previewTitle")}>
        <iframe title="preview" className="h-[70vh] w-full rounded border border-border bg-white" srcDoc={preview ?? ""} />
      </Modal>
    </div>
  );
}

function ReportRow({
  r,
  monthName,
  onDelete,
}: {
  r: Report;
  monthName: (m: number) => string;
  onDelete: (id: number) => void;
}) {
  const { t } = useTranslation(["reports"]);
  const tone = r.status === "completed" ? "ok" : r.status === "failed" ? "danger" : "warn";
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5 text-sm">
      <span className="font-medium">{monthName(r.period_month)} {r.period_year}</span>
      <Badge tone={tone}>{t(`reports:status.${r.status}`)}</Badge>
      <span className="text-xs uppercase text-muted-foreground">{r.locale} · {t(`reports:detail.${r.detail_level}`)}</span>
      {r.checksum_sha256 && (
        <span className="font-mono text-[11px] text-muted-foreground" title={r.checksum_sha256}>
          {t("reports:list.checksum")}: {r.checksum_sha256.slice(0, 10)}…
        </span>
      )}
      {r.status === "failed" && <span className="text-xs text-danger">{t("reports:failed")}</span>}
      <span className="ml-auto flex items-center gap-1">
        {r.status === "completed" && (["pdf", "csv", "json"] as const).map((fmt) =>
          (fmt === "pdf" ? r.has_pdf : fmt === "csv" ? r.has_csv : r.has_json) ? (
            <a
              key={fmt}
              href={api.reportDownloadUrl(r.id, fmt)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
            >
              <FileDown className="h-3.5 w-3.5" /> {fmt.toUpperCase()}
            </a>
          ) : null,
        )}
        <Button variant="ghost" size="icon" onClick={() => onDelete(r.id)} aria-label={t("reports:list.delete")}>
          <Trash2 className="h-4 w-4 text-danger" />
        </Button>
      </span>
    </div>
  );
}

function BrandingCard() {
  const { t } = useTranslation(["reports"]);
  const qc = useQueryClient();
  const branding = useQuery({ queryKey: ["report-branding"], queryFn: api.getReportBranding });
  const [form, setForm] = React.useState<Partial<ReportBranding>>({});
  const [sigs, setSigs] = React.useState("");
  const [saved, setSaved] = React.useState(false);

  React.useEffect(() => {
    if (branding.data) {
      setForm(branding.data);
      setSigs((branding.data.signature_labels ?? []).join(", "));
    }
  }, [branding.data]);

  const save = useMutation({
    mutationFn: () =>
      api.updateReportBranding({
        ...form,
        signature_labels: sigs.split(",").map((s) => s.trim()).filter(Boolean),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["report-branding"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    },
  });
  const logo = useMutation({
    mutationFn: (f: File) => api.uploadReportLogo(f),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["report-branding"] }),
  });

  const set = (k: keyof ReportBranding, v: string) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-primary/15 text-primary">
          <ImageIcon className="h-5 w-5" />
        </div>
        <div>
          <CardTitle>{t("reports:branding.title")}</CardTitle>
          <p className="text-sm text-muted-foreground">{t("reports:branding.hint")}</p>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("reports:branding.organization")}><Input value={form.organization_name ?? ""} onChange={(e) => set("organization_name", e.target.value)} /></Field>
          <Field label={t("reports:branding.site")}><Input value={form.site_name ?? ""} onChange={(e) => set("site_name", e.target.value)} /></Field>
          <Field label={t("reports:branding.reportTitle")}><Input value={form.report_title ?? ""} onChange={(e) => set("report_title", e.target.value)} /></Field>
          <Field label={t("reports:branding.subtitle")}><Input value={form.subtitle ?? ""} onChange={(e) => set("subtitle", e.target.value)} /></Field>
          <Field label={t("reports:branding.contact")}><Input value={form.contact ?? ""} onChange={(e) => set("contact", e.target.value)} /></Field>
          <Field label={t("reports:branding.signatures")}><Input value={sigs} onChange={(e) => setSigs(e.target.value)} /></Field>
          <Field label={t("reports:branding.disclaimer")}><Input value={form.disclaimer ?? ""} onChange={(e) => set("disclaimer", e.target.value)} /></Field>
          <Field label={t("reports:branding.footer")}><Input value={form.footer_text ?? ""} onChange={(e) => set("footer_text", e.target.value)} /></Field>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
          <label className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">{t("reports:branding.logo")}</span>
            <input
              type="file"
              accept="image/png,image/jpeg"
              onChange={(e) => e.target.files?.[0] && logo.mutate(e.target.files[0])}
              className="text-xs"
            />
            {branding.data?.logo_filename && <Badge tone="ok">✓</Badge>}
          </label>
          <span className="flex items-center gap-2">
            {saved && <span className="text-sm text-ok">{t("reports:branding.saved")}</span>}
            <Button onClick={() => save.mutate()} disabled={save.isPending}>{t("reports:branding.save")}</Button>
          </span>
        </div>
      </CardContent>
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
