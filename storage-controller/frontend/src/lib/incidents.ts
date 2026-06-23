import {
  AlertOctagon,
  AlertTriangle,
  CloudOff,
  HelpCircle,
  History,
  Snowflake,
  Timer,
  WifiOff,
  type LucideIcon,
} from "lucide-react";
import type { Tone } from "./status";

export interface IncidentVisual {
  Icon: LucideIcon;
  tone: Tone;
}

export const INCIDENT_VISUALS: Record<string, IncidentVisual> = {
  temperature_high: { Icon: AlertOctagon, tone: "danger" },
  temperature_low: { Icon: AlertOctagon, tone: "danger" },
  sensor_unavailable: { Icon: CloudOff, tone: "neutral" },
  sensor_stale: { Icon: History, tone: "warn" },
  sensor_invalid: { Icon: AlertTriangle, tone: "warn" },
  home_assistant_disconnected: { Icon: WifiOff, tone: "neutral" },
  abnormal_defrost: { Icon: Snowflake, tone: "warn" },
  recovery_timeout: { Icon: Timer, tone: "danger" },
};

export function incidentVisual(type: string): IncidentVisual {
  return INCIDENT_VISUALS[type] ?? { Icon: HelpCircle, tone: "neutral" };
}

const STATE_TONE: Record<string, Tone> = {
  pending_violation: "warn",
  active_violation: "danger",
  recovering: "info",
  closed: "neutral",
};

export function incidentStateTone(state: string): Tone {
  return STATE_TONE[state] ?? "neutral";
}
