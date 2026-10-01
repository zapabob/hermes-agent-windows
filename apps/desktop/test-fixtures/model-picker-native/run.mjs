import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { createServer } from 'vite'
const here = path.dirname(fileURLToPath(import.meta.url))
const app = path.resolve(here, '../..'), root = path.resolve(app, '../..')
const evidence = process.argv[2]
assert(evidence && process.env.HERMES_HOME && process.env.PLAYWRIGHT_BROWSERS_PATH)
await fs.mkdir(evidence, { recursive: false })
const requireApp = createRequire(path.join(app, 'package.json'))
const server = await createServer({ configFile: false, envDir: false, root: here, cacheDir: path.join(evidence, 'vite-cache'),
 resolve: { alias: { '@': path.join(app, 'src'), react: path.dirname(requireApp.resolve('react/package.json')), 'react-dom': path.dirname(requireApp.resolve('react-dom/package.json')) } },
 server: { host: '127.0.0.1', port: 0, fs: { allow: [root] } } })
let browser
const failures = [], remoteAttempts = [], cases = []
try {
 await server.listen()
 const port = server.httpServer.address().port
 browser = await chromium.launch({ headless: true })
 for (const scenario of ['success', 'waiting', 'failure']) {
  const context = await browser.newContext()
  const page = await context.newPage()
  page.on('pageerror', error => failures.push(error.message))
  await page.route('**/*', route => {
   const url = new URL(route.request().url())
   if (url.hostname === '127.0.0.1' && url.port === String(port)) return route.continue()
   remoteAttempts.push(url.origin + url.pathname); return route.abort()
  })
  await page.goto(`http://127.0.0.1:${port}/`)
  await page.waitForFunction(() => !!window.pickerProbe)
  await page.getByRole('button', { name: 'Models', exact: true }).click()
  await page.getByText('Owned provider', { exact: true }).waitFor()
  await page.evaluate(value => window.pickerProbe.mode(value), scenario)
  await page.getByText('Refresh Models', { exact: true }).click()
  await page.waitForFunction(() => window.pickerProbe.snapshot().calls.some(value => value.params?.refresh))
  if (scenario === 'waiting') {
   await page.evaluate(() => window.pickerProbe.newer())
   await page.evaluate(() => window.pickerProbe.complete())
  } else if (scenario === 'failure') {
   await page.evaluate(() => window.pickerProbe.fail())
  }
  if (scenario !== 'failure') await page.waitForFunction(() => window.pickerProbe.snapshot().data?.providers[0]?.slug === 'other-provider')
  else await page.waitForFunction(() => document.body.textContent.includes('Refresh Models'))
  const snapshot = await page.evaluate(() => window.pickerProbe.snapshot())
  assert.deepEqual(snapshot.selected, [])
  assert.deepEqual(snapshot.current, scenario === 'waiting' ? ['newer-choice', 'newer-provider', 'medium', true] : ['selected-new-model', 'owned-provider', 'high', true])
  assert.equal(snapshot.otherInvalidated, false)
  assert(snapshot.calls.every(value => value.method === 'model.options'))
  assert(snapshot.calls.filter(value => value.params?.refresh).length === 1)
  assert.equal(snapshot.data.providers[0].slug, scenario === 'failure' ? 'owned-provider' : 'other-provider')
  cases.push({ scenario, snapshot })
  await page.screenshot({ path: path.join(evidence, scenario + '.png') })
  await context.close()
 }
 assert.deepEqual(failures, [])
 assert.deepEqual(remoteAttempts, [])
 const sources = {}
 for (const file of ['apps/desktop/src/app/shell/model-menu-panel.tsx', 'apps/desktop/src/app/shell/model-catalog-menu.tsx', 'apps/desktop/src/lib/model-options.ts', 'apps/desktop/src/store/session.ts', 'apps/desktop/test-fixtures/model-picker-native/renderer.tsx', 'apps/desktop/test-fixtures/model-picker-native/run.mjs']) sources[file] = crypto.createHash('sha256').update(await fs.readFile(path.join(root, file))).digest('hex')
 await fs.writeFile(path.join(evidence, 'receipt.json'), JSON.stringify({ platform: process.platform, node: process.version, browser: browser.version(), cases, failures, remoteAttempts, sources, scope: 'Actual ModelMenuPanel/requestModelOptions/query/store/DOM in Windows Chromium with owned RPC transport; not Electron or full backend transport E2E.' }, null, 2), 'utf8')
 console.log(JSON.stringify({ passed: cases.length, browser: browser.version(), evidence }))
} finally { await browser?.close(); await server.close() }
