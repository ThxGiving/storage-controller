import * as React from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, Snowflake, Thermometer } from "lucide-react";
import { api } from "@/lib/api";
import type { StorageUnit, StorageUnitInput } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatTemperature, formatNumber } from "@/lib/utils";
import { UnitEditor } from "./UnitEditor";

export function UnitsPage() {
  const { t } = useTranslation(["storage-units", "common"]);
  const qc = useQueryClient();
  const [editorOpen, setEditorOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<StorageUnit | null>(null);

  const unitsQuery = useQuery({ queryKey: ["units"], queryFn: api.listUnits });
  const entitiesQuery = useQuery({
    queryKey: ["entities"],
    queryFn: () => api.getEntities(),
  });
  const profilesQuery = useQuery({ queryKey: ["profiles"], queryFn: api.listProfiles });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["units"] });
    qc.invalidateQueries({ queryKey: ["status"] });
  };

  const createMut = useMutation({
    mutationFn: (input: StorageUnitInput) => api.createUnit(input),
    onSuccess: () => {
      invalidate();
      setEditorOpen(false);
    },
  });
  const updateMut = useMutation({
    mutationFn: ({ id, input }: { id: number; input: StorageUnitInput }) =>
      api.updateUnit(id, input),
    onSuccess: () => {
      invalidate();
      setEditorOpen(false);
    },
  });
  const deleteMut = useMutation({
    mutationFn: (id: number) => api.deleteUnit(id),
    onSuccess: invalidate,
  });

  const openCreate = () => {
    setEditing(null);
    setEditorOpen(true);
  };
  const openEdit = (unit: StorageUnit) => {
    setEditing(unit);
    setEditorOpen(true);
  };
  const handleSubmit = async (input: StorageUnitInput) => {
    if (editing) await updateMut.mutateAsync({ id: editing.id, input });
    else await createMut.mutateAsync(input);
  };

  const units = unitsQuery.data ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{t("storage-units:title")}</h1>
          <p className="text-sm text-muted-foreground">
            {t("storage-units:count", { count: units.length })}
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="h-4 w-4" /> {t("storage-units:newUnit")}
        </Button>
      </div>

      {units.length === 0 && !unitsQuery.isLoading && (
        <Card className="flex flex-col items-center gap-3 p-12 text-center">
          <div className="grid h-12 w-12 place-items-center rounded-full bg-primary/15 text-primary">
            <Snowflake className="h-6 w-6" />
          </div>
          <div>
            <p className="font-medium">{t("storage-units:emptyTitle")}</p>
            <p className="text-sm text-muted-foreground">{t("storage-units:emptyHint")}</p>
          </div>
          <Button onClick={openCreate}>
            <Plus className="h-4 w-4" /> {t("storage-units:createFirst")}
          </Button>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {units.map((unit) => (
          <UnitCard
            key={unit.id}
            unit={unit}
            onEdit={() => openEdit(unit)}
            onDelete={() => {
              if (confirm(t("storage-units:deleteConfirm", { name: unit.name })))
                deleteMut.mutate(unit.id);
            }}
          />
        ))}
      </div>

      <UnitEditor
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
        entities={entitiesQuery.data ?? []}
        profiles={profilesQuery.data ?? []}
        unit={editing}
        onSubmit={handleSubmit}
        submitting={createMut.isPending || updateMut.isPending}
      />
    </div>
  );
}

function UnitCard({
  unit,
  onEdit,
  onDelete,
}: {
  unit: StorageUnit;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation(["storage-units", "profiles"]);
  const currentQuery = useQuery({
    queryKey: ["unit-current", unit.id],
    queryFn: () => api.unitCurrent(unit.id),
    refetchInterval: 15000,
  });

  const room = currentQuery.data?.find((c) => c.role === "room_temperature");
  const warnings = (currentQuery.data ?? []).filter((c) => c.warning);

  return (
    <Card className="flex flex-col">
      <CardHeader className="flex-row items-start justify-between">
        <div>
          <CardTitle>{unit.name}</CardTitle>
          <p className="text-xs text-muted-foreground">
            {t(`profiles:types.${unit.unit_type}`)}
            {unit.location ? ` · ${unit.location}` : ""}
          </p>
        </div>
        <div className="flex gap-1">
          <Button variant="ghost" size="icon" onClick={onEdit} aria-label={t("storage-units:editor.name")}>
            <Pencil className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" onClick={onDelete} aria-label="delete">
            <Trash2 className="h-4 w-4 text-danger" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
        <div className="flex items-end gap-2">
          <Thermometer className="h-6 w-6 text-primary" />
          <span className="text-3xl font-semibold tabular-nums">
            {room?.state != null ? formatTemperature(room.state, "").trim() : "—"}
          </span>
          <span className="pb-1 text-sm text-muted-foreground">
            {room?.unit_of_measurement ?? "°C"}
          </span>
        </div>

        <div className="text-xs text-muted-foreground">
          {t("storage-units:card.range")}: {formatNumber(unit.lower_limit_c)} …{" "}
          {formatNumber(unit.upper_limit_c)} °C
        </div>

        <div className="flex flex-wrap gap-1.5">
          {unit.assignments.map((a) => (
            <Badge key={a.id} tone="neutral">
              {t(`storage-units:roles.${a.role}`)}
            </Badge>
          ))}
        </div>

        {warnings.length > 0 && (
          <div className="mt-auto rounded-md border border-warn/40 bg-warn/10 px-2.5 py-1.5 text-xs text-warn">
            {t("storage-units:card.hints", { count: warnings.length })}: {warnings[0].warning}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
