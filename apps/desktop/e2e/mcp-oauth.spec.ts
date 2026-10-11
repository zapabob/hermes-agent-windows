import { createHash } from 'node:crypto'
import { JsonRpcGatewayClient, JsonRpcGatewayError } from '../../shared/src/json-rpc-gateway'
import { allowErrorBanners } from './test'
import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createInterface } from 'node:readline'

import { buildAppEnv, closeDesktop, createSandbox, launchDesktop, waitForAppReady, writeEnvFile, writeMockProviderConfig } from './fixtures'
import { startMockServer } from './mock-server'
import { assertLoopbackListenerStopped, captureOwnedTree, type OwnedProcess, survivingOwnedProcesses } from './owned-process-observer'
import { expect, type Page, test } from './test'

const ownedRoot = path.resolve(os.tmpdir())
const repository = path.resolve(import.meta.dirname, '../../..')
const python = process.env.HERMES_PYTHON ?? path.join(repository, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
interface Row { operation: string; nonce?: string; authorization?: string }
interface PeerReply { ready?: boolean; base?: string; mcp_url?: string; issuer?: string; code?: string; state?: string; redirect?: string; iss?: string; ledger?: Row[]; token_started?: boolean }

async function peer() {
  const owned = fs.mkdtempSync(path.join(ownedRoot, 'hermes-e2e-oauth-peer-'))
  const script = path.join(import.meta.dirname, 'mcp-oauth-issuer.py')
  const queued: PeerReply[] = []
  const waiters: Array<(row: PeerReply) => void> = []
  let reader: ReturnType<typeof createInterface> | undefined
  const stderr: string[] = []
  const next = async (): Promise<PeerReply> => {
    if (queued.length) { return queued.shift()! }
    return new Promise((resolve, reject) => {
      const deliver = (value: PeerReply) => { clearTimeout(timer); resolve(value) }
      const timer = setTimeout(() => {
        const index = waiters.indexOf(deliver)
        if (index >= 0) { waiters.splice(index, 1) }
        reject(new Error(`Owned issuer response timed out: ${stderr.join('')}`))
      }, 5_000)
      waiters.push(deliver)
    })
  }
  let identities: OwnedProcess[] = []
  const close = async () => {
    const failures: unknown[] = []
    try { child.stdin.end(JSON.stringify({ action: 'quit' }) + '\n') } catch (error) { failures.push(error) }
    try {
      await expect.poll(() => child.exitCode !== null || child.signalCode !== null, { timeout: 15_000 }).toBe(true)
    } catch (error) { failures.push(error) }
    try { expect(child.exitCode).toBe(0); expect(child.signalCode).toBeNull() } catch (error) { failures.push(error) }
    reader?.close()
    child.stdout.destroy()
    child.stderr.destroy()
    try { expect(survivingOwnedProcesses(python, identities)).toEqual([]) } catch (error) { failures.push(error) }
    await test.info().attach('issuer-process-cleanup', { body: JSON.stringify({ identities, failures: failures.map(String), stderr }), contentType: 'application/json' })
    if (failures.length) { throw new AggregateError(failures, 'Owned issuer did not exit') }
  }
  const child = spawn(python, ['-u', script, owned, ownedRoot], { env: process.env, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] })
  try {
    reader = createInterface({ input: child.stdout })
    child.stderr.on('data', bytes => stderr.push(String(bytes)))
    reader.on('line', line => {
      const value = JSON.parse(line) as PeerReply
      const waiting = waiters.shift()
      if (waiting) { waiting(value) } else { queued.push(value) }
    })
    await expect.poll(() => fs.existsSync(path.join(owned, 'birth.json')), { timeout: 5_000 }).toBe(true)
    const birth = JSON.parse(fs.readFileSync(path.join(owned, 'birth.json'), 'utf8')) as OwnedProcess
    identities = captureOwnedTree(python, child.pid!)
    const actual = identities.find(row => row.pid === birth.pid)
    expect(actual).toEqual(birth)
    expect(actual!.argv).toContain(script)
    expect(actual!.argv).toContain(owned)
    expect(actual!.argv).toContain(ownedRoot)
    fs.writeFileSync(path.join(owned, 'observed'), 'observed', 'utf8')
    const ready = await next()
    expect(ready.ready).toBe(true)
    return { ready, identities, close, request: async (action: string, values: Record<string, unknown> = {}) => {
      child.stdin.write(JSON.stringify({ action, ...values }) + '\n')
      return next()
    } }
  } catch (error) {
    try { await close() } catch (cleanup) { throw new AggregateError([error, cleanup], 'Issuer start and cleanup failed') }
    throw error
  }
}

async function authenticate(page: Page) {
  await page.evaluate(() => { window.location.hash = '#/skills?tab=mcp' })
  const selected = page.locator('#mcp-server-reports button').first()
  await expect(selected).toBeVisible({ timeout: 30_000 })
  await selected.click()
  const button = page.getByRole('button', { name: 'Authenticate', exact: true })
  await expect(button).toBeVisible({ timeout: 30_000 })
  await button.click()
}

