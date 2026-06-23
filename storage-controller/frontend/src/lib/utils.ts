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

/**
 * Format a Home Assistant state for display. Numeric states (e.g. a raw sensor
 * float like "5.90000009536743") are rounded and locale-formatted; non-numeric
 * states (on/off, unavailable, text) are returned unchanged.
 */
export function formatState(
  state: string | null | undefined,
  maxFractionDigits = 2,
): string {
  if (state == null || state === "") return "—";
  const trimmed = state.trim();
  // Only treat clean numeric strings as numbers (avoid "123abc", dates, etc.).
  if (/^-?\d*\.?\d+$/.test(trimmed)) {
    return formatNumber(Number(trimmed), { maximumFractionDigits: maxFractionDigits });
  }
  return state;
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

/** Human-readable byte size (locale-aware number). */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || Number.isNaN(bytes)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${formatNumber(v, { maximumFractionDigits: v < 10 && i > 0 ? 1 : 0 })} ${units[i]}`;
}

/** Compact duration between two ISO timestamps (end defaults to now). */
export function formatDuration(
  start: string | null | undefined,
  end?: string | null,
): string {
  if (!start) return "—";
  const s = new Date(start).getTime();
  const e = end ? new Date(end).getTime() : Date.now();
  if (Number.isNaN(s) || Number.isNaN(e)) return "—";
  let secs = Math.max(0, Math.round((e - s) / 1000));
  const d = Math.floor(secs / 86400);
  secs -= d * 86400;
  const h = Math.floor(secs / 3600);
  secs -= h * 3600;
  const m = Math.floor(secs / 60);
  const parts: string[] = [];
  if (d) parts.push(`${d}d`);
  if (h) parts.push(`${h}h`);
  if (m || (!d && !h)) parts.push(`${m}min`);
  return parts.join(" ");
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
