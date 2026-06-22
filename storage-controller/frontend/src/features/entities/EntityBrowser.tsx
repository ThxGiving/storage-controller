import * as React from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Search, RefreshCw, AlertCircle } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { HAEntity } from "@/lib/types";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { formatState, timeAgo } from "@/lib/utils";

export function EntityBrowser() {
  const { t } = useTranslation(["entities", "errors"]);
  const [search, setSearch] = React.useState("");

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ["entities"],
    queryFn: () => api.getEntities(),
    refetchInterval: 15000,
  });

  const filtered = React.useMemo<HAEntity[]>(() => {
    const list = data ?? [];
    const q = search.trim().toLowerCase();
    if (!q) return list;
    return list.filter(
      (e) =>
        e.entity_id.toLowerCase().includes(q) ||
        (e.friendly_name ?? "").toLowerCase().includes(q),
    );
  }, [data, search]);

  const errorMessage =
    error instanceof ApiError ? t(`errors:${error.code}`) : (error as Error)?.message;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{t("entities:title")}</h1>
          <p className="text-sm text-muted-foreground">
            {data ? t("entities:count", { count: data.length }) : t("entities:loading")}
            {data ? ` · ${t("entities:shown", { count: filtered.length })}` : ""}
          </p>
        </div>
        <div className="relative w-full max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("entities:searchPlaceholder")}
            className="pl-9"
          />
        </div>
      </div>

      {isError && (
        <Card className="flex items-center gap-3 border-danger/40 p-4 text-sm text-danger">
          <AlertCircle className="h-5 w-5 shrink-0" />
          <span>{t("entities:loadError", { message: errorMessage })}</span>
        </Card>
      )}

      {!isError && data && data.length === 0 && (
        <Card className="flex flex-col items-center gap-2 p-10 text-center">
          <RefreshCw
            className={`h-6 w-6 text-muted-foreground ${isFetching ? "animate-spin" : ""}`}
          />
          <p className="text-sm text-muted-foreground">{t("entities:emptyHint")}</p>
        </Card>
      )}

      {filtered.length > 0 && (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="px-4 py-3 font-medium">{t("entities:col.entity")}</th>
                  <th className="px-4 py-3 font-medium">{t("entities:col.domain")}</th>
                  <th className="px-4 py-3 font-medium">{t("entities:col.state")}</th>
                  <th className="px-4 py-3 font-medium">{t("entities:col.device")}</th>
                  <th className="px-4 py-3 font-medium">{t("entities:col.last")}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.slice(0, 300).map((e) => (
                  <tr
                    key={e.entity_id}
                    className="border-b border-border/60 last:border-0 hover:bg-accent/40"
                  >
                    <td className="px-4 py-2.5">
                      <div className="font-medium">{e.friendly_name ?? e.entity_id}</div>
                      <div className="font-mono text-xs text-muted-foreground">
                        {e.entity_id}
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge tone="neutral">{e.domain}</Badge>
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge tone={e.available ? "ok" : "danger"}>
                        {formatState(e.state)}
                        {e.unit_of_measurement && e.available
                          ? ` ${e.unit_of_measurement}`
                          : ""}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-muted-foreground">
                      {e.device_name ?? "—"}
                    </td>
                    <td className="px-4 py-2.5 text-muted-foreground">
                      {timeAgo(e.last_changed)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {filtered.length > 300 && (
            <div className="border-t border-border px-4 py-2 text-center text-xs text-muted-foreground">
              {t("entities:moreHidden", { count: filtered.length - 300 })}
            </div>
          )}
        </Card>
      )}

      {isLoading && (
        <Card className="p-10 text-center text-sm text-muted-foreground">
          {t("entities:loading")}
        </Card>
      )}
    </div>
  );
}