for (const scenario of ['native-success', 'cancel-retry', 'admitted-profile-switch']) {
  test(`actual Electron OAuth ${scenario}`, async () => {
    test.setTimeout(240_000)
    let mock: Awaited<ReturnType<typeof startMockServer>> | undefined
    let sandbox: ReturnType<typeof createSandbox> | undefined
    let launched: Awaited<ReturnType<typeof launchDesktop>> | undefined
    const identities: OwnedProcess[] = []
    const callbacks: string[] = []
    const issuer = await peer()
    const failures: unknown[] = []
    let primaryFailure: unknown
    let hasPrimaryFailure = false
    try {
      mock = await startMockServer({ scriptedTurns: [
        { text: '', toolCalls: [{ name: 'tool_call', args: { name: 'mcp__reports__write_sentinel', arguments: { nonce: 'native-effect-' + scenario } } }] },
        { text: 'M03 native protected effect completed.' }
      ] })
      sandbox = createSandbox('m03-oauth')
      expect(path.dirname(path.resolve(sandbox.root))).toBe(ownedRoot)
      const extra = `security:\n  allow_lazy_installs: false\nmcp_servers:\n  reports:\n    url: ${JSON.stringify(issuer.ready.mcp_url)}\n    transport: http\n    auth: oauth\n    oauth: {cimd: false}\n    timeout: 5`
      writeMockProviderConfig(sandbox.hermesHome, mock.url, undefined, extra, 262144)
      writeEnvFile(sandbox.hermesHome)
      const other = path.join(sandbox.hermesHome, 'profiles/other')
      fs.mkdirSync(other, { recursive: true })
      fs.copyFileSync(path.join(sandbox.hermesHome, 'config.yaml'), path.join(other, 'config.yaml'))
      launched = await launchDesktop(buildAppEnv(sandbox, { HERMES_TUI_TOOLSETS: 'reports' }))
      await waitForAppReady({ ...launched, mock, mockUrl: mock.url, sandbox, cleanup: async () => {} })
      identities.push(...captureOwnedTree(python, launched.app.process().pid!))
      const nativeProbe = await launched.page.evaluate(async (): Promise<{ error?: string; redirectUri?: string }> => {
        try {
          const desktop = window as unknown as Window & { hermesDesktop: { mcpOauth: {
            listen: () => Promise<{ id: string; redirectUri: string }>
            cancel: (id: string) => Promise<boolean>
          } } }
          const opened = await desktop.hermesDesktop.mcpOauth.listen()
          await desktop.hermesDesktop.mcpOauth.cancel(opened.id)
          return { redirectUri: opened.redirectUri }
        } catch (error) { return { error: String(error) } }
      })
      await test.info().attach('actual-public-preload-listen-cancel', { body: JSON.stringify(nativeProbe), contentType: 'application/json' })
      if (nativeProbe.redirectUri) { callbacks.push(nativeProbe.redirectUri) }
      expect(nativeProbe.error).toBeUndefined()
      expect(nativeProbe.redirectUri).toMatch(/^http:\/\/127\.0\.0\.1:\d+\/callback$/)
      await assertLoopbackListenerStopped(nativeProbe.redirectUri!)
      // Capture only the external browser launch. The actual UI action, native
      // callback listener/preload, RPC, SDK, token storage and backend remain real.
      await launched.app.evaluate(({ shell }) => {
        const state = globalThis as typeof globalThis & { m03AuthUrls: string[] }
        state.m03AuthUrls = []
        shell.openExternal = async (url: string) => { state.m03AuthUrls.push(url) }
      })
      const urls = async () => launched!.app.evaluate(() => (globalThis as typeof globalThis & { m03AuthUrls: string[] }).m03AuthUrls)
      const profileRail = launched.page.getByRole('group', { name: 'Profiles', exact: true })
      if (scenario !== 'native-success') {
        await profileRail.getByRole('button', { name: 'other', exact: true }).click()
        await expect(profileRail.getByRole('button', { name: 'other', exact: true })).toHaveAttribute('aria-pressed', 'true', { timeout: 45_000 })
        await profileRail.getByRole('button', { name: 'Switch to default', exact: true }).click()
        await expect(profileRail.getByRole('button', { name: 'Show all profiles', exact: true })).toHaveAttribute('aria-pressed', 'true', { timeout: 5_000 })
      }
      const chat = await launched.page.evaluate(() => window.location.hash)
      const token = path.join(sandbox.hermesHome, 'mcp-tokens/reports.json')
      await authenticate(launched.page)
      await expect.poll(async () => (await urls()).length, { timeout: 40_000 }).toBe(1)
      if (scenario === 'cancel-retry') {
        const pendingCallback = new URL((await urls())[0]).searchParams.get('redirect_uri')!
        callbacks.push(pendingCallback)
        const liveResponse = await fetch(pendingCallback, { signal: AbortSignal.timeout(5_000) })
        expect(liveResponse.status).toBe(200)
        await liveResponse.text()
        await profileRail.getByRole('button', { name: 'other', exact: true }).click()
        await expect(profileRail.getByRole('button', { name: 'other', exact: true })).toHaveAttribute('aria-pressed', 'true', { timeout: 5_000 })
        await expect.poll(async () => {
          try { await assertLoopbackListenerStopped(pendingCallback); return true } catch { return false }
        }, { timeout: 15_000 }).toBe(true)
        expect(fs.existsSync(token)).toBe(false)
        expect((await issuer.request('ledger')).ledger!.filter(row => row.operation === 'token_request')).toHaveLength(0)
        await profileRail.getByRole('button', { name: 'Switch to default', exact: true }).click()
        await expect(profileRail.getByRole('button', { name: 'Show all profiles', exact: true })).toHaveAttribute('aria-pressed', 'true', { timeout: 5_000 })
        await authenticate(launched.page)
        await expect.poll(async () => (await urls()).length, { timeout: 40_000 }).toBe(2)
      }
      if (scenario === 'admitted-profile-switch') { await issuer.request('hold') }
      const callback = await issuer.request('authorize', { url: (await urls()).at(-1)! })
      callbacks.push(callback.redirect!)
      const response = await fetch(`${callback.redirect}?${new URLSearchParams({ code: callback.code!, state: callback.state!, iss: callback.iss! })}`, { signal: AbortSignal.timeout(5_000) })
      expect(response.status).toBe(200)
      await response.text()
      await assertLoopbackListenerStopped(callback.redirect!)
      if (scenario === 'admitted-profile-switch') {
        try {
          await expect.poll(async () => (await issuer.request('ledger')).token_started, { timeout: 5_000 }).toBe(true)
          expect((await issuer.request('ledger')).ledger!.filter(row => row.operation === 'token_redemption')).toHaveLength(0)
          expect(fs.existsSync(token)).toBe(false)
          await profileRail.getByRole('button', { name: 'other', exact: true }).click()
          await expect(profileRail.getByRole('button', { name: 'other', exact: true })).toHaveAttribute('aria-pressed', 'true', { timeout: 5_000 })
          expect((await issuer.request('ledger')).ledger!.filter(row => row.operation === 'token_redemption')).toHaveLength(0)
          expect(fs.existsSync(token)).toBe(false)
        } finally {
          try { await issuer.request('release') } catch (error) { failures.push(error) }
        }
      }
      await expect.poll(() => fs.existsSync(token), { timeout: 30_000 }).toBe(true)
      expect(JSON.parse(fs.readFileSync(token, 'utf8')).access_token).toBe('owned-synthetic-token')
      expect(fs.existsSync(path.join(other, 'mcp-tokens/reports.json'))).toBe(false)
      await expect.poll(async () => (await issuer.request('ledger')).ledger!.filter(row => row.operation === 'token_redemption').length).toBe(1)
      if (scenario === 'admitted-profile-switch') {
        await profileRail.getByRole('button', { name: 'Switch to default', exact: true }).click()
        await expect(profileRail.getByRole('button', { name: 'Show all profiles', exact: true })).toHaveAttribute('aria-pressed', 'true', { timeout: 5_000 })
      }
      await launched.page.evaluate(hash => { window.location.hash = hash }, chat)
      const composer = launched.page.locator('[contenteditable="true"]').first()
      await composer.click()
      await composer.fill('M03 invoke the owned protected MCP tool')
      await launched.page.keyboard.press('Enter')
      await expect(launched.page.locator('[data-slot="aui_thread-viewport"]')).toContainText('M03 native protected effect completed.', { timeout: 120_000 })
      const ledger = (await issuer.request('ledger')).ledger!
      expect(ledger.filter(row => row.operation === 'sentinel').map(row => row.nonce)).toEqual(['native-effect-' + scenario])
      await test.info().attach('actual-issuer-ledger', { body: JSON.stringify(ledger), contentType: 'application/json' })
      await launched.page.screenshot({ path: test.info().outputPath('native-oauth-completed.png') })
    } catch (error) {
      primaryFailure = error
      hasPrimaryFailure = true
    } finally {
      const attempt = async (action: () => Promise<void> | void) => { try { await action() } catch (error) { failures.push(error) } }
      await attempt(async () => { await test.info().attach('issuer-ledger-at-cleanup', { body: JSON.stringify(await issuer.request('ledger')), contentType: 'application/json' }) })
      if (mock) { await attempt(async () => { await test.info().attach('full-provider-requests', { body: JSON.stringify(mock!.receivedRequests), contentType: 'application/json' }) }) }
      if (sandbox) {
        await attempt(async () => {
          const logs = path.join(sandbox!.hermesHome, 'logs')
          if (fs.existsSync(logs)) {
            for (const name of fs.readdirSync(logs).filter(name => name.endsWith('.log'))) {
              await attempt(async () => { await test.info().attach('backend-' + name, { path: path.join(logs, name), contentType: 'text/plain' }) })
            }
          }
        })
      }
      await attempt(async () => { await issuer.request('release') })
      if (launched) {
        await attempt(() => { identities.push(...captureOwnedTree(python, launched!.app.process().pid!)) })
        await attempt(() => closeDesktop(launched!.app))
      }
      await attempt(() => issuer.close())
      if (mock) { await attempt(() => mock!.close()) }
      await attempt(async () => { await expect.poll(() => survivingOwnedProcesses(python, identities), { timeout: 15_000 }).toEqual([]) })
      for (const callback of callbacks) { await attempt(() => assertLoopbackListenerStopped(callback)) }
      if (mock) { await attempt(() => assertLoopbackListenerStopped(mock!.url)) }
      await attempt(async () => { await test.info().attach('native-owned-cleanup', { body: JSON.stringify({ identities, failures: failures.map(String) }), contentType: 'application/json' }) })
      // Keep this test-owned sandbox as evidence; no deletion during qualification.
    }
    if (failures.length) {
      throw new AggregateError(hasPrimaryFailure ? [primaryFailure, ...failures] : failures, 'Native OAuth cleanup failed')
    }
    if (hasPrimaryFailure) { throw primaryFailure }
  })
}


