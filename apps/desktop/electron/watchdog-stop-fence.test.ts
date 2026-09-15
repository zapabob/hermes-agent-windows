import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { test } from 'vitest'

import {
  clearDesktopStopFence,
  DESKTOP_STOP,
  waitForDesktopStopFenceAck,
  watchdogMaintenancePath,
  writeDesktopStopFence
} from './watchdog-stop-fence'

function temporaryFence() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-stop-fence-'))

  return { root, filePath: path.join(root, 'maintenance.json') }
}

test('normal Desktop quit persists until the same installation is explicitly launched', () => {
  const { root, filePath } = temporaryFence()
  const repoRoot = path.join(root, 'repo')
  const now = new Date('2026-09-06T01:00:00.000Z')

  const result = writeDesktopStopFence({ filePath, repoRoot, now })
  assert.equal(result.written, true)
  assert.equal(result.preserved, false)
  const stopped = JSON.parse(fs.readFileSync(filePath, 'utf8'))

  assert.equal(stopped.state, DESKTOP_STOP)
  assert.ok(Date.parse(stopped.leaseExpiresAt) > now.getTime())
  assert.equal(clearDesktopStopFence({ filePath, repoRoot: path.join(root, 'foreign'), now }), false)
  assert.equal(clearDesktopStopFence({ filePath, repoRoot, now }), true)
  assert.equal(JSON.parse(fs.readFileSync(filePath, 'utf8')).state, 'NORMAL')
})

test('Desktop quit waits for the exact watchdog maintenance acknowledgement', async () => {
  const { root, filePath } = temporaryFence()

  const result = writeDesktopStopFence({
    filePath,
    repoRoot: path.join(root, 'repo'),
    now: new Date('2026-09-06T01:00:00.000Z')
  })

  assert.equal(result.written, true)

  if (!result.written) {
    throw new Error('expected a new Desktop stop fence')
  }

  fs.writeFileSync(path.join(root, 'watchdog.lock'), JSON.stringify({ pid: 4242 }), 'utf8')
  fs.writeFileSync(
    path.join(root, 'watchdog.state.json'),
    JSON.stringify({
      maintenanceState: result.fence.state,
      maintenanceOwner: result.fence.owner,
      maintenanceNonce: result.fence.nonce,
      maintenanceEpoch: result.fence.epoch,
      maintenanceTimestamp: result.fence.timestamp
    }),
    'utf8'
  )

  assert.equal(
    await waitForDesktopStopFenceAck({
      fence: result.fence,
      filePath,
      isProcessAlive: () => true,
      timeoutMs: 0
    }),
    true
  )
})

test('Desktop quit remains cancelled when a live watchdog has not acknowledged the fence', async () => {
  const { root, filePath } = temporaryFence()

  const result = writeDesktopStopFence({
    filePath,
    repoRoot: path.join(root, 'repo'),
    now: new Date('2026-09-06T01:00:00.000Z')
  })

  assert.equal(result.written, true)

  if (!result.written) {
    throw new Error('expected a new Desktop stop fence')
  }

  fs.writeFileSync(path.join(root, 'watchdog.lock'), JSON.stringify({ pid: 4242 }), 'utf8')

  assert.equal(
    await waitForDesktopStopFenceAck({
      fence: result.fence,
      filePath,
      isProcessAlive: () => true,
      timeoutMs: 0
    }),
    false
  )
})

test('normal Desktop quit never overwrites a live updater fence', () => {
  const { root, filePath } = temporaryFence()

  const update = {
    state: 'UPDATE',
    owner: 'hermes-update:42',
    leaseExpiresAt: '2026-09-06T02:00:00.000Z'
  }

  fs.writeFileSync(filePath, JSON.stringify(update), 'utf8')
  assert.deepEqual(writeDesktopStopFence({ filePath, repoRoot: root, now: new Date('2026-09-06T01:00:00.000Z') }), {
    written: false,
    preserved: true
  })
  assert.deepEqual(JSON.parse(fs.readFileSync(filePath, 'utf8')), update)
})

test('watchdog data override selects the Go watchdog maintenance file', () => {
  assert.equal(
    watchdogMaintenancePath({ HERMES_WATCHDOG_DATA: 'C:\\WatchdogState' }),
    path.join('C:\\WatchdogState', 'maintenance.json')
  )
})

test('Windows default and portable fallback match the Go watchdog data paths', () => {
  assert.equal(
    watchdogMaintenancePath({ LOCALAPPDATA: 'C:\\Users\\test\\AppData\\Local' }),
    path.join('C:\\Users\\test\\AppData\\Local', 'HermesWatchdog', 'maintenance.json')
  )
  assert.equal(watchdogMaintenancePath({}), path.join(os.homedir(), '.hermes', 'watchdog-go', 'maintenance.json'))
})

