import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  CloudOff,
  History,
  Wrench,
  WifiOff,
  type LucideIcon,
} from "lucide-react";
import type { OperationalStatus } from "./types";

export type Tone = "ok" | "warn" | "danger" | "neutral" | "info";

export interface StatusVisual {
  Icon: LucideIcon;
  tone: Tone;
  /** i18n key under the `dashboard:status` namespace. */
  i18nKey: string;
}

export const STATUS_VISUALS: Record<OperationalStatus, StatusVisual> = {
  normal: { Icon: CheckCircle2, tone: "ok", i18nKey: "normal" },
  near_limit: { Icon: AlertTriangle, tone: "warn", i18nKey: "near_limit" },
  outside_range: { Icon: AlertOctagon, tone: "danger", i18nKey: "outside_range" },
  unavailable: { Icon: CloudOff, tone: "neutral", i18nKey: "unavailable" },
  stale: { Icon: History, tone: "warn", i18nKey: "stale" },
  disconnected: { Icon: WifiOff, tone: "neutral", i18nKey: "disconnected" },
  configuration_error: { Icon: Wrench, tone: "danger", i18nKey: "configuration_error" },
};

export function qualityTone(quality: string | null | undefined): Tone {
  switch (quality) {
    case "valid":
      return "ok";
    case "implausible":
    case "stale":
      return "warn";
    case "invalid":
      return "danger";
    default:
      return "neutral";
  }
}

/** Tailwind text/border/bg helpers per tone (kept here so components stay terse). */
export const TONE_CLASSES: Record<Tone, { text: string; bg: string; ring: string; dot: string }> = {
  ok: { text: "text-ok", bg: "bg-ok/10", ring: "ring-ok/30", dot: "bg-ok" },
  warn: { text: "text-warn", bg: "bg-warn/10", ring: "ring-warn/30", dot: "bg-warn" },
  danger: { text: "text-danger", bg: "bg-danger/10", ring: "ring-danger/30", dot: "bg-danger" },
  info: { text: "text-info", bg: "bg-info/10", ring: "ring-info/30", dot: "bg-info" },
  neutral: {
    text: "text-muted-foreground",
    bg: "bg-muted",
    ring: "ring-border",
    dot: "bg-muted-foreground",
  },
};