interface WorkerRow {
  flow_id: string
  worker_done: boolean
  actual_started_event: boolean
  ident: null | number
  native_acquired: boolean
  native_id?: number
  object_id: number
}
interface NativeWorkerRecord {
  kind: string
  birth: OwnedProcess
  sequence: number
  action?: string
  flow_id?: string
  worker_done?: boolean
  native_id?: number
  native_acquired?: boolean
  object_id?: number
  ident?: null | number
  actual_started_event?: boolean
  control_original_start_attempted?: boolean
  control_actual_started?: boolean
  actual_home?: string
  active?: boolean
  module?: string
  path?: string
  sha256?: string
  completed?: boolean
  failures?: string[]
  actual_join_confirmed?: boolean
  rpc_handlers_restored?: boolean
  params?: Record<string, unknown>
  response?: { error?: { code: number; message: string; data?: { kind: string; session_id: string; server_name: string } }; result?: Record<string, unknown> }
  owner_rows?: WorkerRow[]
  [key: string]: unknown
}
interface NativeServerRecord { kind: string; object_id: number; port: null | number; address: null | string }
const workerCause = 'Owned native Gateway worker startup failure'
const sourceHash = (name: string) => createHash('sha256').update(fs.readFileSync(name)).digest('hex')

function workerBootstrap(sandbox: ReturnType<typeof createSandbox>, mode: string) {
  const directory = path.join(sandbox.root, 'worker-bootstrap')
  fs.mkdirSync(directory)
  const source = path.join(import.meta.dirname, 'mcp-oauth-worker-sitecustomize.py')
  const modules: Record<string, { path: string; sha256: string }> = {}
  for (const [name, relative] of Object.entries({
    'tui_gateway.server': 'tui_gateway/server.py',
    'tui_gateway.mcp_oauth_sessions': 'tui_gateway/mcp_oauth_sessions.py',
    'tools.mcp_tool': 'tools/mcp_tool.py'
  })) { modules[name] = { path: relative, sha256: sourceHash(path.join(repository, relative)) } }
  const configuration = { repository, home: sandbox.hermesHome, mode, modules,
    hook_sha256: sourceHash(source), threading_sha256: '846f450ae794e4aab823a163f8c71d27751148af33e91dd3de886686a4e8ebfb' }
  fs.writeFileSync(path.join(directory, 'sitecustomize.py'), fs.readFileSync(source), { flag: 'wx' })
  fs.writeFileSync(path.join(directory, 'configuration.json'), JSON.stringify(configuration, null, 2), { encoding: 'utf8', flag: 'wx' })
  const observations = (): NativeWorkerRecord[] => fs.readdirSync(directory).filter(name => /^observations-\d+\.jsonl$/.test(name)).flatMap(name => {
    const content = fs.readFileSync(path.join(directory, name), 'utf8')
    const lastCompleteLine = content.lastIndexOf('\n')
    return content.slice(0, lastCompleteLine + 1).split('\n').filter(Boolean).map(line => JSON.parse(line) as NativeWorkerRecord)
  })
  const release = (name: 'return-failure' | 'release-worker' | 'finish') => {
    const target = path.join(directory, name)
    if (!fs.existsSync(target)) { fs.writeFileSync(target, 'release', { encoding: 'utf8', flag: 'wx' }) }
    expect(fs.readFileSync(target, 'utf8')).toBe('release')
  }
  return { directory, configuration, observations, release }
}

