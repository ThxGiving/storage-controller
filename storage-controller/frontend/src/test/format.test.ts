import { afterAll, describe, expect, it } from "vitest";
import i18n from "@/i18n";
import { formatNumber, formatState, formatTemperature, parseDecimal } from "@/lib/utils";

afterAll(async () => {
  await i18n.changeLanguage("en");
});

describe("parseDecimal", () => {
  it("accepts English decimal notation", () => {
    expect(parseDecimal("4.5")).toBe(4.5);
  });

  it("accepts German decimal notation", () => {
    expect(parseDecimal("4,5")).toBe(4.5);
  });

  it("returns null for empty input", () => {
    expect(parseDecimal("  ")).toBeNull();
  });

  it("returns null for invalid input", () => {
    expect(parseDecimal("abc")).toBeNull();
  });
});

describe("locale-aware number formatting", () => {
  it("formats with a dot in English", async () => {
    await i18n.changeLanguage("en");
    expect(formatNumber(6.1, { minimumFractionDigits: 1 })).toBe("6.1");
  });

  it("formats with a comma in German", async () => {
    await i18n.changeLanguage("de");
    expect(formatNumber(6.1, { minimumFractionDigits: 1 })).toBe("6,1");
  });

  it("formats a temperature with unit (German)", async () => {
    await i18n.changeLanguage("de");
    expect(formatTemperature(6.1)).toBe("6,1 °C");
  });

  it("returns a dash for nullish values", () => {
    expect(formatNumber(null)).toBe("—");
  });
});

describe("formatState", () => {
  it("rounds an ugly raw sensor float (English)", async () => {
    await i18n.changeLanguage("en");
    expect(formatState("5.90000009536743")).toBe("5.9");
  });

  it("rounds and localizes (German)", async () => {
    await i18n.changeLanguage("de");
    expect(formatState("5.90000009536743")).toBe("5,9");
  });

  it("leaves non-numeric states unchanged", () => {
    expect(formatState("unavailable")).toBe("unavailable");
    expect(formatState("on")).toBe("on");
  });

  it("returns a dash for empty/nullish", () => {
    expect(formatState(null)).toBe("—");
    expect(formatState("")).toBe("—");
  });
});

import { formatBytes } from "@/lib/utils";

describe("formatBytes", () => {
  it("formats byte sizes", async () => {
    await i18n.changeLanguage("en");
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(2 * 1024 * 1024 * 1024)).toBe("2 GB");
  });
  it("returns dash for nullish", () => {
    expect(formatBytes(null)).toBe("—");
  });
});
