import * as React from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Plus, Snowflake } from "lucide-react";
import { api } from "@/lib/api";
import type { DashboardUnit } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { DashboardHeader } from "@/components/dashboard/DashboardHeader";
import { StorageUnitStatusCard } from "@/components/dashboard/StorageUnitStatusCard";
import { UnitDetail } from "@/features/units/UnitDetail";

export function Dashboard({ onNavigateToUnits }: { onNavigateToUnits: () => void }) {
  const { t } = useTranslation("dashboard");
  const [selectedId, setSelectedId] = React.useState<number | null>(null);

  const query = useQuery({
    queryKey: ["dashboard"],
    queryFn: api.getDashboard,
    refetchInterval: 10000,
  });

  const data = query.data;

  // Detail view (kept in sync with refetched data).
  const selectedUnit = data?.units.find((u) => u.id === selectedId) ?? null;
  if (selectedId != null && selectedUnit) {
    return <UnitDetail unit={selectedUnit} onBack={() => setSelectedId(null)} />;
  }

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-semibold">{t("title")}</h1>
        <p className="text-sm text-muted-foreground">{t("subtitle")}</p>
      </div>

      {query.isLoading && <DashboardSkeleton />}

      {query.isError && (
        <Card className="flex items-center justify-between gap-3 border-danger/40 p-4">
          <span className="flex items-center gap-2 text-sm text-danger">
            <AlertCircle className="h-5 w-5" /> {t("error.title")}
          </span>
          <Button variant="outline" size="sm" onClick={() => query.refetch()}>
            {t("error.retry")}
          </Button>
        </Card>
      )}

      {data && (
        <>
          <DashboardHeader
            data={data}
            onRefresh={() => query.refetch()}
            refreshing={query.isFetching}
          />

          {data.units.length === 0 ? (
            <Card className="flex flex-col items-center gap-3 p-12 text-center">
              <div className="grid h-12 w-12 place-items-center rounded-full bg-primary/15 text-primary">
                <Snowflake className="h-6 w-6" />
              </div>
              <div>
                <p className="font-medium">{t("empty.title")}</p>
                <p className="text-sm text-muted-foreground">{t("empty.hint")}</p>
              </div>
              <Button onClick={onNavigateToUnits}>
                <Plus className="h-4 w-4" /> {t("empty.action")}
              </Button>
            </Card>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {data.units.map((unit: DashboardUnit) => (
                <StorageUnitStatusCard key={unit.id} unit={unit} onOpen={(u) => setSelectedId(u.id)} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="flex flex-col gap-5">
      <Skeleton className="h-32 w-full rounded-xl" />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-64 w-full rounded-xl" />
        ))}
      </div>
    </div>
  );
}
