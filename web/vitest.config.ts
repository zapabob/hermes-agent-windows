import { defineConfig } from "vitest/config";
import babel from "@rolldown/plugin-babel";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";

/** Same component/hook-scoped compiler preset as vite.config.ts. */
function compilerPreset() {
  const preset = reactCompilerPreset();
  preset.rolldown.filter ??= {};
  preset.rolldown.filter.code = /\/>|<\/|from\s*['"][^'"]*react/;
  return preset;
}
import path from "path";

const rawWorkers = process.env.VITEST_MAX_WORKERS;
const maxWorkers = rawWorkers ? Math.max(1, Number.parseInt(rawWorkers, 10)) : undefined;

export default defineConfig({
  plugins: [react(), babel({ presets: [compilerPreset()] })],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    maxWorkers,
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