/**
 * C2 regression (951dad8f…): DESKTOP_STOP ownership is keyed by mutable
 * checkout `repoRoot`. Writer and clearer can observe different absolute roots
 * for the SAME Windows Desktop deployment:
 *   - writer:  %HERMES_HOME%\hermes-agent   (.hermes\hermes-agent)
 *   - clearer: Documents\...\hermes-agent   (source / HERMES_DESKTOP_HERMES_ROOT)
 * Exact-path equality then refuses clear → DESKTOP_STOP lingers → watchdog
 * stays in maintenance → healthy backend is not re-attached after restart.
 *
 * Contract: Desktop lifecycle identity ≠ repo checkout path. Clear must succeed
 * across equivalent roots of one installation; a foreign HERMES_HOME must still
 * be rejected. Backend process identity is out of scope for the fence module
 * but the restart path must leave it unchanged (asserted as a fixture here).
 */
test('clears DESKTOP_STOP across equivalent Windows desktop roots before reconnecting', () => {
  const { root, filePath } = temporaryFence()
  const hermesHome = path.join(root, '.hermes')
  const activeRoot = path.join(hermesHome, 'hermes-agent')
  const documentsRoot = path.join(root, 'Documents', 'New project', 'hermes-agent')
  const foreignHome = path.join(root, 'other-profile', '.hermes')
  const now = new Date('2026-09-15T12:19:02.311Z')
  const later = new Date('2026-09-15T22:15:00.000Z')

  // Fixture: one healthy watchdog-managed backend that must survive restart.
  const backendBefore = { pid: 12692, port: 9119, baseUrl: 'http://127.0.0.1:9119', creationCount: 1 }
  let backendAfter = { ...backendBefore }

  fs.mkdirSync(activeRoot, { recursive: true })
  fs.mkdirSync(documentsRoot, { recursive: true })

  // On-disk shape of a C2 fence: ownership keyed ONLY by repoRoot (no lifecycle id).
  fs.writeFileSync(
    filePath,
    `${JSON.stringify(
      {
        schemaVersion: 1,
        state: DESKTOP_STOP,
        owner: 'hermes-desktop-intentional-stop',
        nonce: 'd7b3119c578140dfa86e2cd5039adcdb',
        epoch: 1789474742311000,
        timestamp: now.toISOString(),
        reason: 'User intentionally closed Hermes Desktop',
        leaseSeconds: 315360000,
        leaseExpiresAt: '2036-09-12T12:19:02.311Z',
        pid: 2868,
        processStartTime: null,
        repoRoot: path.resolve(activeRoot)
      },
      null,
      2
    )}\n`,
    'utf8'
  )

  assert.equal(JSON.parse(fs.readFileSync(filePath, 'utf8')).state, DESKTOP_STOP)

  // Pure checkout-path clear (C2 clearer observing Documents) — must not be
  // the ownership model; with only repoRoot equality this stays false.
  assert.equal(
    clearDesktopStopFence({
      filePath,
      repoRoot: documentsRoot,
      now: later
    }),
    false,
    'Documents vs .hermes\\hermes-agent must not match on raw repoRoot equality'
  )

  // Foreign HERMES_HOME must still be refused (ownership boundary intact).
  assert.equal(
    clearDesktopStopFence({
      filePath,
      hermesHome: foreignHome,
      equivalentRoots: [path.join(foreignHome, 'hermes-agent'), documentsRoot],
      now: later
    }),
    false,
    'foreign HERMES_HOME / install must not clear DESKTOP_STOP'
  )
  assert.equal(JSON.parse(fs.readFileSync(filePath, 'utf8')).state, DESKTOP_STOP)

  // Same Desktop lifecycle: clearer observes Documents checkout spelling but
  // owns the shared hermesHome. Must clear without normalizing the two roots
  // into each other.
  const cleared = clearDesktopStopFence({
    filePath,
    hermesHome,
    repoRoot: documentsRoot,
    equivalentRoots: [documentsRoot],
    now: later
  })

  assert.equal(
    cleared,
    true,
    'repoRoot identity mismatch -> DESKTOP_STOP not cleared (Desktop lifecycle identity must not be the mutable checkout path)'
  )
  assert.equal(JSON.parse(fs.readFileSync(filePath, 'utf8')).state, 'NORMAL')

  // After clear, attach to the existing healthy backend — no respawn.
  const reconnectAllowed = JSON.parse(fs.readFileSync(filePath, 'utf8')).state === 'NORMAL'
  assert.equal(reconnectAllowed, true)
  assert.equal(backendAfter.pid, backendBefore.pid)
  assert.equal(backendAfter.port, backendBefore.port)
  assert.equal(backendAfter.creationCount, 1)
  assert.equal(backendAfter.creationCount, backendBefore.creationCount)

  backendAfter = { ...backendBefore }
  assert.deepEqual(backendAfter, backendBefore)
})
