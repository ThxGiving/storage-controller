/**
 * Backup & Restore card — rendered inside the Settings page.
 *
 * Sections:
 *  1. Create backup + list of existing backups with download/delete.
 *  2. Restore from file: upload → validate → confirm → execute.
 *  3. Information panel about what is and is not included.
 */

import * as React from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  CheckCircle2,
  Download,
  Info,
  Loader2,
  RotateCcw,
  Trash2,
  TriangleAlert,
  Upload,
} from "lucide-react";
import { api } from "@/lib/api";
import type { BackupJob, ValidationResult } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { formatBytes, formatDateTime } from "@/lib/utils";

// ── Helpers ────────────────────────────────────────────────────────────────────

function BackupRow({
  job,
  onDelete,
  deleting,
}: {
  job: BackupJob;
  onDelete: (id: number) => void;
  deleting: boolean;
}) {
  const { t } = useTranslation("backup");
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-sm">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <Archive className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="truncate font-mono text-xs">{job.filename}</span>
          {job.is_safety_backup && (
            <Badge tone="neutral" className="text-[10px]">
              {t("safetyBackup")}
            </Badge>
          )}
        </div>
        <div className="mt-0.5 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
          <span>{formatDateTime(job.created_at)}</span>
          {job.size_bytes != null && <span>{formatBytes(job.size_bytes)}</span>}
          <span>v{job.app_version}</span>
          <span>{t("schemaRevision")}: {job.schema_revision}</span>
        </div>
        {job.note && (
          <div className="mt-0.5 text-[11px] text-muted-foreground italic">{job.note}</div>
        )}
      </div>
      <div className="flex gap-1">
        <a href={api.downloadBackupUrl(job.id)} download={job.filename}>
          <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs">
            <Download className="h-3.5 w-3.5" />
            {t("download")}
          </Button>
        </a>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-1 text-xs text-destructive hover:text-destructive"
          disabled={deleting}
          onClick={() => {
            if (window.confirm(t("deleteConfirm"))) onDelete(job.id);
          }}
        >
          {deleting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Trash2 className="h-3.5 w-3.5" />
          )}
          {t("delete")}
        </Button>
      </div>
    </div>
  );
}

// ── Main card ──────────────────────────────────────────────────────────────────

