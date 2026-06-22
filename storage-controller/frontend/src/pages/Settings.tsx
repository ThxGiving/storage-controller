import * as React from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Languages, Palette, Info } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/input";
import {
  getStoredPreference,
  setLanguagePreference,
} from "@/i18n";
import { SUPPORTED_LOCALES, SYSTEM_LANGUAGE } from "@/i18n/locales";

export function SettingsPage() {
  const { t } = useTranslation(["settings", "common"]);
  const [pref, setPref] = React.useState(getStoredPreference());
  const statusQuery = useQuery({ queryKey: ["status"], queryFn: api.getStatus });

  const onLanguageChange = (value: string) => {
    setPref(value);
    setLanguagePreference(value);
  };

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-semibold">{t("settings:title")}</h1>
        <p className="text-sm text-muted-foreground">{t("settings:subtitle")}</p>
      </div>

      <Card>
        <CardHeader className="flex-row items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-primary/15 text-primary">
            <Languages className="h-5 w-5" />
          </div>
          <div>
            <CardTitle>{t("settings:language")}</CardTitle>
            <p className="text-sm text-muted-foreground">{t("settings:languageHint")}</p>
          </div>
        </CardHeader>
        <CardContent>
          <Label htmlFor="language">{t("settings:language")}</Label>
          <select
            id="language"
            value={pref}
            onChange={(e) => onLanguageChange(e.target.value)}
            className="mt-1.5 h-10 w-full max-w-xs rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value={SYSTEM_LANGUAGE}>{t("settings:languageSystem")}</option>
            {SUPPORTED_LOCALES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.nativeName}
              </option>
            ))}
          </select>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-accent text-muted-foreground">
            <Palette className="h-5 w-5" />
          </div>
          <div>
            <CardTitle>{t("settings:theme")}</CardTitle>
            <p className="text-sm text-muted-foreground">{t("settings:themeHint")}</p>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            {t("settings:demoData")}: {t("settings:demoHint")}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-accent text-muted-foreground">
            <Info className="h-5 w-5" />
          </div>
          <CardTitle>{t("settings:about")}</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {t("settings:version")}: {statusQuery.data?.version ?? "—"}
        </CardContent>
      </Card>
    </div>
  );
}
