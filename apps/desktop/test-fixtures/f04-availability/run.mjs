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
  await load('/')
  await page.waitForFunction(() => window.catalogProbe.rows().length > 0)
  const rows = await page.evaluate(() => window.catalogProbe.rows())
  for (const command of ['/f04-hidden', '/f04-terminal', '/f04-messaging', '/f04-advanced']) {
    assert(!rows.includes(command), `unexpected row ${command}`)
  }
  assert(rows.includes('/fixture-text'))
  cases.push('public catalog availability filters real bare-slash adapter rows')
  assert.equal(await page.evaluate(() => window.catalogProbe.executable('/f04-hidden')), true)
  assert.equal(await page.evaluate(() => window.catalogProbe.unavailable('/f04-hidden')), null)
  cases.push('hidden remains executable in the desktop resolver')
  for (const reason of ['terminal', 'messaging', 'advanced']) {
    assert.deepEqual(await page.evaluate(value => window.catalogProbe.surface(value), `/f04-${reason}`), {kind:'unavailable',reason})
    assert.equal(await page.evaluate(value => window.catalogProbe.executable(value), `/f04-${reason}`), false)
    cases.push(`${reason}: Desktop unavailable surface`)
  }
  for (const command of ['/fixture-text', '/fixture-mixed']) {
    await load(`${command} 日本語 multi word`)
    await page.locator('[data-testid=editor]').press('Space')
    const state = await page.evaluate(() => window.catalogProbe.snapshot())
    assert.equal(state.text.replaceAll('\u00a0',' '), `${command} 日本語 multi word `)
    assert.equal(state.chips, 0)
    cases.push(`${command}: editable native UTF-8 prose`)
  }
  await load('/fixture-options on')
  await page.locator('[data-testid=editor]').press('Space')
  assert.equal((await page.evaluate(() => window.catalogProbe.snapshot())).chips,1)
  cases.push('options native finite chip effect')
  assert.deepEqual(await page.evaluate(() => window.catalogProbe.surface('/model')), {kind:'picker',picker:'model'})
  cases.push('local model picker remains authoritative')
  await page.evaluate(() => window.catalogProbe.invalidate())
  assert.equal(await page.evaluate(() => window.catalogProbe.surface('/f04-terminal')),null)
  cases.push('invalidated availability is not retained')
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
