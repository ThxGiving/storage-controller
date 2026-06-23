import { apiUrl } from "./ingress";
import type {
  AppSettings,
  AppStatus,
  AssignmentCurrentValue,
  ConnectionStatus,
  DashboardResponse,
  DefrostCycle,
  DefrostLearningApprove,
  DefrostLearningStatus,
  HAEntity,
  HistoryResponse,
  Incident,
  IncidentDetail,
  IncidentUpdate,
  MaintenanceStatus,
  MonitoringProfile,
  StorageUnit,
  StorageUnitInput,
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
  const res = await fetch(apiUrl(path), {
    headers: { "Content-Type": "application/json" },
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
};
