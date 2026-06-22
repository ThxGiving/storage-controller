import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/lib/api";

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: async () => body,
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("api client", () => {
  it("requests entities with a search query relative to the ingress base", async () => {
    const fetchMock = mockFetch(200, []);
    vi.stubGlobal("fetch", fetchMock);
    // simulate ingress base path
    Object.defineProperty(window, "location", {
      value: { pathname: "/api/hassio_ingress/xyz/", protocol: "http:", host: "h" },
      writable: true,
    });

    await api.getEntities({ search: "kuhl" });

    expect(fetchMock).toHaveBeenCalledOnce();
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toBe("/api/hassio_ingress/xyz/api/home-assistant/entities?search=kuhl");
  });

  it("throws ApiError with the server detail on failure", async () => {
    vi.stubGlobal("fetch", mockFetch(422, { detail: "a room_temperature entity is required" }));
    await expect(api.createUnit({ name: "x", assignments: [] })).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
      message: "a room_temperature entity is required",
    });
  });

  it("exposes ApiError as an Error subclass", () => {
    expect(new ApiError(404, "nope")).toBeInstanceOf(Error);
  });
});
