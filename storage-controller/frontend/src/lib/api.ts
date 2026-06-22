import { apiUrl } from "./ingress";
import type {
  AppStatus,
  AssignmentCurrentValue,
  ConnectionStatus,
  HAEntity,
  MonitoringProfile,
  StorageUnit,
  StorageUnitInput,
} from "./types";

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

  getEntities: (params?: { search?: string; domain?: string; device_class?: string }) => {
    const q = new URLSearchParams();
    if (params?.search) q.set("search", params.search);
    if (params?.domain) q.set("domain", params.domain);
    if (params?.device_class) q.set("device_class", params.device_class);
    const qs = q.toString();
    return request<HAEntity[]>(`api/home-assistant/entities${qs ? `?${qs}` : ""}`);
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
};