async function workerGateway(page: Page) {
  const minted = await page.evaluate(async () => {
    const bridge = window as unknown as Window & { hermesDesktop: { getGatewayWsUrlFor: (scope: { connectionId: string; profile: string }) => Promise<string | { ok: true; wsUrl: string } | { ok: false; error: string }> } }
    return bridge.hermesDesktop.getGatewayWsUrlFor({ connectionId: 'local', profile: 'default' })
  })
  const url = typeof minted === 'string' ? minted : minted.ok ? minted.wsUrl : undefined
  expect(url).toMatch(/^ws:\/\/127\.0\.0\.1:/)
  const client = new JsonRpcGatewayClient({ connectTimeoutMs: 15_000, requestTimeoutMs: 40_000 })
  try { await client.connect(url!); return client } catch (error) { client.close(); throw error }
}

function stopActualCold(identities: OwnedProcess[]) {
  expect(identities.length).toBeGreaterThan(0)
  const script = [
    'import json,sys,os,psutil',
    'failures=[]; owned=[]',
    'for identity in json.load(sys.stdin):',
    '    try:',
    '        process=psutil.Process(identity["pid"])',
    '        if process.create_time()!=identity["created"]: continue',
    '        assert os.path.normcase(process.exe())==os.path.normcase(identity["executable"]) and process.cmdline()==identity["argv"]',
    '        owned.append(process)',
    '    except psutil.NoSuchProcess: pass',
    '    except BaseException as error: failures.append(repr(error))',
    'for process in reversed(owned):',
    '    try:',
    '        process.terminate()',
    '        try: process.wait(5)',
    '        except psutil.TimeoutExpired: process.kill(); process.wait(5)',
    '    except psutil.NoSuchProcess: pass',
    '    except BaseException as error: failures.append(repr(error))',
    'print(json.dumps({"failures":failures,"selected":len(owned)}))',
    'assert not failures, failures'
  ].join('\n')
  const result = spawnSync(python, ['-I', '-c', script], { input: JSON.stringify(identities), encoding: 'utf8', windowsHide: true, timeout: 30_000 })
  expect(result.error).toBeUndefined()
  expect(result.status, result.stderr).toBe(0)
  return JSON.parse(result.stdout) as { failures: string[]; selected: number }
}

