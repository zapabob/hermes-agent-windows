import * as fs from 'node:fs'
import * as path from 'node:path'

import { setupMockBackend, waitForAppReady } from './fixtures'
import { assertLoopbackListenerStopped, captureOwnedTree, type OwnedProcess, survivingOwnedProcesses } from './owned-process-observer'
import { allowErrorBanners, expect, type Page, test } from './test'

const python = path.resolve(import.meta.dirname, '../../../.venv/Scripts/python.exe')
const conversationRequests = (fixture: Awaited<ReturnType<typeof setupMockBackend>>) =>
  fixture.mock.receivedRequests.filter(request => Array.isArray(request.tools) && request.tools.length > 0)

async function auditCleanup(fixture: Awaited<ReturnType<typeof setupMockBackend>>, identities: OwnedProcess[]): Promise<void> {
  const child = fixture.app.process()
  const pid = child.pid
  const failures: unknown[] = []
  try {
    if (pid && child.exitCode === null) {identities.push(...captureOwnedTree(python, pid))}
    await test.info().attach('provider-requests', {
      body: JSON.stringify(fixture.mock.receivedRequests), contentType: 'application/json',
    })
    const logs = path.join(fixture.sandbox.hermesHome, 'logs')
    if (fs.existsSync(logs)) {
      for (const name of fs.readdirSync(logs).filter(name => name.endsWith('.log'))) {
        const file = path.join(logs, name)
        if (fs.statSync(file).size < 1_048_576) {await test.info().attach(name, { path: file, contentType: 'text/plain' })}
      }
    }
  } catch (error) {
    failures.push(error)
  } finally {
    try {
      await fixture.cleanup()
    } catch (error) {
      failures.push(error)
    }
  }
  const audits = await Promise.allSettled([
    expect.poll(() => survivingOwnedProcesses(python, identities), { timeout: 15_000 }).toEqual([]),
    assertLoopbackListenerStopped(fixture.mockUrl),
  ])
  for (const audit of audits) {if (audit.status === 'rejected') {failures.push(audit.reason)}}
  if (child.exitCode === null && child.signalCode === null) {failures.push(new Error('Owned Electron exit is unproven'))}
  if (failures.length) {throw new AggregateError(failures, 'F03 native cleanup or observation failed')}
  await test.info().attach('owned-process-exit-audit', {
    body: JSON.stringify({ identities, survivors: [], listenerStopped: true }), contentType: 'application/json',
  })
}

async function submit(page: Page, text: string): Promise<void> {
  const composer = page.locator('[contenteditable="true"]').first()
  await composer.click()
  await composer.fill(text)
  await page.keyboard.press('Enter')
}

for (const alias of ['/steer', '/s', '/S', '/s-empty', '/s-whitespace']) {
  test(`${alias} reaches a real tool boundary without stopping the tool`, async () => {
    test.setTimeout(240_000)
    const empty = alias.startsWith('/s-')
    if (empty) {allowErrorBanners()}
    const nonce = `F03_${alias.replace('/', '')}_日本語_KeepCase`
    const fixture = await setupMockBackend({ modelContextLength: 262144,
      extraEnv: { HERMES_TUI_TOOLSETS: 'clarify' },
      extraConfig: 'security:\n  allow_lazy_installs: false', mockServer: { scriptedTurns: [
      { text: '', toolCalls: [{ name: 'clarify', args: { question: 'F03 hold the real tool?', choices: ['Continue', 'Wait'] } }] },
      { text: 'F03 native boundary completed.' }
    ] } })
    const identities: OwnedProcess[] = []
    try {
      await waitForAppReady(fixture)
      identities.push(...captureOwnedTree(python, fixture.app.process().pid!))
      await submit(fixture.page, 'F03 run the real clarify tool')
      const pending = fixture.page.locator('[data-clarify-choices]')
      await expect(pending).toBeVisible({ timeout: 120_000 })
      await expect(fixture.page.getByText('F03 hold the real tool?', { exact: true })).toBeVisible()
      await submit(fixture.page, empty ? (alias === '/s-empty' ? '/s' : '/s    ') : `${alias} ${nonce}`)
      if (empty) {await expect(fixture.page.locator('[data-slot="aui_thread-viewport"]')).toContainText('usage: /steer <prompt>')}
      else {await expect(fixture.page.locator('[data-slot="aui_thread-viewport"]')).toContainText('Steer queued')}
      await expect(pending).toBeVisible()
      expect(conversationRequests(fixture)).toHaveLength(1)
      await pending.getByRole('button', { name: /^A Continue/ }).click()
      await pending.getByRole('button', { name: 'Continue', exact: true }).click()
      await expect.poll(() => conversationRequests(fixture).length, { timeout: 30_000 }).toBeGreaterThanOrEqual(2)
      const messages = conversationRequests(fixture)[1].messages as Record<string, unknown>[]
      const tool = messages.find(message => message.role === 'tool' && message.name === 'clarify')
      expect(tool).toBeDefined()
      expect(String(tool!.content)).toContain('Continue')
      expect(String(tool!.content).split(nonce)).toHaveLength(empty ? 1 : 2)
      if (empty) {expect(String(tool!.content)).not.toContain('HERMES_STEER')}
      expect(messages.filter(message => message.role === 'user' && String(message.content).includes(nonce))).toHaveLength(0)
      const previous = conversationRequests(fixture)[0].messages as Record<string, unknown>[]
      expect(messages.slice(0, previous.length)).toEqual(previous)
      await expect(fixture.page.locator('[data-slot="aui_thread-viewport"]')).toContainText('F03 native boundary completed.')
    } finally {
      await auditCleanup(fixture, identities)
    }
  })
}

