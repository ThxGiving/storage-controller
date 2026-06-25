import { useTranslation } from "react-i18next";
import {
  LayoutDashboard,
  Snowflake,
  List,
  Boxes,
  Settings,
  TriangleAlert,
  FileText,
  CalendarClock,
} from "lucide-react";
import { cn } from "@/lib/utils";

export type TabKey =
  | "overview"
  | "units"
  | "incidents"
  | "reports"
  | "schedules"
  | "entities"
  | "settings";

const NAV: { key: TabKey; i18nKey: string; Icon: typeof LayoutDashboard }[] = [
  { key: "overview", i18nKey: "overview", Icon: LayoutDashboard },
  { key: "units", i18nKey: "units", Icon: Boxes },
  { key: "incidents", i18nKey: "incidents", Icon: TriangleAlert },
  { key: "reports", i18nKey: "reports", Icon: FileText },
  { key: "schedules", i18nKey: "schedules", Icon: CalendarClock },
  { key: "entities", i18nKey: "entities", Icon: List },
  { key: "settings", i18nKey: "settings", Icon: Settings },
];

export function Sidebar({
  active,
  onSelect,
}: {
  active: TabKey;
  onSelect: (key: TabKey) => void;
}) {
  const { t } = useTranslation(["navigation", "common"]);
  return (
    <aside className="flex w-full shrink-0 flex-col gap-1 border-border bg-card/60 p-3 md:h-screen md:w-60 md:border-r">
      <div className="mb-4 flex items-center gap-2.5 px-2 pt-2">
        <div className="grid h-9 w-9 place-items-center rounded-lg bg-primary/15 text-primary">
          <Snowflake className="h-5 w-5" />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold">{t("common:brand.top")}</div>
          <div className="text-sm font-semibold text-primary">
            {t("common:brand.bottom")}
          </div>
        </div>
      </div>
      <nav className="flex gap-1 md:flex-col">
        {NAV.map(({ key, i18nKey, Icon }) => (
          <button
            key={key}
            onClick={() => onSelect(key)}
            className={cn(
              "flex flex-1 items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors md:flex-none",
              active === key
                ? "bg-primary/15 text-primary"
                : "text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            <Icon className="h-4 w-4" />
            <span>{t(`navigation:${i18nKey}`)}</span>
          </button>
        ))}
      </nav>
    </aside>
  );
}
