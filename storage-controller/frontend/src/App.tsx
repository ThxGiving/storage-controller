import * as React from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Sidebar, type TabKey } from "@/components/layout/Sidebar";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { StatusPill } from "@/components/layout/StatusPill";
import { StorageWarningBanner } from "@/components/layout/StorageWarningBanner";
import { Dashboard } from "@/pages/Dashboard";
import { EntityBrowser } from "@/features/entities/EntityBrowser";
import { UnitsPage } from "@/features/units/UnitsPage";
import { IncidentsPage } from "@/pages/Incidents";
import { SettingsPage } from "@/pages/Settings";

export default function App() {
  const { t } = useTranslation("common");
  const [tab, setTab] = React.useState<TabKey>("overview");

  const statusQuery = useQuery({
    queryKey: ["status"],
    queryFn: api.getStatus,
    refetchInterval: 10000,
  });
  const haStatus = statusQuery.data?.home_assistant.status;

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <Sidebar active={tab} onSelect={setTab} />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-border bg-card/40 px-5 py-3">
          <div className="text-sm font-medium text-muted-foreground">
            {t("appName")}
          </div>
          <div className="flex items-center gap-3">
            {haStatus && <StatusPill status={haStatus} />}
            <ThemeToggle />
          </div>
        </header>

        <StorageWarningBanner />

        <main className="mx-auto w-full max-w-6xl flex-1 animate-fade-in p-5 md:p-8">
          {tab === "overview" && <Dashboard onNavigateToUnits={() => setTab("units")} />}
          {tab === "units" && <UnitsPage />}
          {tab === "incidents" && <IncidentsPage />}
          {tab === "entities" && <EntityBrowser />}
          {tab === "settings" && <SettingsPage />}
        </main>
      </div>
    </div>
  );
}
