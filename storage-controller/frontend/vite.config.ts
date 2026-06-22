/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

// Ingress-safe: relative base so assets resolve under any dynamic path prefix.
// Remove the `crossorigin` attribute Vite adds to module scripts/styles. The
// assets are same-origin behind Ingress, where the attribute is unnecessary and
// has been observed to cause loading issues in the iframe context.
const stripCrossorigin = {
  name: "strip-crossorigin",
  transformIndexHtml(html: string) {
    return html.replace(/\s+crossorigin(?:=("|')[^"']*\1)?/g, "");
  },
};

export default defineConfig({
  base: "./",
  plugins: [react(), stripCrossorigin],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8099",
      "/health": "http://localhost:8099",
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: false,
  },
});
