import { useTranslation } from "react-i18next";
import {
  Bell,
  Cpu,
  DoorOpen,
  Droplets,
  Fan,
  Lightbulb,
  Snowflake,
  Thermometer,
  Gauge,
  type LucideIcon,
} from "lucide-react";
import { cn, formatNumber } from "@/lib/utils";
import type { DashboardRoleValue, EntityRole } from "@/lib/types";

const ROLE_ICON: Partial<Record<EntityRole, LucideIcon>> = {
  compressor: Snowflake,
  fan: Fan,
  defrost: Droplets,
  controller: Cpu,
  light: Lightbulb,
  door: DoorOpen,
  alarm: Bell,
  evaporator_temperature: Thermometer,
  setpoint: Gauge,
  hysteresis: Gauge,
};

const NUMERIC_ROLES = new Set<EntityRole>([
  "evaporator_temperature",
  "setpoint",
  "hysteresis",
]);

/**
 * Compact row of assigned operational states. Numeric roles show their value;
 * on/off roles show an active/inactive indicator with a text label (not color
 * only). Only assigned roles are rendered.
 */
export function OperationalStateStrip({
  roles,
  className,
}: {
  roles: DashboardRoleValue[];
  className?: string;
}) {
  const { t } = useTranslation(["storage-units", "dashboard"]);
  if (roles.length === 0) return null;

  return (
    <div className={cn("flex flex-wrap gap-1.5", className)}>
      {roles.map((r) => {
        const Icon = ROLE_ICON[r.role] ?? Gauge;
        const label = t(`storage-units:roles.${r.role}`);
        const numeric = NUMERIC_ROLES.has(r.role);
        const active = r.bool_value === true;
        const available = r.available && r.quality === "valid";

        let valueText: string;
        if (numeric) {
          valueText =
            r.numeric_c != null
              ? `${formatNumber(r.numeric_c, { maximumFractionDigits: 1 })}°`
              : "—";
        } else if (!available) {
          valueText = t("dashboard:state.unknown");
        } else {
          valueText = active ? t("dashboard:state.on") : t("dashboard:state.off");
        }

        return (
          <span
            key={`${r.role}-${r.entity_id}`}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border border-border px-1.5 py-1 text-[11px]",
              !numeric && active && available
                ? "border-primary/40 bg-primary/10 text-foreground"
                : "bg-card text-muted-foreground",
            )}
            title={`${label}: ${valueText}`}
          >
            <Icon
              className={cn(
                "h-3.5 w-3.5",
                !numeric && active && available ? "text-primary" : "",
              )}
              aria-hidden
            />
            <span className="font-medium">{label}</span>
            <span className="tabular-nums">{valueText}</span>
          </span>
        );
      })}
    </div>
  );
}
