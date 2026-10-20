import type { EntityRole, HAEntity } from "@/lib/types";

/** State looks like an ISO date-time ("2026-10-20T19:36:28+0200"). */
export const isTimestampState = (state: string | null | undefined): boolean =>
  /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(state ?? "");

/**
 * Sensible candidate filters per role. These only influence ordering in the
 * entity selector — the user can still pick any valid entity (suggestions, not
 * rigid restrictions).
 */
export const ROLE_SUGGESTED: Partial<Record<EntityRole, (e: HAEntity) => boolean>> = {
  room_temperature: (e) =>
    e.domain === "sensor" && e.device_class === "temperature",
  evaporator_temperature: (e) =>
    e.domain === "sensor" && e.device_class === "temperature",
  setpoint: (e) => e.domain === "number" || e.domain === "sensor",
  hysteresis: (e) => e.domain === "number" || e.domain === "sensor",
  compressor: (e) =>
    ["binary_sensor", "switch", "input_boolean", "sensor"].includes(e.domain),
  fan: (e) =>
    ["binary_sensor", "switch", "input_boolean", "sensor"].includes(e.domain),
  door: (e) =>
    ["binary_sensor", "switch", "input_boolean", "sensor"].includes(e.domain),
  alarm: (e) =>
    ["binary_sensor", "switch", "input_boolean", "sensor"].includes(e.domain),
  defrost: (e) =>
    ["switch", "button", "input_boolean", "binary_sensor"].includes(e.domain),
  light: (e) =>
    ["switch", "button", "input_boolean", "binary_sensor", "light"].includes(e.domain),
  controller: (e) =>
    ["switch", "button", "input_boolean", "binary_sensor"].includes(e.domain),
  // On/off link entity, or a sensor holding the time of the last successful read.
  connectivity: (e) =>
    (e.domain === "binary_sensor" && e.device_class === "connectivity") ||
    (e.domain === "sensor" &&
      (e.device_class === "timestamp" || isTimestampState(e.state))),
};
