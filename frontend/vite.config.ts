/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.LINKFLOW_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": apiTarget },
    // docs/METHODOLOGY.md lives outside the frontend root and is imported at build time
    fs: { allow: [".."] },
  },
  test: {
    include: ["src/**/*.test.ts"],
  },
});
