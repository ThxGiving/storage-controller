import * as React from "react";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "ok" | "warn" | "danger" | "info";

const tones: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground",
  ok: "bg-ok/15 text-ok ring-1 ring-inset ring-ok/30",
  warn: "bg-warn/15 text-warn ring-1 ring-inset ring-warn/30",
  danger: "bg-danger/15 text-danger ring-1 ring-inset ring-danger/30",
  info: "bg-info/15 text-info ring-1 ring-inset ring-info/30",
};

export function Badge({
  tone = "neutral",
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium",
        tones[tone],
        className,
      )}
      {...props}
    />
  );
}
