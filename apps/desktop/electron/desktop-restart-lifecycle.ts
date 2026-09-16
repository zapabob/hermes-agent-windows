/**
 * Windows-native Desktop restart / reconnect lifecycle.
 *
 * Critical invariant:
 *   "Desktop connection ownership" !== "backend process ownership".
 *
 * A watchdog-managed (or otherwise external) backend must survive Desktop
 * restart. Desktop may only terminate backends for which it still retains a
 * ChildProcess spawn handle. Manifest PID alone is never authority to kill.
 */

export type DesktopLifecyclePhase =
  | 'STARTING'
  | 'DISCOVER_BACKEND'
  | 'VALIDATE_BACKEND'
  | 'ATTACHING'
  | 'CONNECTED'
  | 'RECONNECTING'
  | 'QUIESCING'
  | 'EXITED'

export type BackendAuthorityKind = 'watchdog-external' | 'desktop-owned' | 'none'

export interface BackendDescriptor {
  baseUrl: string
  port: number
  /** Opaque token fingerprint (length / generation), never the raw secret. */
  tokenPresent: boolean
  tokenLength: number
  pid?: number
  generation: string
  source: 'watchdog' | 'local' | 'remote' | 'unknown'
}

export interface BackendAuthority {
  kind: BackendAuthorityKind
  descriptor: BackendDescriptor | null
  /** True only when this Desktop retained a spawn() ChildProcess handle. */
  hasRetainedChildHandle: boolean
}

export interface DesktopOwnedChild {
  id: string
  kill: (signal?: string) => void
  exited: () => boolean
}

export interface RestartLifecycleDeps {
  discoverBackend: () => Promise<BackendDescriptor | null>
  validateBackend: (descriptor: BackendDescriptor) => Promise<boolean>
  attachBackend: (descriptor: BackendDescriptor) => Promise<void>
  /** Minimal non-destructive RPC after attach (e.g. /api/sessions). */
  probeRpc: (descriptor: BackendDescriptor) => Promise<boolean>
  listDesktopOwnedChildren: () => DesktopOwnedChild[]
  waitForChildExit: (child: DesktopOwnedChild, timeoutMs: number) => Promise<boolean>
  closeDesktopTransports: () => Promise<void> | void
  releaseDesktopConnectionClaim: () => Promise<void> | void
  closeElectronWindows: () => Promise<void> | void
  exitElectronMain: () => Promise<void> | void
  launchReplacementDesktop: () => Promise<void> | void
  acquireSingleInstanceLock: () => boolean
  now?: () => number
  childExitTimeoutMs?: number
}

export interface RestartCycleResult {
  phases: DesktopLifecyclePhase[]
  backendBefore: BackendDescriptor | null
  backendAfter: BackendDescriptor | null
  backendIdentityUnchanged: boolean
  backendCreationCount: number
  oldDesktopExited: boolean
  ownedChildrenExited: boolean
  singleInstanceAcquired: boolean
  rpcOk: boolean
  wroteDesktopStopFence: boolean
  terminatedExternalBackend: boolean
}

export function shouldWriteDesktopStopFence(options: {
  isWindows: boolean
  isQuittingForHandoff: boolean
  systemShutdownInProgress: boolean
  /** True when this quit is followed by app.relaunch() / intentional restart. */
  isQuittingForRestart: boolean
  desktopStopFenceAckDone: boolean
}): boolean {
  if (!options.isWindows) {
    return false
  }

  if (options.isQuittingForHandoff || options.systemShutdownInProgress) {
    return false
  }

  if (options.isQuittingForRestart) {
    // Restart must leave the watchdog-managed backend running and must not
    // park the Go watchdog in a decade-long DESKTOP_STOP lease.
    return false
  }

  return !options.desktopStopFenceAckDone
}

/**
 * Desktop may stop a backend process only when it both claims desktop-owned
 * authority AND still holds the spawn handle. Manifest PID is never enough.
 */
export function mayTerminateBackendProcess(authority: BackendAuthority | null | undefined): boolean {
  if (!authority) {
    return false
  }

  return authority.kind === 'desktop-owned' && authority.hasRetainedChildHandle === true
}

export function authorityFromConnection(
  connection: {
    source?: string | null
    baseUrl?: string | null
    port?: number | null
    token?: string | null
    pid?: number | null
    generation?: string | null
  } | null,
  hasRetainedChildHandle: boolean
): BackendAuthority {
  if (!connection?.baseUrl) {
    return { kind: 'none', descriptor: null, hasRetainedChildHandle: false }
  }

  const token = typeof connection.token === 'string' ? connection.token : ''

  const source =
    connection.source === 'watchdog' || connection.source === 'local' || connection.source === 'remote'
      ? connection.source
      : 'unknown'

  const descriptor: BackendDescriptor = {
    baseUrl: String(connection.baseUrl),
    port: Number(connection.port) || Number(new URL(String(connection.baseUrl)).port) || 0,
    tokenPresent: token.length > 0,
    tokenLength: token.length,
    pid: typeof connection.pid === 'number' ? connection.pid : undefined,
    generation: String(connection.generation || `${connection.baseUrl}|${connection.pid ?? ''}|${token.length}`),
    source
  }

  if (source === 'watchdog' || !hasRetainedChildHandle) {
    return {
      kind: source === 'local' && hasRetainedChildHandle ? 'desktop-owned' : 'watchdog-external',
      descriptor,
      hasRetainedChildHandle: false
    }
  }

  return {
    kind: 'desktop-owned',
    descriptor,
    hasRetainedChildHandle: true
  }
}

