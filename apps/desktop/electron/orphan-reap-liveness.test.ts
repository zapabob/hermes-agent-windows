import assert from 'node:assert/strict'
import { describe, test, vi } from 'vitest'

import {
  createBackendOwnership,
  parseBackendOwnership,
  type BackendIdentity,
  type BackendOwnershipEntry
} from './backend-ownership'
import { createLivenessMatchers } from './backend-liveness-matchers'
import { isPidAliveWindows } from './backend-release-gate'
import { processStartMarker } from './backend-claim'

function memoryStore(initial = '') {
  let contents = initial
  let quarantined = false

  return {
    read: () => contents,
    value: () => contents,
    write: (next: string) => {
      contents = next
    },
    quarantine: () => {
      quarantined = true
    },
    isQuarantined: () => quarantined
  }
}

describe('orphan reap cheap negative liveness gate contract', () => {
  test('1. dead full-identity backend -> processIdentityMatches = false, zero PowerShell marker probes', async () => {
    const markerProbe = vi.fn(async () => 'win:123456789')
    const matchers = createLivenessMatchers({
      isWindows: true,
      isPidAliveWindows: () => false,
      processStartMarker: markerProbe
    })

    const identity: BackendIdentity = {
      pid: 4242,
      nonce: 'nonce-1',
      profile: 'default',
      startMarker: 'win:123456789'
    }

    const result = await matchers.processIdentityMatches(identity)
    assert.equal(result, false)
    assert.equal(markerProbe.mock.calls.length, 0, 'Must not perform PowerShell marker probe for dead PID')
  })

  test('2. dead pid-only backend -> processIdentityMatches = false, record removed, zero PowerShell marker probes', async () => {
    const markerProbe = vi.fn(async () => 'win:123456789')
    const matchers = createLivenessMatchers({
      isWindows: true,
      isPidAliveWindows: () => false,
      processStartMarker: markerProbe
    })

    const identity: BackendIdentity = {
      pid: 4242,
      nonce: 'nonce-2',
      profile: 'default',
      startMarker: 'pid-only:4242'
    }

    const result = await matchers.processIdentityMatches(identity)
    assert.equal(result, false, 'Dead pid-only record must evaluate to false')
    assert.equal(markerProbe.mock.calls.length, 0, 'Zero PowerShell marker probes')

    const store = memoryStore(
      JSON.stringify({
        backends: [{ command: 'hermes serve --port 0', ...identity }]
      })
    )

    const stop = vi.fn()
    const ownership = createBackendOwnership({
      matchesIdentity: matchers.backendIdentityMatches,
      matchesParent: matchers.backendParentMatches,
      stop,
      store
    })

    await ownership.reapOrphans()
    assert.deepEqual(parseBackendOwnership(store.value()), [], 'Dead pid-only record must be removed from ledger')
    assert.equal(stop.mock.calls.length, 0, 'Must never call stop on dead record')
  })

  test('3. live pid-only backend -> undefined, record preserved, never authorized for stop', async () => {
    const markerProbe = vi.fn(async () => 'win:123456789')
    const matchers = createLivenessMatchers({
      isWindows: true,
      isPidAliveWindows: () => true,
      processStartMarker: markerProbe
    })

    const identity: BackendIdentity = {
      pid: 4242,
      nonce: 'nonce-3',
      profile: 'default',
      startMarker: 'pid-only:4242'
    }

    const result = await matchers.processIdentityMatches(identity)
    assert.equal(result, undefined, 'Live pid-only must return undefined (non-authoritative)')
    assert.equal(markerProbe.mock.calls.length, 0)

    const entry: BackendOwnershipEntry = { command: 'hermes serve --port 0', ...identity }
    const store = memoryStore(JSON.stringify({ backends: [entry] }))

    const stop = vi.fn()
    const ownership = createBackendOwnership({
      matchesIdentity: matchers.backendIdentityMatches,
      matchesParent: matchers.backendParentMatches,
      stop,
      store
    })

    await ownership.reapOrphans()
    assert.deepEqual(parseBackendOwnership(store.value()), [entry], 'Live pid-only record preserved for inspection')
    assert.equal(stop.mock.calls.length, 0, 'Live pid-only record must NEVER authorize stop')
  })

  test('4. dead recorded parent -> backendParentMatches = false, zero PowerShell parent-marker probes', async () => {
    const markerProbe = vi.fn(async () => 'win:parent999')
    const matchers = createLivenessMatchers({
      isWindows: true,
      isPidAliveWindows: (pid: number) => (pid === 4242), // parent (999) is dead
      processStartMarker: markerProbe
    })

    const entry: BackendOwnershipEntry = {
      command: 'hermes serve --port 0',
      pid: 4242,
      nonce: 'nonce-4',
      profile: 'default',
      startMarker: 'win:child4242',
      parentPid: 999,
      parentStartMarker: 'win:parent999'
    }

    const parentMatches = await matchers.backendParentMatches(entry)
    assert.equal(parentMatches, false, 'Dead parent must return false (not alive)')
    assert.equal(markerProbe.mock.calls.length, 0, 'Zero PowerShell probes for dead parent')
  })

  test('5. live full identity -> still performs full start-marker verification', async () => {
    const markerProbe = vi.fn(async (pid: number) => `win:incarnation-${pid}`)
    const matchers = createLivenessMatchers({
      isWindows: true,
      isPidAliveWindows: () => true,
      processStartMarker: markerProbe,
      backendCommandForPid: async () => 'python.exe -m hermes_cli.main serve --port 0'
    })

    const matchIdentity: BackendIdentity = {
      pid: 4242,
      nonce: 'nonce-5a',
      profile: 'default',
      startMarker: 'win:incarnation-4242'
    }

    const matchResult = await matchers.backendIdentityMatches(matchIdentity)
    assert.equal(matchResult, true, 'Live matching identity returns true')
    assert.equal(markerProbe.mock.calls.length, 1)

    const mismatchIdentity: BackendIdentity = {
      pid: 4242,
      nonce: 'nonce-5b',
      profile: 'default',
      startMarker: 'win:DIFFERENT-MARKER'
    }

    const mismatchResult = await matchers.backendIdentityMatches(mismatchIdentity)
    assert.equal(mismatchResult, false, 'Live mismatching marker returns false')
  })

  test('6. EPERM/inaccessible but potentially live PID -> do NOT classify dead, fall through safely', async () => {
    // isPidAliveWindows returns true when process.kill throws EPERM
    const fakeKill = vi.fn(() => {
      const err = new Error('operation not permitted') as any
      err.code = 'EPERM'
      throw err
    })

    const alive = isPidAliveWindows(1234, fakeKill)
    assert.equal(alive, true, 'EPERM must be treated as potentially live')

    const markerProbe = vi.fn(async () => {
      const err = new Error('access denied') as any
      err.code = 'EACCES'
      throw err
    })

    const matchers = createLivenessMatchers({
      isWindows: true,
      isPidAliveWindows: () => true, // simulates EPERM treating as live
      processStartMarker: markerProbe
    })

    const identity: BackendIdentity = {
      pid: 1234,
      nonce: 'nonce-6',
      profile: 'default',
      startMarker: 'win:1234'
    }

    const result = await matchers.processIdentityMatches(identity)
    // When marker probe throws EACCES (not ENOENT/ESRCH), result is undefined (safe fallback)
    assert.equal(result, undefined, 'EPERM/inaccessible falls through safely to undefined, never dead')
  })

  test('7. bulk stale ledger (100 dead ownership entries) -> one reap pass removes all dead records, zero PowerShell probes', async () => {
    const markerProbe = vi.fn(async () => 'win:probe')
    const matchers = createLivenessMatchers({
      isWindows: true,
      isPidAliveWindows: () => false, // all 100 entries are dead
      processStartMarker: markerProbe
    })

    const entries: BackendOwnershipEntry[] = Array.from({ length: 100 }, (_, i) => ({
      command: 'python.exe -m hermes_cli.main serve --port 0',
      pid: 10000 + i,
      nonce: `nonce-${i}`,
      profile: 'default',
      startMarker: `win:${100000 + i}`,
      parentPid: 20000 + i,
      parentStartMarker: `win:${200000 + i}`
    }))

    const store = memoryStore(JSON.stringify({ backends: entries }))
    const stop = vi.fn()

    const ownership = createBackendOwnership({
      matchesIdentity: matchers.backendIdentityMatches,
      matchesParent: matchers.backendParentMatches,
      stop,
      store
    })

    const reaped = await ownership.reapOrphans()
    assert.equal(reaped.length, 0, 'Dead processes do not need stop signal')
    assert.deepEqual(parseBackendOwnership(store.value()), [], 'All 100 dead entries removed in single pass')
    assert.equal(markerProbe.mock.calls.length, 0, 'Zero PowerShell probes executed across all 100 entries')
    assert.equal(stop.mock.calls.length, 0)
  })

  test('8. PID reuse: live process with same numeric PID but different startMarker -> false, never killed/adopted', async () => {
    const matchers = createLivenessMatchers({
      isWindows: true,
      isPidAliveWindows: () => true, // PID is alive
      processStartMarker: async () => 'win:NEW-REUSED-INCARNATION',
      backendCommandForPid: async () => 'python.exe -m hermes_cli.main serve --port 0'
    })

    const oldIdentity: BackendIdentity = {
      pid: 4242,
      nonce: 'nonce-8',
      profile: 'default',
      startMarker: 'win:OLD-DEAD-INCARNATION'
    }

    const entry: BackendOwnershipEntry = { command: 'hermes serve --port 0', ...oldIdentity }
    const store = memoryStore(JSON.stringify({ backends: [entry] }))
    const stop = vi.fn()

    const ownership = createBackendOwnership({
      matchesIdentity: matchers.backendIdentityMatches,
      matchesParent: async () => false, // parent is gone
      stop,
      store
    })

    await ownership.reapOrphans()
    assert.equal(stop.mock.calls.length, 0, 'Must NEVER call stop on a reused PID with mismatched incarnation')
    assert.deepEqual(parseBackendOwnership(store.value()), [], 'Dead incarnation entry dropped')
  })

  test('9. corrupt ownership file behavior unchanged -> quarantine/preserve evidence', async () => {
    const store = memoryStore('{ "backends": [ corrupted json ...')
    const stop = vi.fn()

    const ownership = createBackendOwnership({
      matchesIdentity: async () => false,
      matchesParent: async () => false,
      stop,
      store
    })

    const reaped = await ownership.reapOrphans()
    assert.deepEqual(reaped, [])
    assert.equal(store.isQuarantined(), true, 'Corrupted ownership store must be quarantined')
    assert.equal(store.value(), '{ "backends": [ corrupted json ...', 'Original file content preserved')
  })

  test('10. processStartMarker cheap dead-PID gate throws ESRCH without shelling out to PowerShell', async () => {
    // When PID is dead, processStartMarker on Windows must throw error with code = 'ESRCH'
    const deadPid = 2 ** 30 + 54321
    try {
      await processStartMarker(deadPid, () => false)
      assert.fail('Should have thrown')
    } catch (err: any) {
      assert.equal(err.code, 'ESRCH', 'Must set error.code = ESRCH')
      assert.match(err.message, /ESRCH/, 'Message mentions ESRCH')
    }
  })
})
