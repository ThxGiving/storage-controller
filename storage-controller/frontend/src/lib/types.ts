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
  value_mapping_json: string | null;
}

export interface ValueMapping {
  active: string[];
  inactive: string[];
  invert: boolean;
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
  defrost_evaluation_enabled: boolean;
  defrost_learning_min_cycles: number;
  created_at: string;
  updated_at: string;
  assignments: EntityAssignment[];
}

export interface AssignmentInput {
  role: EntityRole;
  entity_id: string;
  enabled?: boolean;
  invert_state?: boolean;
  value_mapping?: ValueMapping | null;
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
  defrost_evaluation_enabled?: boolean;
  assignments: AssignmentInput[];
}

// --- Phase 4.6: defrost learning --------------------------------------------

export interface LearnedDefrostModel {
  id: number;
  version: number;
  status: string;
  confidence: "insufficient" | "preliminary" | "high";
  confidence_score: number;
  valid_cycle_count: number;
  window_start: string | null;
  window_end: string | null;
  typical_defrost_seconds: number | null;
  max_defrost_seconds: number | null;
  typical_recovery_seconds: number | null;
  max_recovery_seconds: number | null;
  typical_room_peak_c: number | null;
  max_room_peak_c: number | null;
  typical_evaporator_peak_c: number | null;
  max_evaporator_peak_c: number | null;
  typical_interval_seconds: number | null;
  room_peak_variation_c: number | null;
  duration_variation_seconds: number | null;
  safety_margin_c: number;
  drift_warning: boolean;
  drift_detail: string | null;
  generated_at: string | null;
  approved_at: string | null;
  approved_by: string | null;
}

export type DefrostLearningState =
  | "disabled"
  | "no_entity"
  | "observing"
  | "suggestion_ready"
  | "approved";

export interface DefrostLearningStatus {
  storage_unit_id: number;
  enabled: boolean;
  has_defrost_entity: boolean;
  state: DefrostLearningState;
  valid_cycle_count: number;
  min_cycles: number;
  confidence: "insufficient" | "preliminary" | "high";
  confidence_score: number;
  outlier_count: number;
  outliers: string[];
  drift_warning: boolean;
  drift_detail: string | null;
  suggestion: LearnedDefrostModel | null;
  approved: LearnedDefrostModel | null;
  recent_cycles: DefrostCycle[];
}

