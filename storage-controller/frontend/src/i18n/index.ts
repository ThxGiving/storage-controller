import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import {
  DEFAULT_LOCALE,
  FALLBACK_LOCALE,
  LANGUAGE_STORAGE_KEY,
  SUPPORTED_CODES,
  SYSTEM_LANGUAGE,
} from "./locales";

import enCommon from "./en/common.json";
import enNavigation from "./en/navigation.json";
import enDashboard from "./en/dashboard.json";
import enStorageUnits from "./en/storage-units.json";
import enEntities from "./en/entities.json";
import enProfiles from "./en/profiles.json";
import enSettings from "./en/settings.json";
import enValidation from "./en/validation.json";
import enErrors from "./en/errors.json";

import deCommon from "./de/common.json";
import deNavigation from "./de/navigation.json";
import deDashboard from "./de/dashboard.json";
import deStorageUnits from "./de/storage-units.json";
import deEntities from "./de/entities.json";
import deProfiles from "./de/profiles.json";
import deSettings from "./de/settings.json";
import deValidation from "./de/validation.json";
import deErrors from "./de/errors.json";

export const NAMESPACES = [
  "common",
  "navigation",
  "dashboard",
  "storage-units",
  "entities",
  "profiles",
  "settings",
  "validation",
  "errors",
] as const;

export const resources = {
  en: {
    common: enCommon,
    navigation: enNavigation,
    dashboard: enDashboard,
    "storage-units": enStorageUnits,
    entities: enEntities,
    profiles: enProfiles,
    settings: enSettings,
    validation: enValidation,
    errors: enErrors,
  },
  de: {
    common: deCommon,
    navigation: deNavigation,
    dashboard: deDashboard,
    "storage-units": deStorageUnits,
    entities: deEntities,
    profiles: deProfiles,
    settings: deSettings,
    validation: deValidation,
    errors: deErrors,
  },
} as const;

/**
 * Resolve the initial language in this order:
 *   1. explicit Storage Controller user preference (localStorage)
 *   2. trusted Home Assistant / Ingress language (when available — best effort)
 *   3. browser language
 *   4. English fallback
 */
export function resolveInitialLanguage(
  storage: Storage = window.localStorage,
  navLang: string = navigator.language,
  haLang?: string | null,
): string {
  const stored = storage.getItem(LANGUAGE_STORAGE_KEY);
  if (stored && stored !== SYSTEM_LANGUAGE && SUPPORTED_CODES.includes(stored)) {
    return stored;
  }
  if (!stored || stored === SYSTEM_LANGUAGE) {
    const ha = (haLang ?? "").slice(0, 2).toLowerCase();
    if (ha && SUPPORTED_CODES.includes(ha)) return ha;
    const browser = (navLang ?? "").slice(0, 2).toLowerCase();
    if (browser && SUPPORTED_CODES.includes(browser)) return browser;
  }
  return DEFAULT_LOCALE;
}

export function setLanguagePreference(language: string): void {
  if (language === SYSTEM_LANGUAGE) {
    window.localStorage.removeItem(LANGUAGE_STORAGE_KEY);
    i18n.changeLanguage(resolveInitialLanguage());
  } else {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
    i18n.changeLanguage(language);
  }
}

export function getStoredPreference(): string {
  return window.localStorage.getItem(LANGUAGE_STORAGE_KEY) ?? SYSTEM_LANGUAGE;
}

i18n.use(initReactI18next).init({
  resources,
  lng: resolveInitialLanguage(),
  fallbackLng: FALLBACK_LOCALE,
  supportedLngs: SUPPORTED_CODES,
  ns: NAMESPACES as unknown as string[],
  defaultNS: "common",
  interpolation: { escapeValue: false },
  // In development, surface missing keys; in production fall back silently.
  saveMissing: false,
  returnNull: false,
});

export default i18n;
