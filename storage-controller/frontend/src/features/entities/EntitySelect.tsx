import * as React from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, Search, X } from "lucide-react";
import type { HAEntity } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

interface EntitySelectProps {
  value: string;
  entities: HAEntity[];
  onChange: (entityId: string) => void;
  onClear?: () => void;
  placeholder?: string;
  /** Entity ids that should be sorted to the top as sensible candidates. */
  suggestedFilter?: (e: HAEntity) => boolean;
  allowClear?: boolean;
}

/**
 * Searchable entity dropdown. Matches entity id and friendly name, shows domain,
 * current state and unit, prefers sensible candidates for the role, and still
 * allows entering an arbitrary entity id manually.
 */
export function EntitySelect({
  value,
  entities,
  onChange,
  onClear,
  placeholder,
  suggestedFilter,
  allowClear = true,
}: EntitySelectProps) {
  const { t } = useTranslation("entities");
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const selected = entities.find((e) => e.entity_id === value);

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    let list = entities;
    if (q) {
      list = list.filter(
        (e) =>
          e.entity_id.toLowerCase().includes(q) ||
          (e.friendly_name ?? "").toLowerCase().includes(q),
      );
    }
    if (suggestedFilter) {
      const score = (e: HAEntity) => (suggestedFilter(e) ? 0 : 1);
      list = [...list].sort((a, b) => score(a) - score(b));
    }
    return list.slice(0, 60);
  }, [entities, query, suggestedFilter]);

  const manualMatch =
    query.includes(".") &&
    !entities.some((e) => e.entity_id === query.trim());

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex h-10 w-full items-center justify-between gap-2 rounded-md border border-input bg-background px-3 text-sm",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          {value ? (
            <span className="truncate font-mono text-xs">{value}</span>
          ) : (
            <span className="text-muted-foreground">
              {placeholder ?? t("select.placeholder")}
            </span>
          )}
        </span>
        <span className="flex items-center gap-1">
          {value && allowClear && (
            <X
              className="h-4 w-4 text-muted-foreground hover:text-foreground"
              onClick={(e) => {
                e.stopPropagation();
                onClear ? onClear() : onChange("");
              }}
            />
          )}
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        </span>
      </button>

      {selected && (
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          {selected.friendly_name && <span>{selected.friendly_name}</span>}
          {selected.state != null && (
            <Badge tone={selected.available ? "info" : "danger"}>
              {selected.state}
              {selected.unit_of_measurement ? ` ${selected.unit_of_measurement}` : ""}
            </Badge>
          )}
          {selected.device_name && <span>· {selected.device_name}</span>}
        </div>
      )}

      {open && (
        <div className="absolute z-30 mt-1 w-full overflow-hidden rounded-md border border-border bg-card shadow-card">
          <div className="flex items-center gap-2 border-b border-border px-3">
            <Search className="h-4 w-4 text-muted-foreground" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("select.searchPlaceholder")}
              className="h-10 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
          </div>
          <div className="max-h-72 overflow-y-auto py-1">
            {manualMatch && (
              <button
                type="button"
                onClick={() => {
                  onChange(query.trim());
                  setOpen(false);
                  setQuery("");
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent"
              >
                <span className="text-muted-foreground">{t("select.manualUse")}</span>
                <span className="font-mono text-xs">{query.trim()}</span>
              </button>
            )}
            {filtered.length === 0 && !manualMatch && (
              <div className="px-3 py-6 text-center text-sm text-muted-foreground">
                {t("select.noResults")}
              </div>
            )}
            {filtered.map((e) => (
              <button
                key={e.entity_id}
                type="button"
                onClick={() => {
                  onChange(e.entity_id);
                  setOpen(false);
                  setQuery("");
                }}
                className={cn(
                  "flex w-full flex-col gap-0.5 px-3 py-2 text-left hover:bg-accent",
                  e.entity_id === value && "bg-accent",
                )}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">
                    {e.friendly_name ?? e.entity_id}
                  </span>
                  <Badge tone="neutral">{e.domain}</Badge>
                </span>
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="truncate font-mono">{e.entity_id}</span>
                  {e.state != null && (
                    <span className="shrink-0">
                      {e.state}
                      {e.unit_of_measurement ? ` ${e.unit_of_measurement}` : ""}
                    </span>
                  )}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
