import { describe, expect, it } from "vitest";
import { apiUrl, getBasePath, wsUrl } from "@/lib/ingress";

describe("ingress base path", () => {
  it("returns root for /", () => {
    expect(getBasePath("/")).toBe("/");
  });

  it("keeps a trailing-slash ingress prefix", () => {
    expect(getBasePath("/api/hassio_ingress/abc123/")).toBe(
      "/api/hassio_ingress/abc123/",
    );
  });

  it("drops index.html", () => {
    expect(getBasePath("/api/hassio_ingress/abc123/index.html")).toBe(
      "/api/hassio_ingress/abc123/",
    );
  });

  it("strips a trailing route segment without a slash", () => {
    expect(getBasePath("/api/hassio_ingress/abc123/units")).toBe(
      "/api/hassio_ingress/abc123/",
    );
  });
});

describe("apiUrl", () => {
  it("builds a relative API path under an ingress prefix", () => {
    expect(apiUrl("api/status", "/api/hassio_ingress/abc123/")).toBe(
      "/api/hassio_ingress/abc123/api/status",
    );
  });

  it("strips a leading slash from the given path", () => {
    expect(apiUrl("/api/status", "/")).toBe("/api/status");
  });
});

describe("wsUrl", () => {
  it("builds a ws:// URL for http", () => {
    expect(
      wsUrl("api/ws", {
        protocol: "http:",
        host: "ha.local:8123",
        pathname: "/api/hassio_ingress/abc123/",
      }),
    ).toBe("ws://ha.local:8123/api/hassio_ingress/abc123/api/ws");
  });

  it("builds a wss:// URL for https", () => {
    expect(
      wsUrl("api/ws", {
        protocol: "https:",
        host: "ha.local",
        pathname: "/",
      }),
    ).toBe("wss://ha.local/api/ws");
  });
});
