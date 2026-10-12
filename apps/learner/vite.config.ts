/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Vite runs this under Node; the app itself never sees process.
declare const process: { env: Record<string, string | undefined> };

const api = { "/v1": { target: process.env.LMS_API_URL ?? "http://127.0.0.1:8033", changeOrigin: true } };

// Served by Caddy at /learn/ (deploy/Caddyfile). `npm run dev` and
// `npm run preview` send /v1 to the API, so a phone can be pointed at either.
export default defineConfig({
  base: "/learn/",
  plugins: [react(), tailwindcss()],
  server: { port: 5177, proxy: api },
  preview: { port: 4177, proxy: api },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    testTimeout: 20000,
  },
});
