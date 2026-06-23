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

/** Theme follows Home Assistant / OS (prefers-color-scheme) by default — and
 *  follows it live — until the user explicitly picks one here (then persisted). */
export function ThemeToggle() {
  const [dark, setDark] = React.useState(() =>
    document.documentElement.classList.contains("dark"),
  );

  const apply = React.useCallback((v: boolean) => {
    document.documentElement.classList.toggle("dark", v);
    setDark(v);
  }, []);

  React.useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const onChange = (e: MediaQueryListEvent) => {
      if (readPref() === null) apply(e.matches); // only when the user hasn't overridden
    };
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
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
