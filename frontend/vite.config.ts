/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The Mini App is served by aiohttp under /app/static/, so every asset URL is
// built with that prefix.  `npm run build` writes straight into webapp/dist,
// which is what `vyron/web/server.py` mounts in production.
export default defineConfig({
  base: "/app/static/",
  plugins: [react()],
  build: {
    outDir: "../webapp/dist",
    emptyOutDir: true,
    sourcemap: false,
    target: "es2020",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    css: false,
    include: ["src/**/*.test.{ts,tsx}"],
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    // `python -m vyron.tools.preview --port 8099` provides the API during dev.
    proxy: {
      "/api": "http://127.0.0.1:8099",
      "/health": "http://127.0.0.1:8099",
      "/v1": "http://127.0.0.1:8099",
    },
  },
});