export interface DefrostLearningApprove {
  max_room_peak_c?: number | null;
  max_evaporator_peak_c?: number | null;
  max_defrost_seconds?: number | null;
  max_recovery_seconds?: number | null;
  safety_margin_c?: number | null;
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

export interface DashboardIncident {
  id: number;
  type: string;
  state: string;
  opened_at: string;
  confirmed_at: string | null;
  extreme_value_c: number | null;
  defrost_overlap: boolean;
  acknowledged: boolean;
  documented: boolean;
}

export interface DashboardDefrost {
  id: number;
  status: string;
  started_at: string;
  recovery_started_at: string | null;
  peak_room_temperature_c: number | null;
  peak_evaporator_temperature_c: number | null;
  max_expected_duration_seconds: number;
  max_recovery_seconds: number;
  recovery_target_c: number | null;
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
  active_incidents: DashboardIncident[];
  defrost: DashboardDefrost | null;
}

export type IncidentType =
  | "temperature_high"
  | "temperature_low"
  | "sensor_unavailable"
  | "sensor_stale"
  | "sensor_invalid"
  | "home_assistant_disconnected"
  | "abnormal_defrost"
  | "recovery_timeout";

export interface IncidentEvent {
  timestamp: string;
  kind: string;
  from_state: string | null;
  to_state: string | null;
  value_c: number | null;
  user: string | null;
  detail: string | null;
}

export interface Incident {
  id: number;
  storage_unit_id: number | null;
  type: string;
  state: string;
  opened_at: string;
  confirmed_at: string | null;
  recovering_at: string | null;
  closed_at: string | null;
  limit_value_c: number | null;
  extreme_value_c: number | null;
  extreme_at: string | null;
  defrost_overlap: boolean;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  cause: string | null;
  corrective_action: string | null;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface IncidentDetail extends Incident {
  storage_unit_name: string | null;
  events: IncidentEvent[];
}

export interface IncidentUpdate {
  acknowledge?: boolean;
  cause?: string;
  corrective_action?: string;
  note?: string;
}

export interface DefrostCycle {
  id: number;
  storage_unit_id: number;
  started_at: string;
  ended_at: string | null;
  recovery_started_at: string | null;
  recovered_at: string | null;
  initial_room_temperature_c: number | null;
  peak_room_temperature_c: number | null;
  initial_evaporator_temperature_c: number | null;
  peak_evaporator_temperature_c: number | null;
  status: string;
  classification: string | null;
  triggering_rule: string | null;
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
  timezone: string;
  timezone_abbreviation: string;
  timezone_offset: string;
  timezone_label: string;
  heartbeat_interval_seconds: number;
  min_temp_delta_c: number;
  retention_raw_days: number;
  retention_agg15_days: number;
  retention_agg_hourly_days: number;
  storage_budget_bytes: number;
  warning_pct: number;
  critical_pct: number;
  emergency_pct: number;
}

export interface StorageCategory {
  name: string;
  bytes: number;
}

export interface MaintenanceStatus {
  last_run: string | null;
  next_run: string | null;
  last_result: string | null;
  database_bytes: number;
  wal_bytes: number;
  reports_bytes: number;
  uploads_bytes: number;
  logs_bytes: number;
  app_total_bytes: number;
  free_bytes: number;
  free_percent: number;
  budget_bytes: number;
  budget_used_percent: number;
  level: "ok" | "warning" | "critical" | "emergency";
  categories: StorageCategory[];
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

// --- Phase 4.6.1: diagnostics ----------------------------------------------

export interface DefrostMappingDiagnostic {
  storage_unit_id: number;
  storage_unit_name: string;
  defrost_entity_id: string;
  entity_domain: string;
  evaluation_enabled: boolean;
  entity_exists: boolean;
  available: boolean;
  raw_state: string | null;
  normalized_bool: boolean | null;
  normalization_reason: string;
  value_mapping: { active: string[]; inactive: string[]; invert: boolean; configured: boolean };
  last_state_change: string | null;
  last_event_received: string | null;
  last_event_persisted: string | null;
  last_engine_evaluation: string | null;
  engine_state: string;
  active_cycle_id: number | null;
  last_cycle_started: string | null;
  last_cycle_ended: string | null;
  last_completed_cycle_id: number | null;
  last_cycle_reconstructed: boolean;
  last_ignored_reason: string | null;
  connected: boolean;
  reconnect_attempts: number;
  last_connected_at: string | null;
  problem: string | null;
}

export interface DefrostDiagnosticsResponse {
  generated_at: string;
  connected: boolean;
  last_event_at: string | null;
  last_engine_evaluation: string | null;
  mappings: DefrostMappingDiagnostic[];
}

export interface EventTrace {
  timestamp: string;
  entity_id: string;
  storage_unit_id: number | null;
  role: string | null;
  old_raw: string | null;
  new_raw: string | null;
  normalized_old: string | null;
  normalized_new: string | null;
  mapping_found: boolean;
  persisted: boolean;
  engine_relevant: boolean;
  result: string;
}

export interface RecentEventsResponse {
  entity_id: string | null;
  events: EventTrace[];
}

export interface DiagnosticsMode {
  enabled: boolean;
  expires_at: string | null;
  remaining_seconds: number;
  enabled_by: string | null;
  buffered_logs: number;
}

export interface DiagnosticsLogEntry {
  timestamp: string;
  severity: string;
  component: string;
  message: string;
  storage_unit_id: number | null;
  entity_id: string | null;
  fields: Record<string, unknown>;
}

export interface DiagnosticsLogsResponse {
  mode: DiagnosticsMode;
  count: number;
  entries: DiagnosticsLogEntry[];
}

// --- Phase 5: reports -------------------------------------------------------

export type ReportStatus = "queued" | "generating" | "completed" | "failed";
export type ReportDetailLevel = "compact" | "standard" | "detailed";

export interface Report {
  id: number;
  uuid: string;
  status: ReportStatus;
  period_year: number;
  period_month: number;
  locale: string;
  timezone: string;
  detail_level: ReportDetailLevel;
  storage_unit_ids: number[];
  checksum_sha256: string | null;
  has_pdf: boolean;
  has_csv: boolean;
  has_json: boolean;
  created_by: string | null;
  created_at: string;
  generated_at: string | null;
  duration_ms: number | null;
  failure_category: string | null;
  error_message: string | null;
}

export interface ReportCreate {
  year: number;
  month: number;
  storage_unit_ids: number[];
  locale?: string;
  timezone?: string;
  detail_level?: ReportDetailLevel;
  allow_duplicate?: boolean;
}

export interface ReportPreview {
  model: Record<string, unknown>;
  html: string;
}

export interface ReportBranding {
  organization_name: string | null;
  site_name: string | null;
  address: string | null;
  contact: string | null;
  logo_filename: string | null;
  report_title: string | null;
  subtitle: string | null;
  accent: string | null;
  footer_text: string | null;
  disclaimer: string | null;
  signature_labels: string[];
  default_locale: string;
  default_timezone: string;
  default_detail_level: ReportDetailLevel;
}

// --- Phase 5.1: history import ----------------------------------------------

export type HistoryRange = "all" | "current_month" | "last_30_days" | "last_90_days";

export interface HistoryAvailability {
  state: "raw_available" | "stats_only" | "no_history";
  raw_available: boolean;
  has_statistics: boolean;
  recommended_range: HistoryRange;
  connected: boolean;
}

export interface HistoryImportJob {
  id: number;
  storage_unit_id: number;
  entity_id: string;
  requested_range: HistoryRange;
  status: "importing" | "completed" | "partial" | "failed" | "no_history";
  raw_from: string | null;
  raw_to: string | null;
  raw_count: number;
  stats_from: string | null;
  stats_to: string | null;
  stats_count: number;
  error_message: string | null;
  created_at: string;
  finished_at: string | null;
}
