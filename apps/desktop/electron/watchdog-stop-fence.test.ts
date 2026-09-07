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
  assert.deepEqual(
    writeDesktopStopFence({ filePath, repoRoot: root, now: new Date('2026-09-06T01:00:00.000Z') }),
    { written: false, preserved: true }
  )
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
  assert.equal(
    watchdogMaintenancePath({}),
    path.join(os.homedir(), '.hermes', 'watchdog-go', 'maintenance.json')
  )
})
