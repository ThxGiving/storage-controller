export type EntityRole =
  | "room_temperature"
  | "evaporator_temperature"
  | "setpoint"
  | "hysteresis"
  | "compressor"
  | "fan"
  | "defrost"
  | "light"
  | "controller"
  | "door"
  | "alarm";

export const ENTITY_ROLES: EntityRole[] = [
  "room_temperature",
  "evaporator_temperature",
  "setpoint",
  "hysteresis",
  "compressor",
  "fan",
  "defrost",
  "light",
  "controller",
  "door",
  "alarm",
];

export const MANDATORY_ROLES: EntityRole[] = ["room_temperature"];

export type StorageUnitType =
  | "day_cold_room"
  | "freezer_room"
  | "vegetable_cold_room"
  | "beverage_cold_room"
  | "refrigerator"
  | "freezer"
  | "refrigerated_counter"
  | "custom";

export const STORAGE_UNIT_TYPES: StorageUnitType[] = [
  "day_cold_room",
  "freezer_room",
  "vegetable_cold_room",
  "beverage_cold_room",
  "refrigerator",
  "freezer",
  "refrigerated_counter",
  "custom",
];

export interface MonitoringProfile {
  id: number;
  key: string | null;
  name: string;
  description: string | null;
  built_in: boolean;
  archived: boolean;
  lower_limit_c: number | null;
  upper_limit_c: number | null;
  warning_margin_c: number;
  violation_delay_seconds: number;
  recovery_delay_seconds: number;
  offline_delay_seconds: number;
  plausible_min_c: number | null;
  plausible_max_c: number | null;
  defrost_grace_enabled: boolean;
  defrost_grace_seconds: number;
  chart_group: string | null;
  report_enabled_by_default: boolean;
}

export interface HAEntity {
  entity_id: string;
  domain: string;
  friendly_name: string | null;
  state: string | null;
  unit_of_measurement: string | null;
  device_class: string | null;
  device_name: string | null;
  available: boolean;
  last_changed: string | null;
  last_updated: string | null;
}

export type ConnectionState =
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "authentication_error";

export interface ConnectionStatus {
  status: ConnectionState;
  last_event_at: string | null;
  last_connected_at: string | null;
  reconnect_attempts: number;
  entity_count: number;
  detail: string | null;
}

export interface AppStatus {
  name: string;
  version: string;
  home_assistant: ConnectionStatus;
  storage_unit_count: number;
  database_ok: boolean;
}

export interface EntityAssignment {
  id: number;
  role: EntityRole;
  entity_id: string;
  enabled: boolean;
  invert_state: boolean;
}

export interface StorageUnit {
  id: number;
  name: string;
  short_report_name: string | null;
  description: string | null;
  location: string | null;
  unit_type: StorageUnitType;
  enabled: boolean;
  sort_order: number;
  lower_limit_c: number | null;
  upper_limit_c: number | null;
  warning_margin_c: number;
  violation_delay_seconds: number;
  recovery_delay_seconds: number;
  offline_delay_seconds: number;
  defrost_grace_enabled: boolean;
  defrost_grace_seconds: number;
  plausible_min_c: number | null;
  plausible_max_c: number | null;
  chart_group: string | null;
  report_enabled: boolean;
  applied_profile_key: string | null;
  applied_profile_name: string | null;
  created_at: string;
  updated_at: string;
  assignments: EntityAssignment[];
}

export interface AssignmentInput {
  role: EntityRole;
  entity_id: string;
  enabled?: boolean;
  invert_state?: boolean;
}

export interface StorageUnitInput {
  name: string;
  short_report_name?: string | null;
  description?: string | null;
  location?: string | null;
  unit_type?: StorageUnitType;
  enabled?: boolean;
  lower_limit_c?: number | null;
  upper_limit_c?: number | null;
  warning_margin_c?: number;
  violation_delay_seconds?: number;
  recovery_delay_seconds?: number;
  offline_delay_seconds?: number;
  defrost_grace_enabled?: boolean;
  plausible_min_c?: number | null;
  plausible_max_c?: number | null;
  chart_group?: string | null;
  applied_profile_key?: string | null;
  applied_profile_name?: string | null;
  assignments: AssignmentInput[];
}

// --- Phase 3: history + dashboard -------------------------------------------

export interface HistoryPoint {
  t: string;
  v: number | null;
  vmin?: number | null;
  vmax?: number | null;
  q?: string | null;
}

export interface HistoryResponse {
  storage_unit_id: number;
  role: EntityRole;
  entity_id: string | null;
  unit: string;
  from_ts: string;
  to_ts: string;
  lower_limit_c: number | null;
  upper_limit_c: number | null;
  sample_count: number;
  downsampled: boolean;
  bucket_seconds: number | null;
  points: HistoryPoint[];
  min_c: number | null;
  max_c: number | null;
  avg_c: number | null;
  coverage_ratio: number | null;
}

export type OperationalStatus =
  | "normal"
  | "near_limit"
  | "outside_range"
  | "unavailable"
  | "stale"
  | "disconnected"
  | "configuration_error";

export interface DashboardRoleValue {
  role: EntityRole;
  entity_id: string;
  exists: boolean;
  available: boolean;
  quality: string;
  numeric_c: number | null;
  raw: string | null;
  unit: string | null;
  bool_value: boolean | null;
}

export interface DashboardSpark {
  t: string;
  v: number | null;
}

export interface DashboardUnit {
  id: number;
  name: string;
  short_report_name: string | null;
  unit_type: StorageUnitType;
  profile_name: string | null;
  lower_limit_c: number | null;
  upper_limit_c: number | null;
  warning_margin_c: number;
  setpoint_c: number | null;
  status: OperationalStatus;
  room: DashboardRoleValue | null;
  last_update: string | null;
  roles: DashboardRoleValue[];
  spark: DashboardSpark[];
}

export interface DashboardSummary {
  total: number;
  normal: number;
  near_limit: number;
  outside_range: number;
  unavailable: number;
  stale: number;
  disconnected: number;
  configuration_error: number;
}

export interface DashboardResponse {
  connection: ConnectionStatus;
  summary: DashboardSummary;
  units: DashboardUnit[];
  last_sample_at: string | null;
  timezone: string;
  generated_at: string;
}

export interface AppSettings {
  heartbeat_interval_seconds: number;
  retention_raw_days: number;
  retention_state_days: number;
}

export interface AssignmentCurrentValue {
  role: EntityRole;
  entity_id: string;
  exists: boolean;
  available: boolean;
  state: string | null;
  unit_of_measurement: string | null;
  friendly_name: string | null;
  warning: string | null;
}
