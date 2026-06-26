import * as React from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, FileDown, Trash2, Eye, Sparkles, Image as ImageIcon, CalendarClock, AlertTriangle } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { Report, ReportBranding, ReportCreate, ReportDetailLevel } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Modal } from "@/components/ui/modal";
import { SchedulesPage } from "./Schedules";

const DETAILS: ReportDetailLevel[] = ["compact", "standard", "detailed"];
const now = new Date();
const DEFAULT_ACCENT = "#1E3A5F";
const HEX_RE = /^#[0-9a-fA-F]{6}$/;

function _lin(c: number): number {
  c /= 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}
function _lum(r: number, g: number, b: number): number {
  return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b);
}
function _h2(n: number): string {
  return Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, "0");
}
function accentTokens(raw: string | null | undefined) {
  const a = raw && HEX_RE.test(raw.trim()) ? raw.trim().toUpperCase() : DEFAULT_ACCENT;
  const r = parseInt(a.slice(1, 3), 16);
  const g = parseInt(a.slice(3, 5), 16);
  const b = parseInt(a.slice(5, 7), 16);
  const lum = _lum(r, g, b);
  const fg = lum < 0.35 ? "#ffffff" : "#111827";
  const [sfr, sfg, sfb] = lum < 0.35
    ? [r + (255 - r) * 0.60, g + (255 - g) * 0.60, b + (255 - b) * 0.60]
    : [r * 0.55, g * 0.55, b * 0.55];
  const secondaryFg = `#${_h2(sfr)}${_h2(sfg)}${_h2(sfb)}`;
  const subtleBg = `#${_h2(r * 0.12 + 255 * 0.88)}${_h2(g * 0.12 + 255 * 0.88)}${_h2(b * 0.12 + 255 * 0.88)}`;
  const border = `#${_h2(r * 0.35 + 255 * 0.65)}${_h2(g * 0.35 + 255 * 0.65)}${_h2(b * 0.35 + 255 * 0.65)}`;
  const dark = `#${_h2(r * 0.80)}${_h2(g * 0.80)}${_h2(b * 0.80)}`;
  const fgLum = fg === "#ffffff" ? 1.0 : _lum(17, 24, 39);
  const hi = Math.max(lum, fgLum), lo = Math.min(lum, fgLum);
  const lowContrast = (hi + 0.05) / (lo + 0.05) < 4.5;
  return { base: a, fg, secondaryFg, subtleBg, border, dark, lowContrast };
}

type ReportsTab = "reports" | "schedules";

export function ReportsPage() {
  const { t } = useTranslation(["reports", "schedules", "common"]);
  const [activeTab, setActiveTab] = React.useState<ReportsTab>("reports");

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-semibold">{t("reports:title")}</h1>
        <p className="text-sm text-muted-foreground">{t("reports:subtitle")}</p>
      </div>
      <div className="flex gap-1 border-b border-border">
        {(["reports", "schedules"] as ReportsTab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
              activeTab === tab
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab === "reports" && <FileText className="h-4 w-4" />}
            {tab === "schedules" && <CalendarClock className="h-4 w-4" />}
            {tab === "reports" && t("reports:title")}
            {tab === "schedules" && t("schedules:list.title")}
          </button>
        ))}
      </div>
      {activeTab === "reports" && <ReportsContent />}
      {activeTab === "schedules" && <SchedulesPage />}
    </div>
  );
}

function ReportsContent() {
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
  const { t } = useTranslation(["reports", "common"]);
  const qc = useQueryClient();
  const branding = useQuery({ queryKey: ["report-branding"], queryFn: api.getReportBranding });
  const [form, setForm] = React.useState<Partial<ReportBranding>>({});
  const [sigs, setSigs] = React.useState("");
  const [accentHex, setAccentHex] = React.useState(DEFAULT_ACCENT);
  const [accentValid, setAccentValid] = React.useState(true);
  const [saved, setSaved] = React.useState(false);

  React.useEffect(() => {
    if (branding.data) {
      setForm(branding.data);
      setSigs((branding.data.signature_labels ?? []).join(", "));
      const hex = branding.data.accent ?? DEFAULT_ACCENT;
      setAccentHex(hex.toUpperCase());
    }
  }, [branding.data]);

  const tok = accentTokens(accentValid ? accentHex : null);

  const handleAccentHex = (v: string) => {
    const upper = v.toUpperCase();
    setAccentHex(upper);
    const valid = HEX_RE.test(upper);
    setAccentValid(valid);
    if (valid) setForm((f) => ({ ...f, accent: upper }));
  };

  const handleAccentPicker = (v: string) => {
    const upper = v.toUpperCase();
    setAccentHex(upper);
    setAccentValid(true);
    setForm((f) => ({ ...f, accent: upper }));
  };

  const resetAccent = () => {
    setAccentHex(DEFAULT_ACCENT);
    setAccentValid(true);
    setForm((f) => ({ ...f, accent: null }));
  };

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

        {/* Accent color picker */}
        <div className="border-t border-border pt-3">
          <div className="mb-1.5 text-sm font-medium">{t("reports:branding.accentColor")}</div>
          <p className="mb-2 text-xs text-muted-foreground">{t("reports:branding.accentHint")}</p>
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="color"
              value={accentValid ? accentHex : DEFAULT_ACCENT}
              onChange={(e) => handleAccentPicker(e.target.value)}
              className="h-9 w-12 cursor-pointer rounded border border-border bg-transparent p-0.5"
              title={t("reports:branding.accentColor")}
            />
            <Input
              value={accentHex}
              onChange={(e) => handleAccentHex(e.target.value)}
              placeholder={DEFAULT_ACCENT}
              className={`w-32 font-mono text-sm uppercase${!accentValid ? " border-danger" : ""}`}
              maxLength={7}
            />
            <Button variant="ghost" size="sm" onClick={resetAccent} className="text-muted-foreground text-xs">
              {t("reports:branding.accentReset")}
            </Button>
          </div>

          {/* Live preview */}
          <div className="mt-3 overflow-hidden rounded-lg border border-border text-[13px]">
            <div className="px-4 py-3" style={{ backgroundColor: tok.base }}>
              <div style={{ color: tok.fg, fontWeight: 700, lineHeight: 1.3 }}>
                {form.organization_name || t("common:appName")}
              </div>
              <div style={{ color: tok.secondaryFg, fontSize: "11px", marginTop: "2px" }}>
                {form.site_name || t("reports:branding.accentPreviewSubtitle")}
              </div>
            </div>
            <div className="px-4 py-2" style={{ backgroundColor: tok.subtleBg, borderLeft: `3px solid ${tok.base}` }}>
              <span style={{ color: tok.dark, fontWeight: 600, fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                {t("reports:branding.accentPreviewSection")}
              </span>
            </div>
          </div>

          {tok.lowContrast && (
            <div className="mt-2 flex items-center gap-1.5 text-xs text-warning">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              {t("reports:branding.accentLowContrast")}
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
          <label className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">{t("reports:branding.logo")}</span>
            <input
              type="file"
              accept="image/png,image/jpeg,image/svg+xml"
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
