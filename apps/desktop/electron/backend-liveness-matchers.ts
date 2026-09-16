/**
 * backend-liveness-matchers.ts
 *
 * Pure negative liveness gates and identity matchers for backend orphan reaping.
 *
 * Contract:
 * - Dead PID (cheap liveness false): immediately returns false, allowing dead
 *   records (including pid-only records) to be pruned from the ownership ledger
 *   without expensive PowerShell process-start-marker probes.
 * - Live PID: cheap liveness NEVER authorizes destructive action or adoption;
 *   it falls through to exact incarnation start-marker and command verification.
 * - Live pid-only PID: returns undefined (never authorized for destructive stop).
 */

import { processStartMarker as realProcessStartMarker } from './backend-claim'
import { backendCommandMatches, type BackendIdentity, type BackendOwnershipEntry } from './backend-ownership'
import { isPidAliveWindows } from './backend-release-gate'

export interface LivenessMatcherDeps {
  isWindows?: boolean
  isPidAliveWindows?: (pid: number) => boolean
  processStartMarker?: (pid: number) => Promise<string>
  backendCommandForPid?: (pid: number) => Promise<string | null>
}

export function createLivenessMatchers(deps: LivenessMatcherDeps = {}) {
  const isWindows = deps.isWindows ?? process.platform === 'win32'
  const isPidAlive = deps.isPidAliveWindows ?? isPidAliveWindows
  const getMarker = deps.processStartMarker ?? realProcessStartMarker
  const getCommand = deps.backendCommandForPid ?? (async () => null)

  async function processIdentityMatches(identity: BackendIdentity): Promise<boolean | undefined> {
    // 1. CHEAP NEGATIVE GATE: On Windows, check liveness BEFORE the pid-only early return.
    // A dead pid-only record MUST become false so it is removed from the ownership ledger.
    if (isWindows && !isPidAlive(identity.pid)) {
      return false
    }

    // 2. Legacy / degraded PID-only records for LIVE processes are non-authoritative.
    // They must return undefined so they are preserved for manual inspection and NEVER
    // authorize destructive ownership.
    if (String(identity.startMarker || '').startsWith('pid-only:')) {
      return undefined
    }

    // 3. Full identity on live process: verify exact incarnation start marker.
    try {
      return (await getMarker(identity.pid)) === identity.startMarker
    } catch (error: any) {
      return error?.code === 'ENOENT' || error?.code === 'ESRCH' ? false : undefined
    }
  }

  async function backendIdentityMatches(identity: BackendIdentity): Promise<boolean | undefined> {
    const processMatches = await processIdentityMatches(identity)

    if (processMatches !== true) {
      return processMatches
    }

    const command = await getCommand(identity.pid)

    return command === null ? undefined : backendCommandMatches(command)
  }

  async function backendParentMatches(entry: BackendOwnershipEntry): Promise<boolean | undefined> {
    if (
      typeof entry.parentPid !== 'number' ||
      !Number.isInteger(entry.parentPid) ||
      typeof entry.parentStartMarker !== 'string' ||
      !entry.parentStartMarker
    ) {
      return undefined
    }

    const parentPid = entry.parentPid

    // On Windows, if the parent process is already dead, it is definitely not alive.
    // Return false without shelling out to PowerShell.
    if (isWindows && !isPidAlive(parentPid)) {
      return false
    }

    try {
      return (await getMarker(parentPid)) === entry.parentStartMarker
    } catch (error: any) {
      return error?.code === 'ENOENT' || error?.code === 'ESRCH' ? false : undefined
    }
  }

  return {
    processIdentityMatches,
    backendIdentityMatches,
    backendParentMatches
  }
}
