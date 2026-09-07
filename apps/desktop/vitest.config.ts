import type { TestProjectConfiguration } from 'vitest/config'
import { defineConfig } from 'vitest/config'

const rawWorkers = process.env.VITEST_MAX_WORKERS
const maxWorkers = rawWorkers ? Math.max(1, Number.parseInt(rawWorkers, 10)) : undefined

const reactUi: TestProjectConfiguration = {
  extends: './vite.config.ts',
  test: {
    name: 'ui',
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    globals: true,
    // The first test in each file pays jsdom env init + full module transform,
    // which can exceed vitest's 5000ms default under CI/load. 30s gives the
    // cold start headroom without masking genuinely hung tests.
    testTimeout: 30_000
  }
}

const electronNative: TestProjectConfiguration = {
  test: {
    name: 'electron',
    environment: 'node',
    include: ['e2e/**/*.unit.test.ts', 'electron/**/*.test.ts', 'scripts/**.test.{ts,mjs}'],
    exclude: ['scripts/run-short-session-hang-repro.test.mjs'],
    testTimeout: 15_000,
    fileParallelism: process.platform !== 'win32'
  }
}

export default defineConfig({
  test: {
    maxWorkers,
    projects: [reactUi, electronNative]
  }
})