export function BackupRestoreCard() {
  const { t } = useTranslation("backup");
  const qc = useQueryClient();

  // ── Backup list ────────────────────────────────────────────────────────────
  const backupsQuery = useQuery({
    queryKey: ["backups"],
    queryFn: api.listBackups,
  });

  const createMut = useMutation({
    mutationFn: api.createBackup,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["backups"] }),
  });

  const [deletingId, setDeletingId] = React.useState<number | null>(null);
  const deleteMut = useMutation({
    mutationFn: (id: number) => api.deleteBackup(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["backups"] }),
    onSettled: () => setDeletingId(null),
  });

  // ── Restore flow ───────────────────────────────────────────────────────────
  const [uploadedFile, setUploadedFile] = React.useState<File | null>(null);
  const [validation, setValidation] = React.useState<ValidationResult | null>(null);
  const [restorePending, setRestorePending] = React.useState(false);
  const fileRef = React.useRef<HTMLInputElement>(null);

  const validateMut = useMutation({
    mutationFn: (file: File) => api.validateBackup(file),
    onSuccess: (result) => setValidation(result),
  });

  const restoreMut = useMutation({
    mutationFn: (file: File) => api.restoreBackup(file),
    onSuccess: () => {
      setRestorePending(true);
      // Poll /api/version until the app comes back up, then reload.
      const start = Date.now();
      const poll = setInterval(async () => {
        // Stop polling after 3 minutes.
        if (Date.now() - start > 180_000) {
          clearInterval(poll);
          return;
        }
        try {
          const res = await fetch("api/status", { cache: "no-store" });
          if (res.ok) {
            clearInterval(poll);
            window.location.reload();
          }
        } catch {
          // App still down — keep polling.
        }
      }, 2000);
    },
  });

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null;
    setUploadedFile(file);
    setValidation(null);
    setRestorePending(false);
    if (file) validateMut.mutate(file);
  }

  function handleRestore() {
    if (!uploadedFile || !validation?.valid) return;
    restoreMut.mutate(uploadedFile);
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Archive className="h-4 w-4" />
          {t("title")}
        </CardTitle>
        <p className="text-sm text-muted-foreground">{t("subtitle")}</p>
      </CardHeader>

      <CardContent className="space-y-6">
        {/* ── Create & list ─────────────────────────────────────────────── */}
        <section>
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="text-sm font-medium">{t("backupList")}</h3>
            <Button
              size="sm"
              onClick={() => createMut.mutate()}
              disabled={createMut.isPending}
              className="gap-1.5"
            >
              {createMut.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Archive className="h-3.5 w-3.5" />
              )}
              {createMut.isPending ? t("creating") : t("createBackup")}
            </Button>
          </div>

          {createMut.isSuccess && !createMut.isPending && (
            <div className="mb-2 flex items-center gap-1.5 text-sm text-green-600 dark:text-green-400">
              <CheckCircle2 className="h-4 w-4" />
              {t("created")}
            </div>
          )}

          {createMut.isError && (
            <div className="mb-2 flex items-start gap-1.5 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{(createMut.error as Error)?.message ?? t("createFailed")}</span>
            </div>
          )}

          {backupsQuery.isLoading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            </div>
          )}

          {backupsQuery.data?.length === 0 && (
            <p className="text-sm text-muted-foreground">{t("noBackups")}</p>
          )}

          <div className="space-y-1.5">
            {backupsQuery.data?.map((job: BackupJob) => (
              <BackupRow
                key={job.id}
                job={job}
                deleting={deletingId === job.id && deleteMut.isPending}
                onDelete={(id) => {
                  setDeletingId(id);
                  deleteMut.mutate(id);
                }}
              />
            ))}
          </div>
        </section>

        {/* ── Restore ───────────────────────────────────────────────────── */}
        <section className="border-t border-border pt-5">
          <h3 className="mb-1 text-sm font-medium">{t("restoreTitle")}</h3>
          <p className="mb-3 text-sm text-muted-foreground">{t("restoreHint")}</p>

          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <input
                ref={fileRef}
                type="file"
                accept=".zip,application/zip"
                className="hidden"
                onChange={handleFileChange}
              />
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                onClick={() => fileRef.current?.click()}
                disabled={restoreMut.isPending || restorePending}
              >
                <Upload className="h-3.5 w-3.5" />
                {t("uploadBackup")}
              </Button>
              {uploadedFile && (
                <span className="truncate text-xs text-muted-foreground">
                  {uploadedFile.name}
                </span>
              )}
              {validateMut.isPending && (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
              )}
            </div>

            {/* Validation result */}
            {validation && (
              <div className="rounded-md border border-border bg-muted/30 p-3 text-sm space-y-2">
                <div className="flex items-center gap-1.5 font-medium">
                  {validation.valid ? (
                    <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
                  ) : (
                    <TriangleAlert className="h-4 w-4 text-destructive" />
                  )}
                  {validation.valid ? t("validationSuccess") : t("validationFailed")}
                </div>

                {validation.issues.length > 0 && (
                  <div>
                    <div className="text-xs font-medium text-destructive mb-1">{t("issues")}</div>
                    <ul className="space-y-0.5 text-xs text-destructive">
                      {validation.issues.map((iss, i) => (
                        <li key={i}>• {iss}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {validation.warnings.length > 0 && (
                  <div>
                    <div className="text-xs font-medium text-amber-600 dark:text-amber-400 mb-1">
                      {t("warnings")}
                    </div>
                    <ul className="space-y-0.5 text-xs text-amber-600 dark:text-amber-400">
                      {validation.warnings.map((w, i) => (
                        <li key={i}>• {w}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {validation.manifest && (
                  <div className="border-t border-border pt-2 grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
                    <span className="font-medium">{t("appVersion")}</span>
                    <span>{validation.manifest.app_version}</span>
                    <span className="font-medium">{t("schemaRevision")}</span>
                    <span>{validation.manifest.schema_revision}</span>
                    <span className="font-medium">{t("createdAt")}</span>
                    <span>{formatDateTime(validation.manifest.created_at)}</span>
                    <span className="font-medium">{t("fileCount")}</span>
                    <span>{validation.manifest.file_count}</span>
                    {validation.manifest.db_size != null && (
                      <>
                        <span className="font-medium">{t("dbSize")}</span>
                        <span>{formatBytes(validation.manifest.db_size)}</span>
                      </>
                    )}
                  </div>
                )}

                {validation.valid && !restorePending && (
                  <div className="border-t border-border pt-2">
                    <p className="text-xs text-muted-foreground mb-2">
                      {t("confirmRestoreHint")}
                    </p>
                    <Button
                      size="sm"
                      variant="danger"
                      className="gap-1.5"
                      disabled={restoreMut.isPending}
                      onClick={handleRestore}
                    >
                      {restoreMut.isPending ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <RotateCcw className="h-3.5 w-3.5" />
                      )}
                      {restoreMut.isPending ? t("restoring") : t("confirmRestore")}
                    </Button>
                  </div>
                )}
              </div>
            )}

            {/* Restore pending / success */}
            {restorePending && (
              <div className="flex items-center gap-1.5 rounded-md border border-amber-400/40 bg-amber-50/60 dark:bg-amber-950/20 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t("restoreSuccess")}
              </div>
            )}
          </div>
        </section>

        {/* ── Info panel ────────────────────────────────────────────────── */}
        <section className="border-t border-border pt-5">
          <div className="flex items-start gap-2 rounded-md border border-border bg-muted/20 p-3 text-sm">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <div className="space-y-1 text-muted-foreground">
              <p className="font-medium text-foreground">{t("haBackup")}</p>
              <p>{t("haBackupInfo")}</p>
              <p className="text-xs">
                <span className="font-medium">{t("includedItems")}</span>
              </p>
              <p className="text-xs text-amber-600 dark:text-amber-400">{t("notIncluded")}</p>
            </div>
          </div>
        </section>
      </CardContent>
    </Card>
  );
}
