import { apiUrl } from "./ingress";
import type {
  AppSettings,
  AppStatus,
  AssignmentCurrentValue,
  ConnectionStatus,
  DashboardResponse,
  DefrostCycle,
  DefrostDiagnosticsResponse,
  DefrostLearningApprove,
  DefrostLearningStatus,
  DiagnosticsLogsResponse,
  DiagnosticsMode,
  HAEntity,
  HistoryAvailability,
  HistoryImportJob,
  HistoryRange,
  RecentEventsResponse,
  HistoryResponse,
  Incident,
  IncidentDetail,
  IncidentUpdate,
  MaintenanceStatus,
  MonitoringProfile,
  Report,
  ReportBranding,
  ReportCreate,
  ReportPreview,
  StorageUnit,
  StorageUnitInput,
  SmtpSettings,
  SmtpSettingsInput,
  SmtpTestResult,
  Schedule,
  ScheduleInput,
  ScheduleRun,
} from "./types";

export interface SamplesParams {
  role?: string;
  range?: "24h" | "7d" | "30d" | "custom";
  from?: string;
  to?: string;
  max_points?: number;
}

export class ApiError extends Error {
  /** Stable machine-readable error code the frontend translates (errors.<code>). */
  code: string;
  details: Record<string, unknown>;

  constructor(
    public status: number,
    message: string,
    code = "generic",
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.details = details;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // FormData (file upload) must set its own multipart boundary — don't force JSON.
  const isForm = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const res = await fetch(apiUrl(path), {
    headers: isForm ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let message = res.statusText;
    let code = "generic";
    let details: Record<string, unknown> = {};
    try {
      const body = await res.json();
      // App errors: { code, details, message }. Pydantic 422: { detail: [...] }.
      if (typeof body.code === "string") {
        code = body.code;
        message = typeof body.message === "string" ? body.message : code;
        details = body.details ?? {};
      } else if (typeof body.detail === "string") {
        message = body.detail;
      } else if (res.status === 422) {
        code = "invalid_input";
      }
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new ApiError(res.status, message, code, details);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  getStatus: () => request<AppStatus>("api/status"),
  getConnection: () => request<ConnectionStatus>("api/home-assistant/connection"),

  getEntities: (params?: {
    search?: string;
    domain?: string;
    device_class?: string;
    limit?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.search) q.set("search", params.search);
    if (params?.domain) q.set("domain", params.domain);
    if (params?.device_class) q.set("device_class", params.device_class);
    // Load the full entity set so client-side search and the role selectors see
    // every entity (HA installs commonly have well over the old 500 default).
    q.set("limit", String(params?.limit ?? 5000));
    return request<HAEntity[]>(`api/home-assistant/entities?${q.toString()}`);
  },

  listUnits: () => request<StorageUnit[]>("api/storage-units"),
  getUnit: (id: number) => request<StorageUnit>(`api/storage-units/${id}`),
  createUnit: (input: StorageUnitInput) =>
    request<StorageUnit>("api/storage-units", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  updateUnit: (id: number, input: Partial<StorageUnitInput>) =>
    request<StorageUnit>(`api/storage-units/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),
  deleteUnit: (id: number) =>
    request<void>(`api/storage-units/${id}`, { method: "DELETE" }),
  unitCurrent: (id: number) =>
    request<AssignmentCurrentValue[]>(`api/storage-units/${id}/current`),

  listProfiles: () => request<MonitoringProfile[]>("api/monitoring-profiles"),

  getDashboard: () => request<DashboardResponse>("api/dashboard"),

  getSamples: (id: number, params?: SamplesParams) => {
    const q = new URLSearchParams();
    if (params?.role) q.set("role", params.role);
    if (params?.range) q.set("range", params.range);
    if (params?.from) q.set("from", params.from);
    if (params?.to) q.set("to", params.to);
    q.set("max_points", String(params?.max_points ?? 800));
    return request<HistoryResponse>(`api/storage-units/${id}/samples?${q.toString()}`);
  },

  getDefrostCycles: (id: number, range = "24h") =>
    request<DefrostCycle[]>(`api/storage-units/${id}/defrost-cycles?range=${range}`),

  getHistoryAvailability: (unitId: number, entityId: string) =>
    request<HistoryAvailability>(
      `api/storage-units/${unitId}/history/availability?entity_id=${encodeURIComponent(entityId)}`,
    ),
  getHistoryImport: (unitId: number) =>
    request<HistoryImportJob | null>(`api/storage-units/${unitId}/history/import`),
  startHistoryImport: (unitId: number, input: { entity_id: string; range: HistoryRange }) =>
    request<HistoryImportJob>(`api/storage-units/${unitId}/history/import`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  cancelHistoryImport: (unitId: number) =>
    request<HistoryImportJob | null>(`api/storage-units/${unitId}/history/import/cancel`, {
      method: "POST",
    }),

  getDefrostLearning: (id: number) =>
    request<DefrostLearningStatus>(`api/storage-units/${id}/defrost/learning`),
  approveDefrostLearning: (id: number, input: DefrostLearningApprove = {}) =>
    request<DefrostLearningStatus>(`api/storage-units/${id}/defrost/learning/approve`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  resetDefrostLearning: (id: number) =>
    request<DefrostLearningStatus>(`api/storage-units/${id}/defrost/learning/reset`, {
      method: "POST",
    }),

  listIncidents: (params?: { state?: "all" | "open" | "closed"; storage_unit_id?: number }) => {
    const q = new URLSearchParams();
    if (params?.state) q.set("state", params.state);
    if (params?.storage_unit_id != null) q.set("storage_unit_id", String(params.storage_unit_id));
    const qs = q.toString();
    return request<Incident[]>(`api/incidents${qs ? `?${qs}` : ""}`);
  },
  getIncident: (id: number) => request<IncidentDetail>(`api/incidents/${id}`),
  updateIncident: (id: number, input: IncidentUpdate) =>
    request<IncidentDetail>(`api/incidents/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),

  getSettings: () => request<AppSettings>("api/settings"),
  updateSettings: (input: Partial<AppSettings>) =>
    request<AppSettings>("api/settings", {
      method: "PATCH",
      body: JSON.stringify(input),
    }),

  getMaintenanceStatus: () => request<MaintenanceStatus>("api/maintenance/status"),
  runMaintenance: () =>
    request<MaintenanceStatus>("api/maintenance/run", { method: "POST" }),

  getDefrostDiagnostics: () =>
    request<DefrostDiagnosticsResponse>("api/diagnostics/defrost"),
  getRecentEvents: (entityId: string, limit = 50) =>
    request<RecentEventsResponse>(
      `api/diagnostics/events/recent?entity_id=${encodeURIComponent(entityId)}&limit=${limit}`,
    ),
  getDiagnosticsMode: () => request<DiagnosticsMode>("api/diagnostics/logging/status"),
  enableDiagnostics: (minutes = 30) =>
    request<DiagnosticsMode>("api/diagnostics/logging/enable", {
      method: "POST",
      body: JSON.stringify({ minutes }),
    }),
  disableDiagnostics: () =>
    request<DiagnosticsMode>("api/diagnostics/logging/disable", { method: "POST" }),
  getDiagnosticsLogs: (params?: { component?: string; entity_id?: string; severity?: string }) => {
    const q = new URLSearchParams();
    if (params?.component) q.set("component", params.component);
    if (params?.entity_id) q.set("entity_id", params.entity_id);
    if (params?.severity) q.set("severity", params.severity);
    const qs = q.toString();
    return request<DiagnosticsLogsResponse>(`api/diagnostics/logs${qs ? `?${qs}` : ""}`);
  },

  // --- Reports (Phase 5) ---
  listReports: () => request<Report[]>("api/reports"),
  previewReport: (input: ReportCreate) =>
    request<ReportPreview>("api/reports/preview", { method: "POST", body: JSON.stringify(input) }),
  createReport: (input: ReportCreate) =>
    request<Report>("api/reports", { method: "POST", body: JSON.stringify(input) }),
  deleteReport: (id: number) =>
    request<void>(`api/reports/${id}`, { method: "DELETE" }),
  reportDownloadUrl: (id: number, fmt: "pdf" | "csv" | "json") =>
    apiUrl(`api/reports/${id}/${fmt}`),
  getReportBranding: () => request<ReportBranding>("api/report-branding"),
  updateReportBranding: (input: Partial<ReportBranding>) =>
    request<ReportBranding>("api/report-branding", {
      method: "PATCH",
      body: JSON.stringify(input),
    }),
  uploadReportLogo: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ReportBranding>("api/report-branding/logo", { method: "POST", body: form });
  },
  deleteReportLogo: () =>
    request<ReportBranding>("api/report-branding/logo", { method: "DELETE" }),

  // --- Phase 6: SMTP + schedules ---
  getEmailSettings: () => request<SmtpSettings>("api/settings/email"),
  updateEmailSettings: (input: SmtpSettingsInput) =>
    request<SmtpSettings>("api/settings/email", { method: "PUT", body: JSON.stringify(input) }),
  testSmtpConnection: () =>
    request<SmtpTestResult>("api/settings/email/test-connection", { method: "POST" }),
  sendTestEmail: (recipient: string) =>
    request<SmtpTestResult>("api/settings/email/test-email", {
      method: "POST",
      body: JSON.stringify({ recipient }),
    }),

  listSchedules: () => request<Schedule[]>("api/schedules"),
  createSchedule: (input: ScheduleInput) =>
    request<Schedule>("api/schedules", { method: "POST", body: JSON.stringify(input) }),
  updateSchedule: (id: number, input: ScheduleInput) =>
    request<Schedule>(`api/schedules/${id}`, { method: "PUT", body: JSON.stringify(input) }),
  deleteSchedule: (id: number) =>
    request<void>(`api/schedules/${id}`, { method: "DELETE" }),
  enableSchedule: (id: number) =>
    request<Schedule>(`api/schedules/${id}/enable`, { method: "POST" }),
  disableSchedule: (id: number) =>
    request<Schedule>(`api/schedules/${id}/disable`, { method: "POST" }),
  runScheduleNow: (id: number, send: boolean) =>
    request<ScheduleRun>(`api/schedules/${id}/run-now?send=${send}`, { method: "POST" }),
  listScheduleRuns: (id: number) =>
    request<ScheduleRun[]>(`api/schedules/${id}/runs`),
  sendExistingReport: (runId: number) =>
    request<ScheduleRun>(`api/schedules/runs/${runId}/send`, { method: "POST" }),
  resendDelivery: (runId: number) =>
    request<ScheduleRun>(`api/schedules/runs/${runId}/resend`, { method: "POST" }),
  cancelRun: (runId: number) =>
    request<ScheduleRun>(`api/schedules/runs/${runId}/cancel`, { method: "POST" }),
};
