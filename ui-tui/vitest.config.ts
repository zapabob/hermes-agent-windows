import { defineConfig } from 'vitest/config'

const rawWorkers = process.env.VITEST_MAX_WORKERS
const maxWorkers = rawWorkers ? Math.max(1, Number.parseInt(rawWorkers, 10)) : undefined

export default defineConfig({
  test: {
    maxWorkers,
    exclude: ['dist/**', 'node_modules/**']
  }
})

