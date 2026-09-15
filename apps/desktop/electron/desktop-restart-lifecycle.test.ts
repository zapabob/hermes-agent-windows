import assert from 'node:assert/strict'
import { describe, test } from 'vitest'

import {
  authorityFromConnection,
  descriptorsMatchIdentity,
  mayTerminateBackendProcess,
  runDesktopRestartCycle,
  runTransportReconnect,
  shouldWriteDesktopStopFence,
  type BackendDescriptor,
  type DesktopOwnedChild
} from './desktop-restart-lifecycle'

/**
 * C2 (951dad8f…) Windows before-quit fence decision, reconstructed from
 * main.ts: write DESKTOP_STOP whenever Windows quit is not handoff/shutdown
 * and the fence has not already been acked — with NO restart exemption.
 */
function c2ShouldWriteDesktopStopFence(options: {
  isWindows: boolean
  isQuittingForHandoff: boolean
  systemShutdownInProgress: boolean
  desktopStopFenceAckDone: boolean
  isQuittingForRestart: boolean
}): boolean {
  void options.isQuittingForRestart

  return (
    options.isWindows &&
    !options.isQuittingForHandoff &&
    !options.systemShutdownInProgress &&
    !options.desktopStopFenceAckDone
  )
}

function fingerprint(token: string) {
  return { tokenPresent: token.length > 0, tokenLength: token.length }
}

