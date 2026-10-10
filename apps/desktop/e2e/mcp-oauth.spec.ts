import { spawn } from 'node:child_process'
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
