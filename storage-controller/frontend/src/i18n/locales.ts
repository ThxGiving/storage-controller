/**
 * Central locale registry.
 *
 * Add a new language here (and its resource bundles) without touching business
 * logic elsewhere. English is the source and fallback language.
 */
export interface LocaleDef {
  code: string;
  /** Native name shown in the language selector. */
  nativeName: string;
}

export const SUPPORTED_LOCALES: LocaleDef[] = [
  { code: "en", nativeName: "English" },
  { code: "de", nativeName: "Deutsch" },
];

export const DEFAULT_LOCALE = "en";
export const FALLBACK_LOCALE = "en";

/** localStorage key holding an explicit user language preference. */
export const LANGUAGE_STORAGE_KEY = "sc_language";
/** Sentinel meaning "follow system / Home Assistant / browser". */
export const SYSTEM_LANGUAGE = "system";

export const SUPPORTED_CODES = SUPPORTED_LOCALES.map((l) => l.code);
