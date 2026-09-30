// Real Windows Chromium integration of the existing hook; not full Electron startup.
import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import path from 'node:path'
import { createRequire } from 'node:module'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { createServer } from 'vite'

const here = path.dirname(fileURLToPath(import.meta.url))
const app = path.resolve(here, '../..')
const root = path.resolve(app, '../..')
const evidence = process.argv[2]
assert(evidence && process.env.HERMES_HOME && process.env.PLAYWRIGHT_BROWSERS_PATH)
await fs.mkdir(evidence, { recursive: false })
const output = path.join(evidence, 'catalog.json')
const backend = spawnSync(process.env.HERMES_PYTHON, [path.join(here, 'backend.py'), output], {
  cwd: root, env: process.env, encoding: 'utf8', timeout: 60000
})
await fs.writeFile(path.join(evidence, 'backend.log'), backend.stdout + backend.stderr, 'utf8')
assert.equal(backend.status, 0, backend.stderr)
const wire = JSON.parse(await fs.readFile(output, 'utf8'))
const catalog = wire.catalog.result
assert.equal(catalog.commands['/rollback'].argument_mode, 'text')
assert.equal(catalog.commands['/undo'].argument_mode, 'text')
const requireApp = createRequire(path.join(app, 'package.json'))
const server = await createServer({
  configFile: false, envDir: false, root: here,
  cacheDir: path.join(evidence, 'vite-cache'),
  resolve: { alias: {
    '@': path.join(app, 'src'),
    react: path.dirname(requireApp.resolve('react/package.json')),
    'react-dom': path.dirname(requireApp.resolve('react-dom/package.json'))
  } },
  server: { host: '127.0.0.1', port: 0, fs: { allow: [root] } }
})
let browser
const failures = []
const cases = []
try {
  await server.listen()
  const port = server.httpServer.address().port
  browser = await chromium.launch({ headless: true })
  const context = await browser.newContext()
  const page = await context.newPage()
  page.on('pageerror', error => failures.push(error.message))
  await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1'
    ? route.continue() : route.abort())
  await page.goto(`http://127.0.0.1:${port}/`)
  await page.waitForFunction(() => !!window.catalogProbe)
  await page.evaluate(value => window.catalogProbe.configure(value.catalog.result, value.completion.result), wire)
  const load = async text => {
    await page.evaluate(value => window.catalogProbe.load(value), text)
    await page.waitForTimeout(30)
  }
  assert.equal(await page.evaluate(() => window.catalogProbe.mode('/rollback')), null)
  await load('/roll')
  await page.waitForFunction(() => window.catalogProbe.mode('/rollback') === 'text')
  await page.evaluate(() => window.catalogProbe.pickAccepted('/rollback'))
  assert.equal((await page.evaluate(() => window.catalogProbe.snapshot())).chips, 0)
  assert.equal((await page.evaluate(() => window.catalogProbe.snapshot())).text, '/rollback ')
  assert.deepEqual((await page.evaluate(() => window.catalogProbe.requests())).sort(), ['commands.catalog', 'complete.slash'])
  cases.push('cold typed public completion prepares metadata before accepted row selection')
  for (const command of ['/rollback', '/undo', '/fixture-text', '/fixture-mixed']) {
    await load(`${command} multi word`)
    await page.locator('[data-testid=editor]').press('Space')
    const snapshot = await page.evaluate(() => window.catalogProbe.snapshot())
    // Chromium uses NBSP at a trailing editable space; preserve raw browser
    // behavior and normalize only this assertion's whitespace comparison.
    assert.equal(snapshot.text.replaceAll('\u00a0', ' '), `${command} multi word `)
    assert.equal(snapshot.chips, 0)
    assert.equal(snapshot.freeText, command === '/fixture-mixed')
    cases.push(`${command}: typed prose stays editable`)
  }
  await load('/fixture-options on')
  await page.locator('[data-testid=editor]').press('Space')
  assert.equal((await page.evaluate(() => window.catalogProbe.snapshot())).chips, 1)
  cases.push('options: finite directive commits')
  await load('/fixture-t')
  await page.evaluate(() => window.catalogProbe.pick('/fixture-text'))
  assert.deepEqual(await page.evaluate(() => window.catalogProbe.snapshot()), {
    text: '/fixture-text ', chips: 0, freeText: false
  })
  cases.push('text: picked command keeps editable text')
  await load('/fixture-n')
  await page.evaluate(() => window.catalogProbe.pick('/fixture-null'))
  assert.equal((await page.evaluate(() => window.catalogProbe.snapshot())).chips, 1)
  cases.push('null: bare command commits')
  assert.equal(await page.evaluate(() => window.catalogProbe.mode('/model')), null)
  assert.equal(await page.evaluate(() => window.catalogProbe.mode('/resume')), 'mixed')
  cases.push('local model/session picker priority')
  await page.evaluate(() => window.catalogProbe.invalidate())
  assert.equal(await page.evaluate(() => window.catalogProbe.mode('/rollback')), null)
  cases.push('invalidated metadata unavailable')
  assert.deepEqual(failures, [])
  await page.screenshot({ path: path.join(evidence, 'composer.png') })
  const sources = {}
  for (const relative of ['hermes_cli/commands.py', 'tui_gateway/methods_tools.py',
    'apps/desktop/src/lib/desktop-slash-commands.ts', 'apps/desktop/src/lib/slash-completion-cache.ts',
    'apps/desktop/src/app/chat/composer/hooks/use-composer-trigger.ts',
    'apps/desktop/src/app/chat/composer/hooks/use-slash-completions.ts',
    'apps/desktop/src/app/chat/composer/hooks/use-live-completion-adapter.ts']) {
    sources[relative] = crypto.createHash('sha256').update(await fs.readFile(path.join(root, relative))).digest('hex')
  }
  await fs.writeFile(path.join(evidence, 'receipt.json'), JSON.stringify({
    platform: process.platform, node: process.version, browser: browser.version(), cases,
    failures, sources, scope: 'real dispatch fixture to real React hook and Chromium DOM; discovery doubles; no Electron, auth or destructive effect'
  }, null, 2), 'utf8')
  console.log(JSON.stringify({ passed: cases.length, browser: browser.version(), evidence }))
} finally {
  await browser?.close()
  await server.close()
}