async function nativeCold(home: string, nonce: string, permission: 'allowed' | 'denied') {
  const receipt = path.join(home, nonce + '.json')
  const script = path.join(import.meta.dirname, 'mcp-oauth-worker-cold.py')
  const output: string[] = []
  const failures: unknown[] = []
  let primaryFailure: unknown
  let hasPrimaryFailure = false
  let identities: OwnedProcess[] = []
  const attempt = async (action: () => Promise<void> | void) => { try { await action() } catch (error) { failures.push(error) } }
  const child = spawn(python, ['-u', script, home, nonce, permission, receipt], { env: { ...process.env, HERMES_HOME: home }, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
  try {
    child.stdout.on('data', bytes => output.push(String(bytes)))
    child.stderr.on('data', bytes => output.push(String(bytes)))
    child.on('error', error => failures.push(error))
    expect(child.pid).toBeDefined()
    identities = captureOwnedTree(python, child.pid!)
    expect(identities.some(row => row.argv.includes(script) && row.argv.includes(home))).toBe(true)
    await expect.poll(() => fs.existsSync(receipt.replace(/\.json$/, '.birth.json')), { timeout: 10_000 }).toBe(true)
    const birth = JSON.parse(fs.readFileSync(receipt.replace(/\.json$/, '.birth.json'), 'utf8')) as OwnedProcess
    identities = captureOwnedTree(python, child.pid!)
    expect(identities.find(row => row.pid === birth.pid)).toEqual(birth)
    expect(birth.argv).toContain(script)
    expect(birth.argv).toContain(home)
    fs.writeFileSync(receipt.replace(/\.json$/, '.observed'), 'observed', { encoding: 'utf8', flag: 'wx' })
    await expect.poll(() => child.exitCode !== null || child.signalCode !== null, { timeout: 60_000 }).toBe(true)
    expect(child.exitCode, output.join('')).toBe(0)
    expect(child.signalCode).toBeNull()
    const evidence = JSON.parse(fs.readFileSync(receipt, 'utf8')) as { birth: OwnedProcess; nonce: string; permission: string; hook_sha256: string; imports: Record<string, { path: string; sha256: string }>; cleanup_completed: boolean; cleanup_failures: string[]; primary_failure: null | string }
    expect(evidence.birth).toEqual(birth)
    expect(evidence.nonce).toBe(nonce)
    expect(evidence.permission).toBe(permission)
    expect(evidence.hook_sha256).toBe(sourceHash(script))
    expect(evidence.cleanup_completed).toBe(true)
    expect(evidence.cleanup_failures).toEqual([])
    expect(evidence.primary_failure).toBeNull()
    for (const record of Object.values(evidence.imports)) {
      expect(path.resolve(record.path).startsWith(repository + path.sep)).toBe(true)
      expect(record.sha256).toBe(sourceHash(record.path))
    }
    await test.info().attach(nonce, { path: receipt, contentType: 'application/json' })
  } catch (error) { primaryFailure = error; hasPrimaryFailure = true } finally {
    await attempt(() => {
      if (child.exitCode === null && child.signalCode === null && child.pid) {
        if (!identities.length) {
          identities = captureOwnedTree(python, child.pid)
          expect(identities.some(row => row.argv.includes(script) && row.argv.includes(home))).toBe(true)
        }
        failures.push(new Error('Cold process required forced test-owned cleanup; native qualification invalid'))
        stopActualCold(identities)
      }
    })
    await attempt(async () => { await expect.poll(() => survivingOwnedProcesses(python, identities), { timeout: 10_000 }).toEqual([]) })
    await attempt(() => { child.stdout.destroy() })
    await attempt(() => { child.stderr.destroy() })
    await attempt(async () => { await test.info().attach(nonce + '-process-cleanup', { body: JSON.stringify({ identities, output, failures: failures.map(String) }), contentType: 'application/json' }) })
  }
  if (failures.length) { throw new AggregateError(hasPrimaryFailure ? [primaryFailure, ...failures] : failures, 'Owned cold process cleanup failed') }
  if (hasPrimaryFailure) { throw primaryFailure }
}

for (const mode of ['constructor', 'bootstrap_held']) {
  test(`actual Electron Gateway worker startup ${mode}`, async () => {
    test.setTimeout(420_000)
    allowErrorBanners()
    const issuer = await peer()
    let sandbox: ReturnType<typeof createSandbox> | undefined
    let bootstrap: ReturnType<typeof workerBootstrap> | undefined
    let mock: Awaited<ReturnType<typeof startMockServer>> | undefined
    let launched: Awaited<ReturnType<typeof launchDesktop>> | undefined
    let gateway: JsonRpcGatewayClient | undefined
    const identities: OwnedProcess[] = []
    const callbacks: string[] = []
    const failures: unknown[] = []
    let primaryFailure: unknown
    let hasPrimaryFailure = false
    let failedSessionId: string | undefined
    let successfulSessionId: string | undefined
    try {
      mock = await startMockServer({ scriptedTurns: [
        { text: '', toolCalls: [{ name: 'tool_call', args: { name: 'mcp__reports__write_sentinel', arguments: { nonce: 'native-worker-warm-' + mode } } }] },
        { text: 'M03 native worker recovery completed.' }
      ] })
      sandbox = createSandbox('m03-worker-startup')
      expect(path.dirname(path.resolve(sandbox.root))).toBe(ownedRoot)
      expect(ownedRoot).toBe(path.join(repository, 'tmp/probes/v0216-20261010/temp'))
      const extra = `security:\n  allow_lazy_installs: false\nmcp_servers:\n  reports:\n    url: ${JSON.stringify(issuer.ready.mcp_url)}\n    transport: http\n    auth: oauth\n    oauth: {cimd: false}\n    timeout: 5`
      writeMockProviderConfig(sandbox.hermesHome, mock.url, undefined, extra, 262144)
      writeEnvFile(sandbox.hermesHome)
      const other = path.join(sandbox.hermesHome, 'profiles/other')
      fs.mkdirSync(other, { recursive: true })
      fs.copyFileSync(path.join(sandbox.hermesHome, 'config.yaml'), path.join(other, 'config.yaml'))
      bootstrap = workerBootstrap(sandbox, mode)
      launched = await launchDesktop(buildAppEnv(sandbox, { HERMES_TUI_TOOLSETS: 'reports', PYTHONPATH: bootstrap.directory }))
      await waitForAppReady({ ...launched, mock, mockUrl: mock.url, sandbox, cleanup: async () => {} })
      identities.push(...captureOwnedTree(python, launched.app.process().pid!))
      await expect.poll(() => bootstrap!.observations().filter(row => row.kind === 'public_observer_ready' && path.resolve(row.actual_home!) === path.resolve(sandbox!.hermesHome)).length, { timeout: 30_000 }).toBe(1)
      const chat = await launched.page.evaluate(() => window.location.hash)
      await launched.app.evaluate(async ({ shell }) => {
        const http = process.getBuiltinModule('node:http')
        const state = globalThis as typeof globalThis & { m03WorkerUrls: string[]; m03WorkerServers: NativeServerRecord[]; m03WorkerRestore: () => void }
        state.m03WorkerUrls = []; state.m03WorkerServers = []
        const originalOpen = shell.openExternal
        const originalListen = http.Server.prototype.listen
        const originalClose = http.Server.prototype.close
        const ids = new WeakMap<import('node:http').Server, number>()
        let next = 0
        state.m03WorkerRestore = () => { shell.openExternal = originalOpen; http.Server.prototype.listen = originalListen; http.Server.prototype.close = originalClose }
        http.Server.prototype.listen = function (this: import('node:http').Server, ...args: unknown[]) {
          const id = ++next
          ids.set(this, id)
          this.once('listening', () => {
            const address = this.address()
            const row = { object_id: id, port: address && typeof address !== 'string' ? address.port : null, address: address && typeof address !== 'string' ? address.address : null }
            state.m03WorkerServers.push({ kind: 'listening', ...row })
            this.once('close', () => state.m03WorkerServers.push({ kind: 'closed', ...row }))
          })
          return Reflect.apply(originalListen, this, args) as import('node:http').Server
        } as typeof originalListen
        http.Server.prototype.close = function (...args: Parameters<typeof originalClose>) {
          const address = this.address()
          state.m03WorkerServers.push({ kind: 'close-request', object_id: ids.get(this) ?? -1,
            port: address && typeof address !== 'string' ? address.port : null, address: address && typeof address !== 'string' ? address.address : null })
          return Reflect.apply(originalClose, this, args) as import('node:http').Server
        }
        shell.openExternal = async (url: string) => { state.m03WorkerUrls.push(url) }

      })
      const urls = () => launched!.app.evaluate(() => (globalThis as typeof globalThis & { m03WorkerUrls: string[] }).m03WorkerUrls)
      const nativeServers = () => launched!.app.evaluate(() => (globalThis as typeof globalThis & { m03WorkerServers: NativeServerRecord[] }).m03WorkerServers)
      const publicProbe = await launched.page.evaluate(async () => {
        const bridge = window as unknown as Window & { hermesDesktop: { mcpOauth: { listen: () => Promise<{ id: string; redirectUri: string }>; cancel: (id: string) => Promise<boolean> } } }
        const listener = await bridge.hermesDesktop.mcpOauth.listen()
        await bridge.hermesDesktop.mcpOauth.cancel(listener.id)
        return listener
      })
      callbacks.push(publicProbe.redirectUri)
      await assertLoopbackListenerStopped(publicProbe.redirectUri)
      await test.info().attach('worker-actual-public-preload-probe', { body: JSON.stringify(publicProbe), contentType: 'application/json' })
      const profileRail = launched.page.getByRole('group', { name: 'Profiles', exact: true })
      await authenticate(launched.page)
      const gateKind = mode === 'constructor' ? 'constructor_failure_gate' : 'native_failure_gate'
      await expect.poll(() => bootstrap!.observations().filter(row => row.kind === gateKind).length, { timeout: 30_000 }).toBe(1)
      if (mode === 'bootstrap_held') {
        await profileRail.getByRole('button', { name: 'other', exact: true }).click()
        await expect(profileRail.getByRole('button', { name: 'other', exact: true })).toHaveAttribute('aria-pressed', 'true', { timeout: 45_000 })
      }
      bootstrap.release('return-failure')
      await expect.poll(() => bootstrap!.observations().filter(row => row.kind === 'public_rpc' && row.action === 'start' && row.response?.error?.message === workerCause).length, { timeout: 15_000 }).toBe(1)
      const start = bootstrap.observations().find(row => row.kind === 'public_rpc' && row.action === 'start' && row.response?.error?.message === workerCause)!
      expect(start.response!.error!.code).toBe(5024)
      expect(start.response!.error!.data?.kind).toBe('mcp_oauth_startup_failure')
      expect(start.response!.error!.data?.server_name).toBe('reports')
      failedSessionId = start.response!.error!.data?.session_id
      expect(failedSessionId).toMatch(/^[A-Za-z0-9_-]+$/)
      expect(start.params!.name).toBe('reports')
      const failedRedirect = String(start.params!.client_redirect_uri)
      expect(failedRedirect).toMatch(/^http:\/\/127\.0\.0\.1:\d+\/callback$/)
      callbacks.push(failedRedirect)
      await expect.poll(() => bootstrap!.observations().filter(row => row.kind === 'public_rpc' && row.action === 'cancel' && row.params?.session_id === failedSessionId).length, { timeout: 15_000 }).toBe(1)
      const cancel = bootstrap.observations().find(row => row.kind === 'public_rpc' && row.action === 'cancel' && row.params?.session_id === failedSessionId)!
      expect(cancel.birth).toEqual(start.birth)
      expect(cancel.params!.profile).toEqual(start.params!.profile)
      expect(cancel.params!.name).toBe(start.params!.name)
      expect(cancel.response!.result!.ok).toBe(true)
      await assertLoopbackListenerStopped(failedRedirect)
      const failedPort = Number(new URL(failedRedirect).port)
      await expect.poll(async () => (await nativeServers()).filter(row => row.kind === 'closed' && row.port === failedPort).length).toBe(1)
      expect((await nativeServers()).filter(row => row.kind === 'listening' && row.port === failedPort)).toHaveLength(1)
      expect(await urls()).toEqual([])
      expect(bootstrap.observations().filter(row => row.kind === 'public_rpc' && row.action === 'callback')).toEqual([])
      expect((await issuer.request('ledger')).ledger!.filter(row => ['token_request', 'token_redemption', 'sentinel'].includes(row.operation))).toEqual([])
      const token = path.join(sandbox.hermesHome, 'mcp-tokens/reports.json')
      expect(fs.existsSync(token)).toBe(false)
      expect(fs.existsSync(path.join(other, 'mcp-tokens/reports.json'))).toBe(false)
      if (mode === 'constructor') { await expect(launched.page.getByRole('alert').filter({ hasText: workerCause })).toBeVisible() }
      const actualIdentities = captureOwnedTree(python, launched.app.process().pid!)
      identities.push(...actualIdentities)
      expect(actualIdentities.find(row => row.pid === start.birth.pid)).toEqual(start.birth)
      const records = bootstrap.observations().filter(row => row.birth.pid === start.birth.pid)
      expect(records.filter(row => row.kind === 'bootstrap_bound')).toHaveLength(1)
      expect(records.filter(row => row.kind === 'installed_sdk_binding')).toHaveLength(1)
      expect(records.find(row => row.kind === 'installed_sdk_binding')!.sha256).toBe('912f43f60a023b66b05d102a5f2312affbccb6a626644f195aa6739d52c8717c')
      expect(records.filter(row => row.kind === 'worker_hook_ready')).toHaveLength(1)
      expect(records.find(row => row.kind === 'worker_hook_ready')!.control_original_start_attempted).toBe(true)
      expect(records.find(row => row.kind === 'worker_hook_ready')!.control_actual_started).toBe(true)
      for (const [module, binding] of Object.entries(bootstrap.configuration.modules)) {
        const bound = records.find(row => row.kind === 'module_binding' && row.module === module)
        expect(bound).toBeDefined(); expect(bound!.active).toBe(true)
        expect(bound!.sha256).toBe(binding.sha256)
        expect(path.resolve(bound!.path!)).toBe(path.resolve(repository, binding.path))
      }
      if (mode === 'bootstrap_held') {
        const acquisition = records.find(row => row.kind === 'native_before_ident')!
        expect(acquisition.native_acquired).toBe(true); expect(acquisition.native_id).toBeGreaterThan(0)
        expect(acquisition.ident).toBeNull(); expect(acquisition.actual_started_event).toBe(false)
        expect(acquisition.worker_done).toBe(false)
        expect(cancel.response!.result!.cancelled).toBe(false)
        expect(cancel.response!.result!.status).toBe('error')
        expect(cancel.owner_rows!.find(row => row.flow_id === failedSessionId)!.worker_done).toBe(false)
      }
      gateway = await workerGateway(launched.page)
      const ownerParams = { name: 'reports', profile: start.params!.profile, session_id: failedSessionId }
      const owner = await gateway.request<Record<string, unknown>>('mcp.servers.oauth.poll', ownerParams)
      expect(owner.error_message).toBe(workerCause)
      const foreign = await gateway.request<Record<string, unknown>>('mcp.servers.oauth.poll', { ...ownerParams, profile: 'other' })
      expect(foreign.error_message).toBe('OAuth session not found or expired')
      expect(foreign.session_id).toBeUndefined()
      if (mode === 'bootstrap_held') {
        let duplicate: unknown
        try { await gateway.request('mcp.servers.oauth.start', { name: 'reports', profile: start.params!.profile }, 40_000) } catch (error) { duplicate = error }
        expect(duplicate).toBeInstanceOf(JsonRpcGatewayError)
        expect((duplicate as JsonRpcGatewayError).code).toBe(5024)
        expect((duplicate as JsonRpcGatewayError).data).toBeUndefined()
        expect((duplicate as Error).message).toBe("MCP OAuth for 'reports' is already in progress")
        expect(bootstrap.observations().filter(row => row.kind === 'public_rpc' && row.action === 'start').at(-1)!.owner_rows!.find(row => row.flow_id === failedSessionId)!.worker_done).toBe(false)
      }
      bootstrap.release('release-worker')
      await expect.poll(() => bootstrap!.observations().filter(row => row.kind === 'failed_start_cleanup' && row.completed).length, { timeout: 45_000 }).toBe(1)
      expect(bootstrap.observations().filter(row => row.kind === 'operational_failure')).toEqual([])
      const cleanup = bootstrap.observations().find(row => row.kind === 'failed_start_cleanup')!
      expect(cleanup.failures).toEqual([])
      if (mode === 'bootstrap_held') { expect(bootstrap.observations().find(row => row.kind === 'native_worker_joined')!.flow_id).toBe(failedSessionId) }
      else { expect(bootstrap.observations().find(row => row.kind === 'constructor_settled')!.flow_id).toBe(failedSessionId) }
      if (mode === 'bootstrap_held') {
        await profileRail.getByRole('button', { name: 'Switch to default', exact: true }).click()
        await expect(profileRail.getByRole('button', { name: 'Show all profiles', exact: true })).toHaveAttribute('aria-pressed', 'true', { timeout: 5_000 })
        await launched.page.evaluate(() => { window.location.hash = '#/skills?tab=mcp' })
        const retryServer = launched.page.locator('#mcp-server-reports button').first()
        await expect(retryServer).toBeVisible({ timeout: 30_000 })
        await retryServer.click()
      }
      const retryAuthenticate = launched.page.getByRole('button', { name: 'Authenticate', exact: true })
      await expect(retryAuthenticate).toBeVisible({ timeout: 30_000 })
      await retryAuthenticate.click()
      await expect.poll(async () => (await urls()).length, { timeout: 40_000 }).toBe(1)
      const authorization = (await urls())[0]
      const callback = await issuer.request('authorize', { url: authorization })
      callbacks.push(callback.redirect!)
      const response = await fetch(`${callback.redirect}?${new URLSearchParams({ code: callback.code!, state: callback.state!, iss: callback.iss! })}`, { signal: AbortSignal.timeout(5_000) })
      expect(response.status).toBe(200); await response.text()
      await assertLoopbackListenerStopped(callback.redirect!)
      await expect.poll(() => fs.existsSync(token), { timeout: 30_000 }).toBe(true)
      expect(JSON.parse(fs.readFileSync(token, 'utf8')).access_token).toBe('owned-synthetic-token')
      await expect.poll(() => bootstrap!.observations().filter(row => row.kind === 'public_rpc' && row.action === 'start' && row.response?.result?.ok).length).toBe(1)
      successfulSessionId = String(bootstrap.observations().find(row => row.kind === 'public_rpc' && row.action === 'start' && row.response?.result?.ok)!.response!.result!.session_id)
      expect(successfulSessionId).not.toBe(failedSessionId)
      await launched.page.evaluate(hash => { window.location.hash = hash }, chat)
      const composer = launched.page.locator('[contenteditable="true"]').first()
      await composer.fill('M03 invoke the actual registry tool after startup recovery')
      await launched.page.keyboard.press('Enter')
      await expect(launched.page.locator('[data-slot="aui_thread-viewport"]')).toContainText('M03 native worker recovery completed.', { timeout: 120_000 })
      await nativeCold(sandbox.hermesHome, 'native-worker-cold-allowed-' + mode, 'allowed')
      await nativeCold(other, 'native-worker-cold-denied-' + mode, 'denied')
      const ledger = (await issuer.request('ledger')).ledger!
      expect(ledger.filter(row => row.operation === 'token_redemption')).toHaveLength(1)
      expect(ledger.filter(row => row.operation === 'sentinel').map(row => row.nonce)).toEqual(['native-worker-warm-' + mode, 'native-worker-cold-allowed-' + mode])
      expect(fs.existsSync(path.join(other, 'mcp-tokens/reports.json'))).toBe(false)
      await test.info().attach('native-worker-issuer-ledger', { body: JSON.stringify(ledger), contentType: 'application/json' })
    } catch (error) { primaryFailure = error; hasPrimaryFailure = true } finally {
      const attempt = async (action: () => Promise<void> | void) => { try { await action() } catch (error) { failures.push(error) } }
      if (bootstrap) {
        await attempt(() => bootstrap!.release('return-failure'))
        await attempt(() => bootstrap!.release('release-worker'))
        await attempt(() => bootstrap!.release('finish'))
        let controlObserved = false
        await attempt(() => { controlObserved = bootstrap!.observations().some(row => row.kind === 'worker_hook_ready') })
        if (controlObserved) {
          await attempt(async () => { await expect.poll(() => bootstrap!.observations().filter(row => row.kind === 'control_completed').length, { timeout: 60_000 }).toBe(1) })
          await attempt(async () => {
            if (!gateway && launched) { gateway = await workerGateway(launched.page) }
            expect(gateway).toBeDefined()
            // Existing read method, no fabricated owner identity or new RPC.
            try { await gateway!.request('mcp.servers.oauth.poll', { name: 'reports', ...(successfulSessionId || failedSessionId ? { session_id: successfulSessionId ?? failedSessionId } : {}) }) }
            catch (error) { expect(error).toBeInstanceOf(JsonRpcGatewayError); expect((error as JsonRpcGatewayError).code).toBe(4063) }
            await expect.poll(() => bootstrap!.observations().filter(row => row.kind === 'control_joined').length).toBe(1)
            const joined = bootstrap!.observations().find(row => row.kind === 'control_joined')!
            expect(joined.actual_join_confirmed).toBe(true); expect(joined.rpc_handlers_restored).toBe(true)
            expect(joined.completed).toBe(true); expect(joined.failures).toEqual([])
          })
        }
        await attempt(async () => {
          const rows = bootstrap!.observations()
          await test.info().attach('native-worker-operational-observations', { body: JSON.stringify(rows), contentType: 'application/json' })
          expect(rows.filter(row => row.kind === 'operational_failure')).toEqual([])
          await test.info().attach('native-worker-bootstrap-config', { body: JSON.stringify(bootstrap!.configuration), contentType: 'application/json' })
          await test.info().attach('native-worker-hook-observations', { body: JSON.stringify(rows), contentType: 'application/json' })
          for (const entry of fs.readdirSync(bootstrap!.directory, { withFileTypes: true })) {
            if (entry.isFile()) {
              await attempt(async () => { await test.info().attach('native-worker-owned-' + entry.name, { path: path.join(bootstrap!.directory, entry.name), contentType: entry.name.endsWith('.py') ? 'text/plain' : 'application/json' }) })
            }
          }
        })
      }
      await attempt(async () => { await test.info().attach('native-worker-issuer-ledger-at-cleanup', { body: JSON.stringify(await issuer.request('ledger')), contentType: 'application/json' }) })
      if (mock) { await attempt(async () => { await test.info().attach('native-worker-full-provider-requests', { body: JSON.stringify(mock!.receivedRequests), contentType: 'application/json' }) }) }
      if (sandbox) {
        await attempt(async () => {
          const logs = path.join(sandbox!.hermesHome, 'logs')
          if (fs.existsSync(logs)) {
            for (const name of fs.readdirSync(logs).filter(name => name.endsWith('.log'))) {
              await attempt(async () => { await test.info().attach('native-worker-backend-' + name, { path: path.join(logs, name), contentType: 'text/plain' }) })
            }
          }
        })
      }
      await attempt(() => gateway?.close())
      if (launched) {
        await attempt(async () => { await launched!.app.evaluate(() => (globalThis as typeof globalThis & { m03WorkerRestore?: () => void }).m03WorkerRestore?.()) })
        await attempt(() => { identities.push(...captureOwnedTree(python, launched!.app.process().pid!)) })
        await attempt(() => closeDesktop(launched!.app))
      }
      await attempt(() => issuer.close())
      if (mock) { await attempt(() => mock!.close()) }
      await attempt(async () => { await expect.poll(() => survivingOwnedProcesses(python, identities), { timeout: 15_000 }).toEqual([]) })
      for (const callback of callbacks) { await attempt(() => assertLoopbackListenerStopped(callback)) }
      if (mock) { await attempt(() => assertLoopbackListenerStopped(mock!.url)) }
      await attempt(async () => { await test.info().attach('native-worker-process-socket-cleanup', { body: JSON.stringify({ identities, failures: failures.map(String) }), contentType: 'application/json' }) })
    }
    if (failures.length) { throw new AggregateError(hasPrimaryFailure ? [primaryFailure, ...failures] : failures, 'Native worker startup cleanup failed') }
    if (hasPrimaryFailure) { throw primaryFailure }
  })
}
