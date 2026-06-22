/**
 * Ingress-aware base-path resolution.
 *
 * The app may be served from "/" (local dev) or from a dynamic Home Assistant
 * Ingress prefix such as "/api/hassio_ingress/<session-id>/". All API and
 * WebSocket calls are built relative to this base so nothing is hard-coded.
 */

/** Compute the application base path (always ends with a single trailing slash). */
export function getBasePath(pathname: string = window.location.pathname): string {
  // Strip a trailing "index.html" if present.
  let base = pathname.replace(/index\.html$/, "");
  if (!base.endsWith("/")) {
    // Drop the last path segment (e.g. a client-route) to reach the app root.
    base = base.slice(0, base.lastIndexOf("/") + 1);
  }
  return base || "/";
}

/** Build an absolute, ingress-safe URL for an API path like "api/status". */
export function apiUrl(
  path: string,
  pathname: string = window.location.pathname,
): string {
  const base = getBasePath(pathname);
  return base + path.replace(/^\/+/, "");
}

/** Build an ingress-safe WebSocket URL (ws:// or wss://) for a backend path. */
export function wsUrl(
  path: string,
  loc: { protocol: string; host: string; pathname: string } = window.location,
): string {
  const scheme = loc.protocol === "https:" ? "wss:" : "ws:";
  const base = getBasePath(loc.pathname);
  return `${scheme}//${loc.host}${base}${path.replace(/^\/+/, "")}`;
}