export function descriptorsMatchIdentity(a: BackendDescriptor | null, b: BackendDescriptor | null): boolean {
  if (!a || !b) {
    return false
  }

  if (a.baseUrl.replace(/\/+$/, '') !== b.baseUrl.replace(/\/+$/, '')) {
    return false
  }

  if (a.port !== b.port) {
    return false
  }

  if (typeof a.pid === 'number' && typeof b.pid === 'number' && a.pid !== b.pid) {
    return false
  }

  return true
}

/**
 * Pure restart orchestrator used by production wiring and the integration test.
 * Does not import electron — all side effects go through deps.
 */
export async function runDesktopRestartCycle(
  deps: RestartLifecycleDeps,
  options: { backendCreationCount?: { value: number } } = {}
): Promise<RestartCycleResult> {
  const phases: DesktopLifecyclePhase[] = ['CONNECTED']
  const creation = options.backendCreationCount ?? { value: 1 }
  const childExitTimeoutMs = deps.childExitTimeoutMs ?? 5_000

  const backendBefore = await deps.discoverBackend()

  phases.push('QUIESCING')
  await deps.closeDesktopTransports()
  await deps.releaseDesktopConnectionClaim()

  const owned = deps.listDesktopOwnedChildren()

  for (const child of owned) {
    try {
      child.kill('SIGTERM')
    } catch {
      // already gone
    }
  }

  let ownedChildrenExited = true

  for (const child of owned) {
    const ok = await deps.waitForChildExit(child, childExitTimeoutMs)
    ownedChildrenExited = ownedChildrenExited && ok
  }

  await deps.closeElectronWindows()
  await deps.exitElectronMain()
  phases.push('EXITED')

  await deps.launchReplacementDesktop()
  const singleInstanceAcquired = deps.acquireSingleInstanceLock()

  if (!singleInstanceAcquired) {
    return {
      phases,
      backendBefore,
      backendAfter: backendBefore,
      backendIdentityUnchanged: true,
      backendCreationCount: creation.value,
      oldDesktopExited: true,
      ownedChildrenExited,
      singleInstanceAcquired: false,
      rpcOk: false,
      wroteDesktopStopFence: false,
      terminatedExternalBackend: false
    }
  }

  phases.push('STARTING', 'DISCOVER_BACKEND')
  const discovered = await deps.discoverBackend()
  phases.push('VALIDATE_BACKEND')
  const valid = discovered ? await deps.validateBackend(discovered) : false

  if (!discovered || !valid) {
    // Falling through to spawn would create a second backend — forbidden when
    // a healthy external descriptor should have been attachable.
    creation.value += 1

    return {
      phases,
      backendBefore,
      backendAfter: discovered,
      backendIdentityUnchanged: descriptorsMatchIdentity(backendBefore, discovered),
      backendCreationCount: creation.value,
      oldDesktopExited: true,
      ownedChildrenExited,
      singleInstanceAcquired: true,
      rpcOk: false,
      wroteDesktopStopFence: false,
      terminatedExternalBackend: false
    }
  }

  phases.push('ATTACHING')
  await deps.attachBackend(discovered)
  phases.push('CONNECTED')
  const rpcOk = await deps.probeRpc(discovered)

  return {
    phases,
    backendBefore,
    backendAfter: discovered,
    backendIdentityUnchanged: descriptorsMatchIdentity(backendBefore, discovered),
    backendCreationCount: creation.value,
    oldDesktopExited: true,
    ownedChildrenExited,
    singleInstanceAcquired: true,
    rpcOk,
    wroteDesktopStopFence: false,
    terminatedExternalBackend: false
  }
}

/**
 * On transport loss while CONNECTED: re-read the live descriptor, validate,
 * and re-attach. Never reuse a stale cached endpoint blindly.
 */
export async function runTransportReconnect(deps: {
  discoverBackend: () => Promise<BackendDescriptor | null>
  validateBackend: (descriptor: BackendDescriptor) => Promise<boolean>
  attachBackend: (descriptor: BackendDescriptor) => Promise<void>
  cachedDescriptor: BackendDescriptor | null
}): Promise<{ phase: DesktopLifecyclePhase; descriptor: BackendDescriptor | null; usedCache: boolean }> {
  const fresh = await deps.discoverBackend()

  if (!fresh) {
    return { phase: 'RECONNECTING', descriptor: null, usedCache: false }
  }

  if (!(await deps.validateBackend(fresh))) {
    return { phase: 'RECONNECTING', descriptor: fresh, usedCache: false }
  }

  await deps.attachBackend(fresh)

  const usedCache =
    !!deps.cachedDescriptor &&
    deps.cachedDescriptor.baseUrl === fresh.baseUrl &&
    deps.cachedDescriptor.tokenLength === fresh.tokenLength &&
    deps.cachedDescriptor.generation === fresh.generation

  return { phase: 'CONNECTED', descriptor: fresh, usedCache }
}
