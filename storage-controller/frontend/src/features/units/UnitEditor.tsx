import * as React from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Sparkles } from "lucide-react";
import {
  ENTITY_ROLES,
  STORAGE_UNIT_TYPES,
  type EntityRole,
  type HAEntity,
  type MonitoringProfile,
  type StorageUnit,
  type StorageUnitInput,
  type StorageUnitType,
} from "@/lib/types";
import { parseDecimal } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { Badge } from "@/components/ui/badge";
import { EntitySelect } from "@/features/entities/EntitySelect";
import { ROLE_SUGGESTED } from "./roleFilters";

interface UnitEditorProps {
  open: boolean;
  onClose: () => void;
  entities: HAEntity[];
  profiles: MonitoringProfile[];
  unit?: StorageUnit | null;
  onSubmit: (input: StorageUnitInput) => Promise<void>;
  submitting?: boolean;
}

type AssignmentMap = Partial<Record<EntityRole, string>>;

export function UnitEditor({
  open,
  onClose,
  entities,
  profiles,
  unit,
  onSubmit,
  submitting,
}: UnitEditorProps) {
  const { t } = useTranslation(["storage-units", "common", "profiles", "validation"]);

  const [name, setName] = React.useState("");
  const [shortName, setShortName] = React.useState("");
  const [location, setLocation] = React.useState("");
  const [unitType, setUnitType] = React.useState<StorageUnitType>("custom");
  const [profileId, setProfileId] = React.useState<string>("");
  const [appliedProfile, setAppliedProfile] = React.useState<{
    key: string | null;
    name: string | null;
  }>({ key: null, name: null });
  const [lower, setLower] = React.useState<string>("");
  const [upper, setUpper] = React.useState<string>("");
  const [warnMargin, setWarnMargin] = React.useState<string>("0");
  const [violationDelay, setViolationDelay] = React.useState<string>("15");
  const [recoveryDelay, setRecoveryDelay] = React.useState<string>("5");
  const [assignments, setAssignments] = React.useState<AssignmentMap>({});
  const [error, setError] = React.useState<string | null>(null);

  // Defrost-aware evaluation (single toggle; operational characteristics are
  // learned automatically and never set by hand here).
  const [defrostEnabled, setDefrostEnabled] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    if (unit) {
      setName(unit.name);
      setShortName(unit.short_report_name ?? "");
      setLocation(unit.location ?? "");
      setUnitType(unit.unit_type);
      setLower(unit.lower_limit_c?.toString() ?? "");
      setUpper(unit.upper_limit_c?.toString() ?? "");
      setWarnMargin(unit.warning_margin_c.toString());
      setViolationDelay(Math.round(unit.violation_delay_seconds / 60).toString());
      setRecoveryDelay(Math.round(unit.recovery_delay_seconds / 60).toString());
      setAppliedProfile({
        key: unit.applied_profile_key,
        name: unit.applied_profile_name,
      });
      const map: AssignmentMap = {};
      unit.assignments.forEach((a) => (map[a.role] = a.entity_id));
      setAssignments(map);
      setDefrostEnabled(unit.defrost_evaluation_enabled);
    } else {
      setName("");
      setShortName("");
      setLocation("");
      setUnitType("custom");
      setLower("");
      setUpper("");
      setWarnMargin("0");
      setViolationDelay("15");
      setRecoveryDelay("5");
      setAssignments({});
      setAppliedProfile({ key: null, name: null });
      setDefrostEnabled(false);
    }
    setProfileId("");
    setError(null);
  }, [open, unit]);

  const profileLabel = (p: MonitoringProfile) =>
    p.key ? t(`profiles:presets.${p.key}`, { defaultValue: p.name }) : p.name;

  const applyProfile = () => {
    const p = profiles.find((x) => String(x.id) === profileId);
    if (!p) return;
    // Copy the profile's current values into the unit (snapshot semantics).
    setLower(p.lower_limit_c?.toString() ?? "");
    setUpper(p.upper_limit_c?.toString() ?? "");
    setWarnMargin(p.warning_margin_c.toString());
    setViolationDelay(Math.round(p.violation_delay_seconds / 60).toString());
    setRecoveryDelay(Math.round(p.recovery_delay_seconds / 60).toString());
    setAppliedProfile({ key: p.key, name: profileLabel(p) });
  };

  const setRole = (role: EntityRole, entityId: string) =>
    setAssignments((prev) => {
      const next = { ...prev };
      if (entityId) next[role] = entityId;
      else delete next[role];
      return next;
    });

  const validate = (): string | null => {
    if (!name.trim()) return t("validation:nameRequired");
    if (!assignments.room_temperature) return t("validation:roomTemperatureRequired");
    const lo = parseDecimal(lower);
    const hi = parseDecimal(upper);
    if (lo != null && hi != null && lo >= hi) return t("validation:invalidLimits");
    return null;
  };

  const hasDefrostEntity = Boolean(assignments.defrost);

  const handleSubmit = async () => {
    const err = validate();
    if (err) {
      setError(err);
      return;
    }
    const input: StorageUnitInput = {
      name: name.trim(),
      short_report_name: shortName.trim() || null,
      location: location.trim() || null,
      unit_type: unitType,
      lower_limit_c: parseDecimal(lower),
      upper_limit_c: parseDecimal(upper),
      warning_margin_c: parseDecimal(warnMargin) ?? 0,
      violation_delay_seconds: Math.round((parseDecimal(violationDelay) ?? 0) * 60),
      recovery_delay_seconds: Math.round((parseDecimal(recoveryDelay) ?? 0) * 60),
      applied_profile_key: appliedProfile.key,
      applied_profile_name: appliedProfile.name,
      // Only the toggle is user-set; the defrost entity must be assigned for it
      // to take effect. Operational characteristics are learned, never entered.
      defrost_evaluation_enabled: hasDefrostEntity ? defrostEnabled : false,
      assignments: ENTITY_ROLES.filter((r) => assignments[r]).map((r) => ({
        role: r,
        entity_id: assignments[r]!,
      })),
    };
    try {
      await onSubmit(input);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={
        unit
          ? t("storage-units:editor.titleEdit", { name: unit.name })
          : t("storage-units:editor.titleNew")
      }
    >
      <div className="flex flex-col gap-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={`${t("storage-units:editor.name")} *`}>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("storage-units:editor.namePlaceholder")}
            />
          </Field>
          <Field label={t("storage-units:editor.shortReportName")}>
            <Input value={shortName} onChange={(e) => setShortName(e.target.value)} />
          </Field>
          <Field label={t("storage-units:editor.location")}>
            <Input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder={t("storage-units:editor.locationPlaceholder")}
            />
          </Field>
          <Field label={t("storage-units:editor.type")}>
            <select
              value={unitType}
              onChange={(e) => setUnitType(e.target.value as StorageUnitType)}
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {STORAGE_UNIT_TYPES.map((ty) => (
                <option key={ty} value={ty}>
                  {t(`profiles:types.${ty}`)}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <div>
          <h4 className="mb-2 text-sm font-semibold">
            {t("storage-units:editor.typeAndProfile")}
          </h4>
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[220px] flex-1">
              <Label>{t("storage-units:editor.profile")}</Label>
              <select
                value={profileId}
                onChange={(e) => setProfileId(e.target.value)}
                className="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <option value="">{t("storage-units:editor.profileNone")}</option>
                {profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {profileLabel(p)}
                  </option>
                ))}
              </select>
            </div>
            <Button variant="secondary" onClick={applyProfile} disabled={!profileId}>
              <Sparkles className="h-4 w-4" />
              {t("storage-units:editor.applyProfile")}
            </Button>
          </div>
          <p className="mt-1.5 text-xs text-muted-foreground">
            {t("storage-units:editor.profileHint")}
          </p>
          {appliedProfile.name && (
            <Badge tone="info" className="mt-2">
              {appliedProfile.name}
            </Badge>
          )}
        </div>

        <div>
          <h4 className="mb-2 text-sm font-semibold">
            {t("storage-units:editor.limitsTiming")}
          </h4>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label={t("storage-units:editor.lowerLimit")}>
              <Input value={lower} onChange={(e) => setLower(e.target.value)} inputMode="decimal" placeholder="0" />
            </Field>
            <Field label={t("storage-units:editor.upperLimit")}>
              <Input value={upper} onChange={(e) => setUpper(e.target.value)} inputMode="decimal" placeholder="8" />
            </Field>
            <Field label={t("storage-units:editor.warningMargin")}>
              <Input value={warnMargin} onChange={(e) => setWarnMargin(e.target.value)} inputMode="decimal" />
            </Field>
            <Field label={t("storage-units:editor.violationDelay")}>
              <Input value={violationDelay} onChange={(e) => setViolationDelay(e.target.value)} inputMode="numeric" />
            </Field>
            <Field label={t("storage-units:editor.recoveryDelay")}>
              <Input value={recoveryDelay} onChange={(e) => setRecoveryDelay(e.target.value)} inputMode="numeric" />
            </Field>
          </div>
        </div>

        <div>
          <label
            className={`flex items-center gap-2 text-sm font-semibold ${
              hasDefrostEntity ? "" : "opacity-60"
            }`}
          >
            <input
              type="checkbox"
              checked={hasDefrostEntity && defrostEnabled}
              disabled={!hasDefrostEntity}
              onChange={(e) => setDefrostEnabled(e.target.checked)}
              className="h-4 w-4 rounded border-input"
            />
            {t("storage-units:editor.defrostSection")}
          </label>
          <p className="mt-1 text-xs text-muted-foreground">
            {hasDefrostEntity
              ? t("storage-units:editor.defrostHint")
              : t("storage-units:editor.defrostNoEntity")}
          </p>
        </div>

        <div>
          <h4 className="mb-2 text-sm font-semibold">
            {t("storage-units:editor.entityAssignment")}
          </h4>
          <div className="flex flex-col gap-3">
            {ENTITY_ROLES.map((role) => (
              <div key={role} className="grid items-start gap-2 sm:grid-cols-[180px_1fr]">
                <Label className="pt-2.5">
                  {t(`storage-units:roles.${role}`)}
                  {role === "room_temperature" && <span className="text-danger"> *</span>}
                </Label>
                <EntitySelect
                  value={assignments[role] ?? ""}
                  entities={entities}
                  onChange={(id) => setRole(role, id)}
                  suggestedFilter={ROLE_SUGGESTED[role]}
                  allowClear={role !== "room_temperature"}
                />
              </div>
            ))}
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-border pt-4">
          <Button variant="outline" onClick={onClose}>
            {t("common:actions.cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting
              ? t("common:actions.saving")
              : unit
                ? t("common:actions.save")
                : t("common:actions.create")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}
