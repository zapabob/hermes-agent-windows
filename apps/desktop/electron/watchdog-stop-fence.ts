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

/**
 * Stable Desktop lifecycle identity for DESKTOP_STOP ownership.
 *
 * Must NOT be a mutable checkout / repoRoot (Documents vs %HERMES_HOME%\hermes-agent).
 * HERMES_HOME is shared across those equivalent roots for one Windows deployment.
 */
function resolveDesktopLifecycleId(hermesHome: string): string {
  return path.resolve(String(hermesHome || '')).toLowerCase()
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

function activeHermesRootForHome(hermesHome: string) {
  return path.join(path.resolve(hermesHome), 'hermes-agent')
}

/**
 * Whether a stored fence belongs to this Desktop lifecycle.
 *
 * New fences key on desktopLifecycleId (== resolved HERMES_HOME).
 * Legacy C2 fences keyed only on repoRoot: accept when that path is one of the
 * equivalent roots for the clearer’s hermesHome (active install and/or known
 * checkout spellings). Never “ignore any mismatch”.
 */
function fenceMatchesDesktopLifecycle(
  existing: Record<string, unknown>,
  options: {
    hermesHome: string
    equivalentRoots?: string[]
  }
): boolean {
  const hermesHome = String(options.hermesHome || '').trim()

  if (!hermesHome) {
    return false
  }

  const clearerId = resolveDesktopLifecycleId(hermesHome)
  const storedId = existing.desktopLifecycleId ?? existing.hermesHome

  if (typeof storedId === 'string' && storedId.trim()) {
    return normalizedRoot(storedId) === clearerId
  }

  // Legacy C2: ownership was mutable repoRoot.
  const storedRoot = normalizedRoot(existing.repoRoot)

  if (!storedRoot) {
    return false
  }

  const equivalents = [
    activeHermesRootForHome(hermesHome),
    ...(options.equivalentRoots || []).map(root => path.resolve(String(root || '')))
  ]

  return equivalents.some(root => normalizedRoot(root) === storedRoot)
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
  hermesHome,
  repoRoot,
  now = new Date()
}: {
  filePath: string
  /** Canonical Desktop lifecycle identity (HERMES_HOME). Preferred. */
  hermesHome?: string
  /**
   * Optional checkout path retained as metadata / legacy C2 compatibility.
   * NOT the ownership key when hermesHome is provided.
   */
  repoRoot?: string
  now?: Date
}) {
  const existing = readFence(filePath)

  if (liveFence(existing, now) && existing?.state !== DESKTOP_STOP) {
    return { written: false, preserved: true }
  }

  const resolvedHome = String(hermesHome || '').trim()
  const resolvedRepo = String(repoRoot || '').trim()

  // C2 callers passed only repoRoot. Derive lifecycle id when repoRoot is the
  // active install (.../hermes-agent) by using its parent as HERMES_HOME.
  let lifecycleHome = resolvedHome

  if (!lifecycleHome && resolvedRepo) {
    const base = path.basename(path.resolve(resolvedRepo)).toLowerCase()

    if (base === 'hermes-agent') {
      lifecycleHome = path.dirname(path.resolve(resolvedRepo))
    }
  }

  if (!lifecycleHome && !resolvedRepo) {
    throw new Error('writeDesktopStopFence requires hermesHome (or legacy repoRoot)')
  }

  const expiresAt = new Date(now.getTime() + DESKTOP_STOP_LEASE_MS)
  const desktopLifecycleId = lifecycleHome ? resolveDesktopLifecycleId(lifecycleHome) : undefined

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
    // Ownership key (stable). repoRoot remains informational for operators.
    ...(desktopLifecycleId ? { desktopLifecycleId, hermesHome: path.resolve(lifecycleHome) } : {}),
    ...(resolvedRepo ? { repoRoot: path.resolve(resolvedRepo) } : {})
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
  hermesHome,
  repoRoot,
  equivalentRoots,
  now = new Date()
}: {
  filePath: string
  hermesHome?: string
  /** Legacy C2 clearer path / Documents checkout spelling. */
  repoRoot?: string
  /** Additional checkout paths that belong to the same Desktop lifecycle. */
  equivalentRoots?: string[]
  now?: Date
}) {
  const existing = readFence(filePath)

  if (existing?.state !== DESKTOP_STOP || existing.owner !== DESKTOP_STOP_OWNER) {
    return false
  }

  const resolvedHome = String(hermesHome || '').trim()
  const resolvedRepo = String(repoRoot || '').trim()

  // Derive hermesHome from legacy-only callers that pass the active root.
  let lifecycleHome = resolvedHome

  if (!lifecycleHome && resolvedRepo) {
    const base = path.basename(path.resolve(resolvedRepo)).toLowerCase()

    if (base === 'hermes-agent') {
      lifecycleHome = path.dirname(path.resolve(resolvedRepo))
    }
  }

  if (!lifecycleHome) {
    // Pure repoRoot equality (C2). Documents vs .hermes\hermes-agent fails here
    // by design of the broken identity — callers must pass hermesHome.
    if (!resolvedRepo) {
      return false
    }

    if (normalizedRoot(existing.repoRoot) !== normalizedRoot(resolvedRepo)) {
      return false
    }
  } else {
    const roots = [...(equivalentRoots || [])]

    if (resolvedRepo) {
      roots.push(resolvedRepo)
    }

    if (!fenceMatchesDesktopLifecycle(existing, { hermesHome: lifecycleHome, equivalentRoots: roots })) {
      return false
    }
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
  fenceMatchesDesktopLifecycle,
  resolveDesktopLifecycleId,
  waitForDesktopStopFenceAck,
  watchdogMaintenancePath,
  writeDesktopStopFence
}
