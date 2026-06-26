import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./i18n";
import "./index.css";

/**
 * Render a visible error instead of a blank page. Behind Home Assistant Ingress
 * the App runs in an iframe; if anything throws during startup we want the error
 * on screen (and in the console) rather than a white page.
 */
function showFatalError(error: unknown): void {
  const root = document.getElementById("root");
  if (!root) return;
  const message =
    error instanceof Error ? `${error.name}: ${error.message}` : String(error);
  const stack = error instanceof Error && error.stack ? error.stack : "";
  const detail = escapeHtml(message + (stack ? "\n\n" + stack : ""));
  root.innerHTML = `
    <div style="font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:24px;
                border:1px solid #f0a;border-radius:12px;background:#1b1020;color:#f6e9ff">
      <h2 style="margin:0 0 8px">Refrigeration Logbook – Startfehler</h2>
      <p style="margin:0 0 12px;color:#cbb6d6">
        Die Oberfläche konnte nicht geladen werden. Bitte diese Meldung melden:
      </p>
      <pre style="white-space:pre-wrap;font-size:12px;background:#000;color:#f88;
                  padding:12px;border-radius:8px;overflow:auto">${detail}</pre>
    </div>`;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

window.addEventListener("error", (e) => showFatalError(e.error ?? e.message));
window.addEventListener("unhandledrejection", (e) => showFatalError(e.reason));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
});

try {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </React.StrictMode>,
  );
} catch (error) {
  showFatalError(error);
}
