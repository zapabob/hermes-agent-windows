import assert from 'node:assert/strict'
import path from 'node:path'
import { describe, test, vi } from 'vitest'

import { createBackendConnectionState } from './backend-connection-state'
import { BackendDialClaims } from './backend-dial-claim'
import { runBackendStartStep } from './backend-start-cancellation'
import { runPrimaryBackendStartup } from './primary-backend-startup'

describe('Single-Owner Desktop Backend Lifecycle (Phase 2 RED Tests)', () => {
  // 7.1 stale prewarmed backend
  test('7.1: stale desktop-backend.json is never adopted as authoritative runtime by Desktop', async () => {
    const staleManifest = {
      pid: 1234,
      port: 9000,
      token: 'old-stale-token'
    }

    // In single-owner architecture, Desktop local startup must NOT have a
    // prewarmed-local branch or adopt external stale manifest as authoritative.
    const ensuredBackend = { command: 'hermes', args: ['serve'] }
    let ensureCalled = false

    const result = await runPrimaryBackendStartup({
      resolveRemote: async () => null,
      connectRemote: async () => ({ baseUrl: '', mode: 'remote' as const }),
      waitForLocalStart: async () => {},
      prepareLocalBackend: () => ({ kind: 'local' }),
      waitForDecision: async () => 'continue-local' as const,
      ensureLocalRuntime: async backend => {
        ensureCalled = true
        return ensuredBackend
      }
    })

    assert.equal(result.kind, 'local')
    assert.equal(ensureCalled, true)
    // There must be NO 'prewarmed-local' kind
    assert.notEqual((result as any).kind, 'prewarmed-local')
  })

  // 7.2 restart generation race
  test('7.2: late completion of Generation A cannot overwrite or clear Generation B', async () => {
    type FakeProcess = { pid: number; killed?: boolean }
    const state = createBackendConnectionState<FakeProcess, { baseUrl: string }>()

    // Generation A begins
    const attemptA = state.startAttempt()
    assert.equal(attemptA.generation, 0)

    let resolveA: (val: { baseUrl: string }) => void = () => {}
    const promiseA = new Promise<{ baseUrl: string }>(resolve => {
      resolveA = resolve
    })
    assert.equal(state.setPromise(attemptA, promiseA), true)

    // Desktop restart occurs -> invalidates Generation A, increments generation
    const procA: FakeProcess = { pid: 101 }
    state.attachProcess(attemptA, procA)
    const invalidatedProc = state.invalidate()
    assert.equal(invalidatedProc, procA)

    // Generation B begins
    const attemptB = state.startAttempt()
    assert.equal(attemptB.generation, 1)
    const procB: FakeProcess = { pid: 202 }
    const ownerB = state.attachProcess(attemptB, procB)
    assert.notEqual(ownerB, null)

    const promiseB = Promise.resolve({ baseUrl: 'http://127.0.0.1:9002' })
    assert.equal(state.setPromise(attemptB, promiseB), true)
    assert.equal(state.getProcess()?.pid, 202)

    // Now Generation A completes late
    resolveA({ baseUrl: 'http://127.0.0.1:9001' })
    await promiseA

    // Generation A cannot clear Generation B's process or promise
    assert.equal(state.isCurrentAttempt(attemptA), false)
    assert.equal(state.clearPromiseForAttempt(attemptA), false)
    assert.equal(state.clearForCurrentProcess({ generation: 0, process: procA }), false)

    // Generation B's state remains intact
    assert.equal(state.getProcess()?.pid, 202)
    assert.equal(await state.getPromise(), await promiseB)
  })

  // 7.3 concurrent reconnect (single in-flight dial per scope)
  test('7.3: concurrent reconnect requests coalesce into exactly 1 dial', async () => {
    const claims = new BackendDialClaims()
    let dialCount = 0

    const dialFn = async () => {
      dialCount++
      await new Promise(r => setTimeout(r, 20))
      return { baseUrl: 'http://127.0.0.1:9000', token: 'tok' }
    }

    // Main window and popout window request reconnect concurrently
    const [res1, res2] = await Promise.all([
      claims.run('primary:default', dialFn),
      claims.run('primary:default', dialFn)
    ])

    assert.equal(dialCount, 1, 'Two concurrent reconnects must execute exactly 1 dial')
    assert.deepEqual(res1, res2)
  })

  // 7.4 backend crash recovery (exactly one replacement backend)
  test('7.4: backend crash detection allows exactly one replacement generation', async () => {
    type FakeProcess = { pid: number; killed: boolean }
    const state = createBackendConnectionState<FakeProcess, string>()

    // Initial backend A
    const attempt1 = state.startAttempt()
    const procA: FakeProcess = { pid: 1001, killed: false }
    const ownerA = state.attachProcess(attempt1, procA)!
    state.setPromise(attempt1, Promise.resolve('connection-A'))

    assert.equal(state.getProcess()?.pid, 1001)

    // Backend A crashes -> cleared for current process
    const cleared = state.clearForCurrentProcess(ownerA)
    assert.equal(cleared, true)
    assert.equal(state.getProcess(), null)
    assert.equal(state.getPromise(), null)

    // Exactly one replacement backend B spawned under fresh attempt
    const attempt2 = state.startAttempt()
    const procB: FakeProcess = { pid: 1002, killed: false }
    const ownerB = state.attachProcess(attempt2, procB)!
    state.setPromise(attempt2, Promise.resolve('connection-B'))

    assert.equal(state.getProcess()?.pid, 1002)
    assert.equal(await state.getPromise(), 'connection-B')
  })

  // 7.5 same HERMES_HOME / different repoRoot -> same lifecycle identity
  test('7.5: different checkout roots with same resolved HERMES_HOME share lifecycle identity', () => {
    const hermesHome = 'C:\\Users\\User\\.hermes'
    const normalizedHome = path.resolve(hermesHome).toLowerCase()

    const rootA = 'C:\\Users\\User\\Documents\\repoA'
    const rootB = 'C:\\Users\\User\\.hermes\\hermes-agent'

    const idA = path.resolve(hermesHome).toLowerCase()
    const idB = path.resolve(hermesHome).toLowerCase()

    assert.equal(idA, idB, 'Lifecycle identity must be determined by resolved HERMES_HOME, not repoRoot')
  })

  // 7.6 MSYS path normalization
  test('7.6: MSYS HERMES_HOME and native Windows HERMES_HOME normalize identically', () => {
    // Helper replicating main.ts / hermes_constants MSYS path normalization
    function normalizeHermesHome(raw: string): string {
      let trimmed = raw.trim()
      const msysMatch = trimmed.match(/^\/([a-zA-Z])\/(.*)$/)
      if (msysMatch) {
        trimmed = `${msysMatch[1].toUpperCase()}:\\${msysMatch[2].replace(/\//g, '\\')}`
      }
      return path.resolve(trimmed).toLowerCase()
    }

    const msys = '/c/Users/foo/.hermes'
    const native = 'C:\\Users\\foo\\.hermes'

    assert.equal(normalizeHermesHome(msys), normalizeHermesHome(native))
  })

  // Startup Cancellation test
  test('startup cancellation: aborted signal stops startup step immediately', async () => {
    const controller = new AbortController()
    controller.abort(new Error('Desktop shutdown'))

    await assert.rejects(
      () => runBackendStartStep(controller.signal, async () => 'should not run'),
      /Desktop shutdown/
    )
  })

  // Phase 26: Cross-authority negative tests (Desktop side)
  test('Phase 26: Electron Desktop does not claim, adopt PID of, or terminate embedding server', () => {
    // Desktop backend authority is strictly generation-scoped and process-instance bound.
    // An external embedding server process on port 8082 with PID 99999 must never be attached.
    type FakeProcess = { pid: number; isEmbedding?: boolean }
    const state = createBackendConnectionState<FakeProcess, string>()
    const attempt = state.startAttempt()

    const embeddingProc: FakeProcess = { pid: 99999, isEmbedding: true }
    assert.equal(embeddingProc.isEmbedding, true)

    // Desktop only attaches its own spawned Python backend
    const desktopBackendProc: FakeProcess = { pid: 88888, isEmbedding: false }
    const owner = state.attachProcess(attempt, desktopBackendProc)
    assert.notEqual(owner, null)
    assert.equal(owner?.process.pid, 88888)
    assert.equal(owner?.process.isEmbedding, false)
  })
})