test('idle /s preserves the next-turn payload and existing transcript', async () => {
  test.setTimeout(180_000)
  const fixture = await setupMockBackend({ modelContextLength: 262144,
    extraEnv: { HERMES_TUI_TOOLSETS: 'terminal' },
    extraConfig: 'security:\n  allow_lazy_installs: false', mockServer: { scriptedTurns: [
    { text: 'F03 first completed.' }, { text: 'F03 idle completed.' },
  ] } })
  const identities: OwnedProcess[] = []
  try {
    await waitForAppReady(fixture)
    identities.push(...captureOwnedTree(python, fixture.app.process().pid!))
    await submit(fixture.page, 'F03 initial retained prompt')
    const viewport = fixture.page.locator('[data-slot="aui_thread-viewport"]')
    await expect(viewport).toContainText('F03 first completed.', { timeout: 120_000 })
    await expect(fixture.page.getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0)
    const nonce = 'F03_IDLE_日本語_KeepCase'
    await submit(fixture.page, `/s ${nonce}`)
    await expect(viewport).toContainText('F03 idle completed.', { timeout: 30_000 })
    const prompts = conversationRequests(fixture).map(request =>
      (request.messages as Record<string, unknown>[]).filter(message => message.role === 'user').at(-1)?.content)
    expect(prompts).toEqual(['F03 initial retained prompt', nonce])
    await expect(viewport).toContainText('F03 initial retained prompt')
    await expect(viewport).toContainText('F03 first completed.')
    await expect(viewport).toContainText(nonce)
  } finally {
    await auditCleanup(fixture, identities)
  }
})

test('Stop cancels accepted /s and idle /s starts a fresh turn', async () => {
  test.setTimeout(240_000)
  allowErrorBanners()
  const cancelled = 'F03_CANCELLED_日本語_KeepCase'
  const fresh = 'F03_AFTER_STOP_日本語_KeepCase'
  const fixture = await setupMockBackend({ modelContextLength: 262144,
    extraEnv: { HERMES_TUI_TOOLSETS: 'clarify' },
    extraConfig: 'security:\n  allow_lazy_installs: false', mockServer: { scriptedTurns: [
      { text: '', toolCalls: [{ name: 'clarify', args: { question: 'F03 stop this real tool?', choices: ['Continue', 'Wait'] } }] },
      { text: 'F03 fresh turn after Stop completed.' },
    ] } })
  const identities: OwnedProcess[] = []
  try {
    await waitForAppReady(fixture)
    identities.push(...captureOwnedTree(python, fixture.app.process().pid!))
    await submit(fixture.page, 'F03 initial turn to cancel')
    await expect(fixture.page.locator('[data-clarify-choices]')).toBeVisible({ timeout: 120_000 })
    await submit(fixture.page, `/s ${cancelled}`)
    const viewport = fixture.page.locator('[data-slot="aui_thread-viewport"]')
    await expect(viewport).toContainText('Steer queued')
    expect(conversationRequests(fixture)).toHaveLength(1)
    const composerForm = fixture.page.locator('form').filter({ has: fixture.page.locator('[contenteditable="true"]') })
    await composerForm.getByRole('button', { name: 'Stop', exact: true }).click()
    await expect(fixture.page.getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0, { timeout: 30_000 })
    await submit(fixture.page, `/s ${fresh}`)
    await expect(viewport).toContainText('F03 fresh turn after Stop completed.', { timeout: 30_000 })
    const requests = conversationRequests(fixture)
    expect(requests).toHaveLength(2)
    const messages = requests[1].messages as Record<string, unknown>[]
    expect(messages.filter(message => message.role === 'user').at(-1)?.content).toBe(fresh)
    expect(JSON.stringify(messages)).not.toContain(cancelled)
    await expect(viewport).toContainText('F03 initial turn to cancel')
    await expect(viewport).toContainText(fresh)
  } finally {
    await auditCleanup(fixture, identities)
  }
})
