import { useTranslation } from "react-i18next";
import { Wifi, WifiOff, RefreshCw, ShieldAlert } from "lucide-react";
import type { ConnectionState } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

const MAP: Record<
  ConnectionState,
  { tone: "ok" | "warn" | "danger" | "neutral"; Icon: typeof Wifi }
> = {
  connected: { tone: "ok", Icon: Wifi },
  reconnecting: { tone: "warn", Icon: RefreshCw },
  disconnected: { tone: "neutral", Icon: WifiOff },
  authentication_error: { tone: "danger", Icon: ShieldAlert },
};

export function StatusPill({ status }: { status: ConnectionState }) {
  const { t } = useTranslation("common");
  const { tone, Icon } = MAP[status] ?? MAP.disconnected;
  return (
    <Badge tone={tone}>
      <Icon className={`h-3.5 w-3.5 ${status === "reconnecting" ? "animate-spin" : ""}`} />
      {t(`status.${status}`)}
    </Badge>
  );
}
