import { describe, expect, it } from "vitest";
import { ROLE_SUGGESTED, isTimestampState } from "@/features/units/roleFilters";
import type { HAEntity } from "@/lib/types";

const entity = (over: Partial<HAEntity>): HAEntity => ({
  entity_id: "sensor.x",
  domain: "sensor",
  friendly_name: null,
  state: null,
  unit_of_measurement: null,
  device_class: null,
  device_name: null,
  available: true,
  last_changed: null,
  last_updated: null,
  ...over,
});

describe("connectivity role suggestions", () => {
  it("recognises ISO timestamp states", () => {
    expect(isTimestampState("2026-10-20T19:36:28+0200")).toBe(true);
    expect(isTimestampState("2026-10-20T17:36:28Z")).toBe(true);
    expect(isTimestampState("-20.2")).toBe(false);
    expect(isTimestampState(null)).toBe(false);
  });

  it("suggests connectivity binary sensors and last-read sensors", () => {
    const suggest = ROLE_SUGGESTED.connectivity!;
    expect(
      suggest(entity({ domain: "binary_sensor", device_class: "connectivity", state: "on" })),
    ).toBe(true);
    expect(suggest(entity({ state: "2026-10-20T19:36:28+0200" }))).toBe(true);
    expect(suggest(entity({ device_class: "timestamp", state: "unknown" }))).toBe(true);
    expect(suggest(entity({ device_class: "temperature", state: "-20.2" }))).toBe(false);
  });
});
