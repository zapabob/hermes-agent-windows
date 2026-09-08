import { randomUUID } from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const DESKTOP_STOP = 'DESKTOP_STOP'
const NORMAL = 'NORMAL'
const DESKTOP_STOP_OWNER = 'hermes-desktop-intentional-stop'
const DESKTOP_STOP_LEASE_MS = 10 * 365 * 24 * 60 * 60 * 1000

interface DesktopStopFenceIdentity extends Record<string, unknown> {
  epoch: number
  nonce: string
  owner: string
  state: string
  timestamp: string
}

function watchdogMaintenancePath(env: NodeJS.ProcessEnv = process.env) {
  const explicit = String(env.HERMES_WATCHDOG_DATA || '').trim()
  const localAppData = String(env.LOCALAPPDATA || '').trim()

  const fallback = localAppData
    ? path.join(localAppData, 'HermesWatchdog')
    : path.join(os.homedir(), '.hermes', 'watchdog-go')

  return path.join(explicit || fallback, 'maintenance.json')
}

function readFence(filePath: string): Record<string, unknown> | null {
  try {
    const value = JSON.parse(fs.readFileSync(filePath, 'utf8'))

    return value && typeof value === 'object' && !Array.isArray(value) ? value : null
  } catch {
    return null
  }
}

function liveFence(fence: Record<string, unknown> | null, now: Date) {
  if (!fence || fence.state === NORMAL) {
    return false
  }

  const expiresAt = Date.parse(String(fence.leaseExpiresAt || ''))

  return Number.isFinite(expiresAt) && expiresAt > now.getTime()
}

function normalizedRoot(value: unknown) {
  try {
    return path.resolve(String(value || '')).toLowerCase()
  } catch {
    return ''
  }
}

function atomicWriteFence(filePath: string, payload: Record<string, unknown>) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  const temporary = path.join(path.dirname(filePath), `.${path.basename(filePath)}.${process.pid}.${randomUUID()}.tmp`)
  const descriptor = fs.openSync(temporary, 'wx', 0o600)

  try {
    fs.writeFileSync(descriptor, `${JSON.stringify(payload, null, 2)}\n`, 'utf8')
    fs.fsyncSync(descriptor)
  } finally {
    fs.closeSync(descriptor)
  }

  try {
    fs.renameSync(temporary, filePath)
  } finally {
    try {
      fs.unlinkSync(temporary)
    } catch {
      void 0
    }
  }
}

function writeDesktopStopFence({
  filePath,
  repoRoot,
  now = new Date()
}: {
  filePath: string
  repoRoot: string
  now?: Date
}) {
  const existing = readFence(filePath)

  if (liveFence(existing, now) && existing?.state !== DESKTOP_STOP) {
    return { written: false, preserved: true }
  }

  const expiresAt = new Date(now.getTime() + DESKTOP_STOP_LEASE_MS)

  const payload: DesktopStopFenceIdentity = {
    schemaVersion: 1,
    state: DESKTOP_STOP,
    owner: DESKTOP_STOP_OWNER,
    nonce: randomUUID().replaceAll('-', ''),
    epoch: now.getTime() * 1_000,
    timestamp: now.toISOString(),
    reason: 'User intentionally closed Hermes Desktop',
    leaseSeconds: Math.floor(DESKTOP_STOP_LEASE_MS / 1000),
    leaseExpiresAt: expiresAt.toISOString(),
    pid: process.pid,
    processStartTime: null,
    repoRoot: path.resolve(repoRoot)
  }

  atomicWriteFence(filePath, payload)

  return { written: true, preserved: false, fence: payload }
}

function processAlive(pid: number) {
  try {
    process.kill(pid, 0)

    return true
  } catch (error) {
    return (error as NodeJS.ErrnoException | null)?.code === 'EPERM'
  }
}

async function waitForDesktopStopFenceAck({
  fence,
  filePath,
  timeoutMs = 35_000,
  pollMs = 200,
  isProcessAlive = processAlive,
  sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms))
}: {
  fence: DesktopStopFenceIdentity
  filePath: string
  timeoutMs?: number
  pollMs?: number
  isProcessAlive?: (pid: number) => boolean
  sleep?: (ms: number) => Promise<void>
}) {
  const lockPath = path.join(path.dirname(filePath), 'watchdog.lock')
  const statePath = path.join(path.dirname(filePath), 'watchdog.state.json')
  const startedAt = Date.now()

  while (Date.now() - startedAt <= timeoutMs) {
    const lock = readFence(lockPath)

    if (!lock) {
      return true
    }

    const watchdogPid = Number(lock.pid)

    if (!Number.isInteger(watchdogPid) || watchdogPid <= 0) {
      return false
    }

    if (!isProcessAlive(watchdogPid)) {
      return true
    }

    const state = readFence(statePath)

    if (
      state?.maintenanceState === fence.state &&
      state.maintenanceOwner === fence.owner &&
      state.maintenanceNonce === fence.nonce &&
      state.maintenanceEpoch === fence.epoch &&
      state.maintenanceTimestamp === fence.timestamp
    ) {
      return true
    }

    await sleep(pollMs)
  }

  return false
}

function clearDesktopStopFence({
  filePath,
  repoRoot,
  now = new Date()
}: {
  filePath: string
  repoRoot: string
  now?: Date
}) {
  const existing = readFence(filePath)

  if (
    existing?.state !== DESKTOP_STOP ||
    existing.owner !== DESKTOP_STOP_OWNER ||
    normalizedRoot(existing.repoRoot) !== normalizedRoot(repoRoot)
  ) {
    return false
  }

  atomicWriteFence(filePath, {
    ...existing,
    state: NORMAL,
    timestamp: now.toISOString(),
    reason: 'User explicitly launched Hermes Desktop',
    leaseExpiresAt: now.toISOString(),
    pid: process.pid
  })

  return true
}

export {
  clearDesktopStopFence,
  DESKTOP_STOP,
  DESKTOP_STOP_OWNER,
  waitForDesktopStopFenceAck,
  watchdogMaintenancePath,
  writeDesktopStopFence
}
