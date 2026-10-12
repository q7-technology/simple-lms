/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Vite runs this under Node; the app itself never sees process.
declare const process: { env: Record<string, string | undefined> };

// 5176, beside Simple WMS's 5173 and Simple TMS's 5174 and 5175.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5176,
    proxy: {
      "/v1": {
        target: process.env.LMS_API_URL ?? "http://127.0.0.1:8033",
        changeOrigin: true,
      },
    },
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    testTimeout: 20000,
  },
});
