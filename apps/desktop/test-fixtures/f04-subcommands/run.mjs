// Windows Chromium → actual React completion/submit → actual dispatch/CLI worker.
// This bounded fixture does not qualify Electron startup or session.create.
/* global window -- These callbacks execute in Chromium through Playwright. */
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { createInterface } from 'node:readline'
import { fileURLToPath } from 'node:url'

import { createServer } from 'vite'

const here = path.dirname(fileURLToPath(import.meta.url))
const app = path.resolve(here, '../..')
const root = path.resolve(app, '../..')
const evidence = path.resolve(process.argv[2])
assert(evidence.startsWith(path.join(root, 'tmp/probes/v0216-20261010/evidence') + path.sep))
await fs.mkdir(evidence)
process.env.PLAYWRIGHT_BROWSERS_PATH = 'C:/Users/downl/AppData/Local/ms-playwright'
const { chromium } = await import('playwright')
const backend = spawn(process.env.HERMES_PYTHON, [path.join(here, 'backend.py'), evidence], {
  cwd: root,
  env: process.env,
  shell: false,
  windowsHide: true
})
let log = ''
backend.stderr.on('data', bytes => {
  log += bytes
})
backend.stdout.on('data', bytes => {
  log += bytes
})
const exit = new Promise(resolve => backend.on('exit', (code, signal) => resolve({ code, signal })))
let ready
let server
let browser
let closed = false
const errors = []
const cases = []
const post = async endpoint => {
  const response = await fetch(`http://127.0.0.1:${ready.port}/${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
    signal: AbortSignal.timeout(65000)
  })
  return response.json()
}
try {
  ready = await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('owned backend ready timeout')), 60000)
    const lines = createInterface({ input: backend.stdout })
    lines.on('line', line => {
      try {
        const value = JSON.parse(line)
        if (value.port && value.profiles) {
          clearTimeout(timeout)
          lines.close()
          resolve(value)
        }
      } catch {
        // Non-protocol startup diagnostics stay in backend.log.
      }
    })
    backend.on('exit', code => {
      clearTimeout(timeout)
      reject(new Error(`backend exited ${code}: ${log}`))
    })
  })
  const requireApp = createRequire(path.join(app, 'package.json'))
  server = await createServer({
    configFile: false,
    envDir: false,
    root: here,
    cacheDir: path.join(evidence, 'vite-cache'),
    resolve: {
      alias: {
        '@': path.join(app, 'src'),
        react: path.dirname(requireApp.resolve('react/package.json')),
        'react-dom': path.dirname(requireApp.resolve('react-dom/package.json'))
      }
    },
    server: {
      host: '127.0.0.1',
      port: 0,
      fs: { allow: [root] },
      proxy: {
        '/fixture': { target: `http://127.0.0.1:${ready.port}`, rewrite: value => value.slice('/fixture'.length) }
      }
    }
  })
  await server.listen()
  browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route =>
    new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort()
  )
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/`)
  await page.waitForFunction(() => !!window.reviewProbe)
  await page.evaluate(value => window.reviewProbe.select('owner', value), ready.profiles.owner.stored)
  const pickSubmit = async (verb, tail = '') => {
    await page.evaluate(() => window.reviewProbe.load('/skills '))
    await page.waitForFunction(value => window.reviewProbe.rows().includes(`/skills ${value}`), verb)
    const rows = await page.evaluate(() => window.reviewProbe.rows())
    assert(!rows.some(value => /\b(install|search|browse|inspect|audit)\b/.test(value)))
    await page.evaluate(value => window.reviewProbe.pick(`/skills ${value}`), verb)
    const selected = await page.evaluate(() => window.reviewProbe.text())
    assert.equal(selected.trim(), `/skills ${verb}`)
    if (tail) {
      await page.keyboard.insertText(` ${tail}`)
    }
    const invocation = await page.evaluate(() => window.reviewProbe.text())
    await page.evaluate(() => window.reviewProbe.submit())
    const state = await post('state')
    const call = state.calls.filter(row => row.request.method === 'slash.exec').at(-1)
    assert.equal(call.request.params.command, invocation.trim().slice(1))
    assert('result' in call.response, JSON.stringify(call.response))
    assert(call.response.result.output)
    return state
  }
  const initial = await post('state')
  const owner = ready.profiles.owner.records
  const foreign = ready.profiles.foreign.records
  let state = await pickSubmit('pending')
  let output = state.calls.at(-1).response.result.output
  assert(output.includes(owner.approve.id) && output.includes(owner.reject.id))
  assert(!output.includes(foreign.approve.id))
  assert.deepEqual(state.effects, initial.effects)
  cases.push('actual accepted pending candidate → public submit → owned pending IDs, no effects')
  state = await pickSubmit('diff', owner.approve.id)
  output = state.calls.at(-1).response.result.output
  assert(output.includes(owner.approve.id) && output.includes('日本語 pending review effect.'))
  assert.deepEqual(state.effects, initial.effects)
  cases.push('actual diff candidate → pending-ID diff, no persistence')
  await page.evaluate(value => window.reviewProbe.select('foreign', value), ready.profiles.foreign.stored)
  state = await pickSubmit('approve', owner.approve.id)
  assert.deepEqual(state.effects, initial.effects)
  assert.equal(state.calls.at(-1).request.params.session_id, ready.profiles.foreign.runtime)
  cases.push('foreign runtime approval cannot apply or discard the owner record')
  await page.evaluate(value => window.reviewProbe.select('owner', value), ready.profiles.owner.stored)
  state = await pickSubmit('approve', owner.approve.id)
  assert.equal(state.effects.owner.files.approve, owner.approve.content)
  assert(!state.effects.owner.pending.includes(owner.approve.id))
  assert.deepEqual(state.effects.foreign, initial.effects.foreign)
  cases.push('actual approve candidate → exact UTF-8 skill contents and pending removal')
  state = await pickSubmit('reject', owner.reject.id)
  assert.equal(state.effects.owner.files.reject, null)
  assert(!state.effects.owner.pending.includes(owner.reject.id))
  assert.deepEqual(state.effects.foreign, initial.effects.foreign)
  cases.push('actual reject candidate → pending removal with no target file')
  state = await pickSubmit('approval', 'off')
  assert.equal(state.effects.owner.approval, false)
  assert.equal(state.effects.foreign.approval, true)
  state = await pickSubmit('approval', 'on')
  assert.equal(state.effects.owner.approval, true)
  assert.deepEqual(state.effects.foreign, initial.effects.foreign)
  cases.push('actual approval candidate → persisted off/on scoped to owner config')
  const executionAttempts = value =>
    value.attempts.filter(row => !['commands.catalog', 'complete.slash'].includes(row.method))
  const count = executionAttempts(state).length
  const refusals = []
  for (const invocation of ['/skills', '/skills install source', '/skills audit', '/skills unknown', '/clear run']) {
    await page.evaluate(value => window.reviewProbe.load(value), invocation)
    await page.evaluate(() => window.reviewProbe.submit())
    state = await post('state')
    const after = executionAttempts(state).length
    assert.equal(after, count)
    refusals.push({ invocation, execution_attempts_before: count, execution_attempts_after: after })
  }
  state = await post('state')
  assert.equal(executionAttempts(state).length, count)
  cases.push('unsupported hub/bare/terminal submissions send zero execution attempts, including dispatch bypasses')
  assert.deepEqual(errors, [])
  await page.screenshot({ path: path.join(evidence, 'composer.png') })
  const cleanup = await post('close')
  closed = true
  assert.equal(cleanup.closed.length, 2)
  assert(
    cleanup.closed.every(
      row =>
        row.exit !== null &&
        !row.same_birth_alive &&
        row.pipes_closed &&
        row.drain_threads.every(thread => !thread.alive) &&
        row.descendants.every(child => !child.same_birth_alive && !child.cleanup_needed)
    )
  )
  assert.deepEqual(await exit, { code: 0, signal: null })
  const sources = {}
  for (const relative of [
    'hermes_cli/commands.py',
    'tui_gateway/methods_tools.py',
    'tui_gateway/server.py',
    'tui_gateway/slash_worker.py',
    'hermes_cli/cli_commands_mixin.py',
    'hermes_cli/write_approval_commands.py',
    'tools/write_approval.py',
    'tools/skill_manager_tool.py',
    'apps/desktop/src/lib/desktop-slash-commands.ts',
    'apps/desktop/src/app/chat/composer/hooks/use-slash-completions.ts',
    'apps/desktop/src/app/chat/composer/hooks/use-composer-trigger.ts',
    'apps/desktop/src/app/session/hooks/use-prompt-actions/index.ts',
    'apps/desktop/src/app/session/hooks/use-prompt-actions/slash.ts',
    ...['backend.py', 'renderer.tsx', 'run.mjs', 'index.html'].map(
      name => `apps/desktop/test-fixtures/f04-subcommands/${name}`
    )
  ]) {
    const bytes = await fs.readFile(path.join(root, relative))
    sources[relative] = { sha256: crypto.createHash('sha256').update(bytes).digest('hex'), bytes: bytes.length }
  }
  await fs.writeFile(
    path.join(evidence, 'receipt.json'),
    JSON.stringify(
      {
        platform: process.platform,
        browser: browser.version(),
        cases,
        refusals,
        errors,
        sources,
        cleanup: cleanup.closed,
        scope:
          'Windows Chromium actual hooks + public dispatch + actual CLI child + owned profile effects; no Electron/session.create qualification'
      },
      null,
      2
    ),
    'utf8'
  )
  console.log(JSON.stringify({ passed: cases.length, evidence }))
} finally {
  if (!closed && ready) {
    try {
      await post('close')
    } catch {
      backend.kill()
    }
    await exit
  } else if (!closed) {
    backend.kill()
    await exit
  }
  await browser?.close()
  await server?.close()
  await fs.writeFile(path.join(evidence, 'backend.log'), log, 'utf8')
}
