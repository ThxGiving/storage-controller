import { describe, expect, it } from "vitest";
import { resolveInitialLanguage, resources, NAMESPACES } from "@/i18n";
import { SUPPORTED_CODES } from "@/i18n/locales";

function fakeStorage(value: string | null): Storage {
  const store: Record<string, string> = {};
  if (value !== null) store["sc_language"] = value;
  return {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => {
      store[k] = v;
    },
    removeItem: (k: string) => {
      delete store[k];
    },
    clear: () => {},
    key: () => null,
    length: 0,
  } as Storage;
}

describe("language detection order", () => {
  it("prefers an explicit stored preference", () => {
    expect(resolveInitialLanguage(fakeStorage("de"), "en-US")).toBe("de");
  });

  it("uses Home Assistant language before the browser when no preference", () => {
    expect(resolveInitialLanguage(fakeStorage(null), "en-US", "de-DE")).toBe("de");
  });

  it("falls back to the browser language", () => {
    expect(resolveInitialLanguage(fakeStorage(null), "de-DE")).toBe("de");
  });

  it("falls back to English for unsupported languages", () => {
    expect(resolveInitialLanguage(fakeStorage(null), "fr-FR")).toBe("en");
  });

  it("treats the system sentinel as no explicit preference", () => {
    expect(resolveInitialLanguage(fakeStorage("system"), "de-DE")).toBe("de");
  });
});

describe("translation completeness", () => {
  it("supports exactly the registered locales", () => {
    expect(SUPPORTED_CODES).toEqual(["en", "de"]);
  });

  it("every English key has a German translation", () => {
    const flatten = (obj: unknown, prefix = ""): string[] => {
      if (typeof obj !== "object" || obj === null) return [prefix];
      return Object.entries(obj).flatMap(([k, v]) =>
        flatten(v, prefix ? `${prefix}.${k}` : k),
      );
    };

    for (const ns of NAMESPACES) {
      const enKeys = flatten(resources.en[ns]).sort();
      const deKeys = flatten(resources.de[ns]).sort();
      expect(deKeys, `namespace "${ns}" differs between en and de`).toEqual(enKeys);
    }
  });
});
