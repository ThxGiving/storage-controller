import type { EntityRole, HAEntity } from "@/lib/types";

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
};
