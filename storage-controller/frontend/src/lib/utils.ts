import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import i18n from "@/i18n";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

function currentLocale(): string {
  return i18n.language || "en";
}

/** Locale-aware number formatting (German uses "," decimal / "." grouping). */
export function formatNumber(
  value: number | null | undefined,
  options?: Intl.NumberFormatOptions,
): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat(currentLocale(), options).format(value);
}

/** Format a temperature value with its unit, locale-aware. */
export function formatTemperature(
  value: number | string | null | undefined,
  unit = "°C",
): string {
  if (value == null || value === "") return "—";
  const num = typeof value === "string" ? Number(value.replace(",", ".")) : value;
  if (Number.isNaN(num)) return String(value);
  return `${formatNumber(num, { maximumFractionDigits: 1 })} ${unit}`;
}

/**
 * Parse a user-entered decimal, accepting both English ("4.5") and German
 * ("4,5") punctuation. Returns null for empty/invalid input.
 */
export function parseDecimal(input: string): number | null {
  const trimmed = input.trim();
  if (trimmed === "") return null;
  const normalized = trimmed.replace(/\s/g, "").replace(",", ".");
  const num = Number(normalized);
  return Number.isNaN(num) ? null : num;
}

/** Locale-aware short date-time, or "—". */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(currentLocale(), {
    dateStyle: "short",
    timeStyle: "short",
  });
}

/** Relative "x ago" formatting using the locale's RelativeTimeFormat. */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso).getTime();
  if (Number.isNaN(d)) return "—";
  const rtf = new Intl.RelativeTimeFormat(currentLocale(), { numeric: "auto" });
  const secs = Math.round((d - Date.now()) / 1000);
  const abs = Math.abs(secs);
  if (abs < 60) return rtf.format(Math.round(secs), "second");
  const mins = Math.round(secs / 60);
  if (Math.abs(mins) < 60) return rtf.format(mins, "minute");
  const hours = Math.round(mins / 60);
  if (Math.abs(hours) < 24) return rtf.format(hours, "hour");
  return rtf.format(Math.round(hours / 24), "day");
}