describe('Desktop restart/reconnect lifecycle (Windows)', () => {
  test('C2 writes DESKTOP_STOP on relaunch; contract requires restart to skip the fence', () => {
    const relaunch = {
      isWindows: true,
      isQuittingForHandoff: false,
      systemShutdownInProgress: false,
      desktopStopFenceAckDone: false,
      isQuittingForRestart: true
    }

    // Production policy skips the fence on restart.
    assert.equal(shouldWriteDesktopStopFence(relaunch), false)

    // Frozen C2 behaviour: relaunch still wrote DESKTOP_STOP (no restart bit).
    assert.equal(
      c2ShouldWriteDesktopStopFence(relaunch),
      true,
      'C2 before-quit wrote DESKTOP_STOP during Desktop restart'
    )
  })

  test('manifest PID alone never authorizes killing a watchdog-external backend', () => {
    const authority = authorityFromConnection(
      {
        source: 'watchdog',
        baseUrl: 'http://127.0.0.1:9119',
        port: 9119,
        token: 'x'.repeat(43),
        pid: 12692
      },
      false
    )

    assert.equal(authority.kind, 'watchdog-external')
    assert.equal(authority.hasRetainedChildHandle, false)
    assert.equal(mayTerminateBackendProcess(authority), false)
  })

  test('integration: Desktop restart keeps one healthy backend and reconnects via fresh descriptor', async () => {
    const backendPid = 4242
    let backendAlive = true
    let creationCount = 1
    let desktopAAlive = true
    let desktopBAlive = false
    let singleInstanceOwner: 'A' | 'B' | null = 'A'
    let attached: BackendDescriptor | null = null
    let manifestGeneration = 'gen-1'
    let rpcCalls = 0

    const ownedHelpers: DesktopOwnedChild[] = [
      {
        id: 'helper-pty',
        kill() {
          this._dead = true
        },
        exited() {
          return this._dead === true
        },
        _dead: false
      } as DesktopOwnedChild & { _dead: boolean }
    ]

    const liveDescriptor = (): BackendDescriptor => ({
      baseUrl: 'http://127.0.0.1:9119',
      port: 9119,
      pid: backendPid,
      generation: manifestGeneration,
      source: 'watchdog',
      ...fingerprint('session-token-aaaaaaaaaaaaaaaaaaaaaaaaaaaa')
    })

    // A connects
    attached = liveDescriptor()
    assert.ok(attached)
    rpcCalls += 1

    const result = await runDesktopRestartCycle(
      {
        discoverBackend: async () => {
          if (!backendAlive) {
            return null
          }

          // Re-read current descriptor (never return a process-local cache).
          return liveDescriptor()
        },
        validateBackend: async descriptor => backendAlive && descriptor.pid === backendPid,
        attachBackend: async descriptor => {
          if (!desktopBAlive && !desktopAAlive) {
            throw new Error('no Desktop owner to attach')
          }

          attached = descriptor
        },
        probeRpc: async () => {
          rpcCalls += 1

          return backendAlive && !!attached
        },
        listDesktopOwnedChildren: () => (desktopAAlive ? ownedHelpers : []),
        waitForChildExit: async child => {
          const deadline = Date.now() + 50

          while (Date.now() < deadline) {
            if (child.exited()) {
              return true
            }

            await new Promise(resolve => setTimeout(resolve, 5))
          }

          return child.exited()
        },
        closeDesktopTransports: async () => {
          attached = null
        },
        releaseDesktopConnectionClaim: async () => {
          // Connection claim only — backend process ownership untouched.
        },
        closeElectronWindows: async () => undefined,
        exitElectronMain: async () => {
          desktopAAlive = false
          singleInstanceOwner = null
        },
        launchReplacementDesktop: async () => {
          desktopBAlive = true
        },
        acquireSingleInstanceLock: () => {
          if (singleInstanceOwner) {
            return false
          }

          singleInstanceOwner = 'B'

          return true
        }
      },
      { backendCreationCount: { get value() { return creationCount }, set value(v: number) { creationCount = v } } as { value: number } }
    )

    // Simulate the C2 footgun: if restart wrote DESKTOP_STOP, watchdog would
    // stop republishing / Desktop would fail validate. We assert the cycle
    // itself never requests that fence.
    assert.equal(result.wroteDesktopStopFence, false)
    assert.equal(result.terminatedExternalBackend, false)
    assert.equal(backendAlive, true)
    assert.equal(creationCount, 1)
    assert.equal(result.backendCreationCount, 1)
    assert.equal(result.backendIdentityUnchanged, true)
    assert.equal(result.oldDesktopExited, true)
    assert.equal(desktopAAlive, false)
    assert.equal(result.ownedChildrenExited, true)
    assert.ok(ownedHelpers.every(child => child.exited()))
    assert.equal(result.singleInstanceAcquired, true)
    assert.equal(singleInstanceOwner, 'B')
    assert.equal(result.rpcOk, true)
    assert.ok(rpcCalls >= 2)
    assert.ok(descriptorsMatchIdentity(result.backendBefore, result.backendAfter))
    assert.deepEqual(
      result.phases.slice(-5),
      ['STARTING', 'DISCOVER_BACKEND', 'VALIDATE_BACKEND', 'ATTACHING', 'CONNECTED']
    )
  })

  test('transport loss re-reads descriptor instead of trusting stale cache', async () => {
    const stale: BackendDescriptor = {
      baseUrl: 'http://127.0.0.1:9119',
      port: 9119,
      pid: 1,
      generation: 'old',
      source: 'watchdog',
      ...fingerprint('old-token')
    }

    const fresh: BackendDescriptor = {
      baseUrl: 'http://127.0.0.1:9119',
      port: 9119,
      pid: 1,
      generation: 'new',
      source: 'watchdog',
      ...fingerprint('new-token-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb')
    }

    let attached: BackendDescriptor | null = null

    const result = await runTransportReconnect({
      cachedDescriptor: stale,
      discoverBackend: async () => fresh,
      validateBackend: async descriptor => descriptor.generation === 'new',
      attachBackend: async descriptor => {
        attached = descriptor
      }
    })

    assert.equal(result.phase, 'CONNECTED')
    assert.equal(result.usedCache, false)
    assert.equal(attached?.generation, 'new')
    assert.equal(attached?.tokenLength, fresh.tokenLength)
  })
})
