import * as React from "react";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";

const KEY = "sc-theme";

function readPref(): "dark" | "light" | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === "dark" || v === "light" ? v : null;
  } catch {
    return null;
  }
}

/** Read HA's current dark-mode flag from the parent window.
 *  Returns null when not in HA, cross-origin, or HA hasn't decided yet. */
function readHaDark(): boolean | null {
  try {
    if (window.parent === window) return null;
    const ha = window.parent.document.querySelector("home-assistant") as any;
    if (ha?.hass?.themes?.darkMode != null) return ha.hass.themes.darkMode as boolean;
    if (ha?.hass?.selectedTheme?.dark != null) return ha.hass.selectedTheme.dark as boolean;
    const cs = window.parent.document.documentElement.style.colorScheme;
    if (cs === "dark") return true;
    if (cs === "light") return false;
  } catch {
    // cross-origin or HA API unavailable
  }
  return null;
}

/** Theme follows HA dark-mode flag, then OS prefers-color-scheme — unless
 *  the user explicitly picks one via the toggle (persisted in localStorage). */
export function ThemeToggle() {
  const [dark, setDark] = React.useState(() =>
    document.documentElement.classList.contains("dark"),
  );

  const apply = React.useCallback((v: boolean) => {
    document.documentElement.classList.toggle("dark", v);
    setDark(v);
  }, []);

  // Re-sync with HA when the parent window changes its theme.
  // MutationObserver on parent <html> catches HA's style attribute updates.
  React.useEffect(() => {
    if (readPref() !== null) return; // user has manual override — don't touch it

    // Initial sync (index.html script may have run before HA was ready)
    const haDark = readHaDark();
    if (haDark != null) apply(haDark);

    // Watch HA theme changes at runtime
    let observer: MutationObserver | null = null;
    try {
      if (window.parent !== window) {
        observer = new MutationObserver(() => {
          if (readPref() !== null) return;
          const next = readHaDark();
          if (next != null) apply(next);
        });
        observer.observe(window.parent.document.documentElement, {
          attributes: true,
          attributeFilter: ["style", "class"],
        });
      }
    } catch {
      // cross-origin — fall back to OS media query
    }

    // OS media query as fallback when HA detection isn't available
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const onMqChange = (e: MediaQueryListEvent) => {
      if (readPref() !== null) return;
      if (readHaDark() == null) apply(e.matches);
    };
    mq?.addEventListener?.("change", onMqChange);

    return () => {
      observer?.disconnect();
      mq?.removeEventListener?.("change", onMqChange);
    };
  }, [apply]);

  const toggle = () => {
    const v = !dark;
    apply(v);
    try {
      localStorage.setItem(KEY, v ? "dark" : "light");
    } catch {
      /* preference simply won't persist (restricted iframe) */
    }
  };

  return (
    <Button variant="ghost" size="icon" onClick={toggle} aria-label="Theme wechseln">
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}
