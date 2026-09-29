import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { closeActiveTab } from '@/app/chat/close-tab'
import { commandFocusedPreview } from '@/app/chat/right-rail/preview-nav'
import { openSession } from '@/app/open-session'
import { getApiRequestConnection, getSession } from '@/hermes'
import { resolveDeepLinkAction } from '@/lib/deeplink-routes'
import { hostPathLabel } from '@/lib/external-link'
import { pathFromHermesDeepLink, resolveHermesOpenPath } from '@/lib/hermes-open-target'
import { storedSessionIdForNotification } from '@/lib/session-ids'
import { requestMcpInstallFromDeepLink } from '@/store/mcp-deeplink-install'
import { startMcpHealthChecker, stopMcpHealthChecker } from '@/store/mcp-health'
import {
  clearPluginNotifyHandlers,
  invokePluginNotifyAction,
  invokePluginNotifyActivate,
  respondToApprovalAction
} from '@/store/native-notifications'
import { openPluginInstallRequest } from '@/store/plugin-install-request'
import { openBrowserTab, openPreview } from '@/store/preview'
import { openFolderAsProject } from '@/store/projects'
import {
  $selectedStoredSessionId,
  getRememberedRoute,
  getRememberedSessionId,
  sessionBelongsToProfile,
  sessionMatchesStoredId,
  setRememberedRoute,
  setRememberedSessionId
} from '@/store/session'
import { $sessionTiles, storedSessionIdForRuntimeId } from '@/store/session-states'
import { onSessionsChanged } from '@/store/session-sync'
import { openUpdatesWindow, startUpdatePoller, stopUpdatePoller } from '@/store/updates'
import { isBrowserWindow, isHudWindow, isSecondaryWindow } from '@/store/windows'
import type { SessionInfo } from '@/types/hermes'

import { requestComposerFocus, requestComposerInsert } from '../../chat/composer/focus'
import { appViewForPath, isOverlayView, NEW_CHAT_ROUTE, routeSessionId, sessionRoute } from '../../routes'

type RememberedSession = Pick<
  SessionInfo,
  '_lineage_root_id' | 'connection_id' | 'id' | 'parent_session_id' | 'profile' | 'source'
>
type RememberedAncestor = { id: string; rows: RememberedSession[] }

function rememberedRowHasOwner(row: RememberedSession, profile: string, connectionId: string): boolean {
  const rowConnection = (row.connection_id ?? '').trim()

  return (
    ((row.profile ?? '').trim() || 'default') === (profile.trim() || 'default') &&
    (rowConnection ? rowConnection === connectionId : connectionId === 'local')
  )
}

function isSessionNotFoundError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false
  }

  const statusCode = (error as Error & { statusCode?: unknown }).statusCode

  // Electron's API bridge may preserve the structured field or only the HTTP
  // status prefix in the serialized Error message.
  return statusCode === 404 || /^404(?::|\s|$)/.test(error.message)
}

async function fetchRememberedRow(id: string, profile: string, connectionId: string): Promise<RememberedSession> {
  let row: RememberedSession

  try {
    row = await getSession(id, { connectionId, profile })
  } catch (error) {
    if (error instanceof Error && isSessionNotFoundError(error)) {
      const missingSessionError = Object.assign(new Error(error.message), {
        sessionId: id,
        statusCode: (error as Error & { statusCode?: unknown }).statusCode
      })

      throw missingSessionError
    }

    throw error
  }

  // The explicit request pins the owner even when the backend row lacks a
  // Desktop registry tag. A conflicting returned tag still fails validation.
  return {
    ...row,
    connection_id: row.connection_id?.trim() || connectionId,
    profile: row.profile?.trim() || profile
  }
}

function rememberedCandidateUnchanged(
  start: RememberedSession,
  rows: readonly RememberedSession[],
  profile: string,
  connectionId: string
): boolean {
  const matchingRows = rows.filter(row => sessionMatchesStoredId(row, start.id))

  const foreignProfileRow = matchingRows.some(
    row => ((row.profile ?? '').trim() || 'default') !== (profile.trim() || 'default')
  )

  const currentRows = matchingRows.filter(row => rememberedRowHasOwner(row, profile, connectionId))

  return (
    !foreignProfileRow &&
    (currentRows.length === 0 ||
      currentRows.every(
        current =>
          current.source === start.source &&
          current.parent_session_id === start.parent_session_id &&
          current._lineage_root_id === start._lineage_root_id
      ))
  )
}

function rememberedAncestryUnchanged(
  ancestry: RememberedAncestor,
  rows: readonly RememberedSession[],
  profile: string,
  connectionId: string
): boolean {
  return ancestry.rows.every(row => rememberedCandidateUnchanged(row, rows, profile, connectionId))
}

function ownedRememberedRow(
  rows: readonly RememberedSession[],
  id: string,
  profile: string,
  connectionId: string
): RememberedSession | undefined {
  return rows.find(row => sessionMatchesStoredId(row, id) && rememberedRowHasOwner(row, profile, connectionId))
}

function hasRememberedRowInForeignOwner(
  rows: readonly RememberedSession[],
  id: string,
  profile: string,
  connectionId: string,
  previousConnectionId: null | string
): boolean {
  const expectedProfile = profile.trim() || 'default'
  const expectedConnection = connectionId.trim() || 'local'
  const previousConnection = previousConnectionId?.trim() || null

  return rows.some(row => {
    if (!sessionMatchesStoredId(row, id)) {
      return false
    }

    const rowProfile = (row.profile ?? '').trim() || 'default'

    if (rowProfile !== expectedProfile) {
      return true
    }

    const rowConnection = (row.connection_id ?? '').trim() || 'local'

    return rowConnection !== expectedConnection && (previousConnection === null || rowConnection !== previousConnection)
  })
}

async function userFacingAncestorId(
  start: RememberedSession,
  rows: readonly RememberedSession[],
  profile: string,
  connectionId: string,
  visitedRows?: RememberedSession[]
): Promise<null | RememberedAncestor> {
  const seen = new Set<string>()
  const ancestry: RememberedSession[] = []
  let row = start

  while (true) {
    if (seen.has(row.id) || !rememberedRowHasOwner(row, profile, connectionId)) {
      return null
    }

    seen.add(row.id)
    ancestry.push(row)
    visitedRows?.push(row)

    if (row.source !== 'subagent') {
      return { id: row._lineage_root_id ?? row.id, rows: ancestry }
    }

    const parentId = row.parent_session_id

    if (!parentId) {
      return null
    }

    row =
      ownedRememberedRow(rows, parentId, profile, connectionId) ??
      (await fetchRememberedRow(parentId, profile, connectionId))
  }
}

interface DesktopIntegrationsParams {
  activeConnectionId?: null | string
  activeProfile: string
  chatOpen: boolean
  hasPreview: boolean
  locationPathname: string
  navigate: (to: string, options?: { replace?: boolean }) => void
  profileReady: boolean
  refreshSessions: () => Promise<unknown> | unknown
  resumeExhaustedSessionId: null | string
  routedSessionId: null | string
  runtimeIdByStoredSessionId: { readonly current: Map<string, string> }
  sessions: readonly RememberedSession[]
}

/**
 * All the Electron-main / OS / cross-window integrations the shell listens for:
 * update polling, the ⌘W close shortcut, deep links, native-notification
 * navigation, preview-shortcut enablement, remembered-session restore, and
 * cross-window session-list sync. Kept out of the wiring controller so the
 * "talks to the desktop shell" surface reads as one unit.
 */
export function useDesktopIntegrations({
  activeConnectionId = getApiRequestConnection(),
  activeProfile,
  locationPathname,
  navigate,
  profileReady,
  refreshSessions,
  resumeExhaustedSessionId,
  routedSessionId,
  runtimeIdByStoredSessionId,
  sessions
}: DesktopIntegrationsParams): void {
  const connectionId = activeConnectionId ?? 'local'

  // Update polling — populates $desktopVersion/$updateStatus, which feed the
  // statusbar version pill and the update toasts. Also honors the main
  // process's "open updates" menu request.
  useEffect(() => {
    startUpdatePoller()
    // Background MCP health: HTTP/SSE servers only (never spawns stdio),
    // notifies on transitions into needs-auth/error with a Sign in action.
    startMcpHealthChecker()
    const unsubscribe = window.hermesDesktop?.onOpenUpdatesRequested?.(() => openUpdatesWindow())

    return () => {
      unsubscribe?.()
      stopUpdatePoller()
      stopMcpHealthChecker()
    }
  }, [])

  // The renderer OWNS ⌘W: on macOS the native menu accelerator would else
  // close the window, so claim it unconditionally — the menu then routes ⌘W
  // to us (close-preview-requested IPC) and we decide tab-vs-window.
  useEffect(() => {
    window.hermesDesktop?.setPreviewShortcutActive?.(true)
  }, [])

  const restoredRef = useRef(false)
  const previousConnectionIdRef = useRef<null | string>(null)

  const restoreContextRef = useRef({
    activeConnectionId: connectionId,
    activeProfile,
    locationPathname,
    profileReady,
    routedSessionId,
    sessions
  })

  const restoreEpochRef = useRef(0)
  const pendingRestoreEpochRef = useRef<null | number>(null)
  const [restoreRetryToken, setRestoreRetryToken] = useState(0)

  // A by-id response can settle after a route commit but before passive effects.
  // Publish the committed view first so an old restore cannot reclaim focus.
  useLayoutEffect(() => {
    const prior = restoreContextRef.current

    if (
      prior.activeConnectionId !== connectionId ||
      prior.activeProfile !== activeProfile ||
      prior.locationPathname !== locationPathname ||
      prior.profileReady !== profileReady ||
      prior.routedSessionId !== routedSessionId
    ) {
      restoreEpochRef.current += 1
    }

    if (prior.activeConnectionId !== connectionId) {
      previousConnectionIdRef.current = prior.activeConnectionId
      restoredRef.current = false
      pendingRestoreEpochRef.current = null
    }

    restoreContextRef.current = {
      activeConnectionId: connectionId,
      activeProfile,
      locationPathname,
      profileReady,
      routedSessionId,
      sessions
    }
  })

  useLayoutEffect(
    () => () => {
      restoreEpochRef.current += 1

      if (pendingRestoreEpochRef.current !== null) {
        restoredRef.current = false
        pendingRestoreEpochRef.current = null
      }
    },
    []
  )

  // Wait until boot has adopted the primary profile, then restore that profile's
  // navigation exactly once. The same effect owns subsequent writes so the
  // initial `/` cannot overwrite remembered history before it is read.
  // This ref is a one-time lifecycle latch, not a mirror of reactive atom state.
  // eslint-disable-next-line no-restricted-syntax
  useEffect(() => {
    if (!profileReady || isHudWindow() || isBrowserWindow()) {
      return
    }

    if (!restoredRef.current) {
      // Only cold-start navigation at the default route is replaceable; a deep
      // link or hidden-then-shown window keeps its explicit destination.
      if (locationPathname === NEW_CHAT_ROUTE) {
        const route = getRememberedRoute(activeProfile)
        const routeSession = route ? routeSessionId(route) : null
        const last = getRememberedSessionId(activeProfile)
        const rowFor = (id: string) => ownedRememberedRow(sessions, id, activeProfile, connectionId)
        const routeRow = routeSession ? rowFor(routeSession) : undefined

        const forgetMissingSession = (id: string) => {
          if (getRememberedSessionId(activeProfile) === id) {
            setRememberedSessionId(null, activeProfile)
          }

          if (routeSessionId(getRememberedRoute(activeProfile) ?? '') === id) {
            setRememberedRoute(null, activeProfile)
          }
        }

        const restorableNonSessionRoute =
          !!route && route !== NEW_CHAT_ROUTE && !routeSession && !isOverlayView(appViewForPath(route))

        // Boot adoption can publish renderer.ready before its async session
        // refresh completes. Keep the restore latch open until ownership can be
        // decided; treating an unloaded list as authoritative would erase valid
        // remembered navigation permanently.
        if (sessions.length === 0 && !restorableNonSessionRoute && (routeSession || last)) {
          return
        }

        restoredRef.current = true

        const restoreRememberedCandidate = (
          candidate: Promise<RememberedSession> | RememberedSession,
          onNotFound?: () => void
        ) => {
          const epoch = restoreEpochRef.current
          let retryRestoreOnNextRefresh = false
          let retryWithFreshState = false
          let resolvedCandidate: null | RememberedSession = null
          const visitedRows: RememberedSession[] = []
          pendingRestoreEpochRef.current = epoch

          const restoreStillCurrent = () => {
            const context = restoreContextRef.current

            return (
              restoreEpochRef.current === epoch &&
              context.activeConnectionId === connectionId &&
              context.activeProfile === activeProfile &&
              context.locationPathname === NEW_CHAT_ROUTE &&
              context.profileReady &&
              !context.routedSessionId &&
              (getApiRequestConnection() ?? 'local') === connectionId &&
              getRememberedSessionId(activeProfile) === last &&
              getRememberedRoute(activeProfile) === route
            )
          }

          void Promise.resolve(candidate)
            .then(async row => {
              resolvedCandidate = row

              return {
                row,
                ancestor:
                  row.source === 'subagent'
                    ? await userFacingAncestorId(row, sessions, activeProfile, connectionId, visitedRows)
                    : rememberedRowHasOwner(row, activeProfile, connectionId)
                      ? { id: row._lineage_root_id ?? row.id, rows: [row] }
                      : null
              }
            })
            .then(async ({ row, ancestor }) => {
              const ancestryMatchesCurrentList = () => {
                const currentRows = restoreContextRef.current.sessions

                return (
                  rememberedCandidateUnchanged(row, currentRows, activeProfile, connectionId) &&
                  (!ancestor || rememberedAncestryUnchanged(ancestor, currentRows, activeProfile, connectionId))
                )
              }

              if (!restoreStillCurrent()) {
                return
              }

              if (!ancestryMatchesCurrentList()) {
                retryRestoreOnNextRefresh = true
                retryWithFreshState = true

                return
              }

              // A paged-out delegate can change parent while its old parent's
              // lookup succeeds. Recheck the delegate edges before committing
              // the destination; the list alone cannot prove them unchanged.
              for (const visited of ancestor?.rows ?? []) {
                if (
                  visited.source !== 'subagent' ||
                  ownedRememberedRow(restoreContextRef.current.sessions, visited.id, activeProfile, connectionId)
                ) {
                  continue
                }

                let fresh: RememberedSession
                const rowsBeforeRecheck = restoreContextRef.current.sessions

                try {
                  fresh = await fetchRememberedRow(visited.id, activeProfile, connectionId)
                } catch (error) {
                  if (!restoreStillCurrent()) {
                    return
                  }

                  if (restoreContextRef.current.sessions !== rowsBeforeRecheck || !ancestryMatchesCurrentList()) {
                    retryRestoreOnNextRefresh = true
                    retryWithFreshState = true

                    return
                  }

                  if (onNotFound && isSessionNotFoundError(error)) {
                    onNotFound()
                    retryWithFreshState = true
                  }

                  retryRestoreOnNextRefresh = true

                  return
                }

                if (!restoreStillCurrent()) {
                  return
                }

                if (restoreContextRef.current.sessions !== rowsBeforeRecheck || !ancestryMatchesCurrentList()) {
                  retryRestoreOnNextRefresh = true
                  retryWithFreshState = true

                  return
                }

                if (!rememberedRowHasOwner(fresh, activeProfile, connectionId)) {
                  onNotFound?.()
                  retryRestoreOnNextRefresh = true
                  retryWithFreshState = true

                  return
                }

                if (
                  fresh.source !== visited.source ||
                  fresh.parent_session_id !== visited.parent_session_id ||
                  fresh._lineage_root_id !== visited._lineage_root_id
                ) {
                  retryRestoreOnNextRefresh = true
                  retryWithFreshState = true

                  return
                }
              }

              if (!restoreStillCurrent()) {
                return
              }

              if (!ancestryMatchesCurrentList()) {
                retryRestoreOnNextRefresh = true
                retryWithFreshState = true

                return
              }

              if (!ancestor) {
                if (last === row.id) {
                  setRememberedSessionId(null, activeProfile)
                }

                if (routeSessionId(getRememberedRoute(activeProfile) ?? '') === row.id) {
                  setRememberedRoute(null, activeProfile)
                }

                if (last && last !== row.id) {
                  retryRestoreOnNextRefresh = true
                  retryWithFreshState = true
                }

                return
              }

              setRememberedSessionId(ancestor.id, activeProfile)
              setRememberedRoute(sessionRoute(ancestor.id), activeProfile)
              navigate(sessionRoute(ancestor.id), { replace: true })
            })
            .catch(async error => {
              if (!restoreStillCurrent()) {
                return
              }

              if (onNotFound && isSessionNotFoundError(error)) {
                const context = restoreContextRef.current
                const missingSessionId = (error as Error & { sessionId?: unknown }).sessionId

                const candidateChanged =
                  resolvedCandidate !== null &&
                  !rememberedCandidateUnchanged(resolvedCandidate, context.sessions, activeProfile, connectionId)

                const ancestryChanged = visitedRows.some(
                  row => !rememberedCandidateUnchanged(row, context.sessions, activeProfile, connectionId)
                )

                const missingSessionAppeared =
                  typeof missingSessionId === 'string' &&
                  !!ownedRememberedRow(context.sessions, missingSessionId, activeProfile, connectionId)

                if (candidateChanged || ancestryChanged || missingSessionAppeared) {
                  retryRestoreOnNextRefresh = true
                  retryWithFreshState = true

                  return
                }

                // The list can omit a delegate that was fetched by id. A 404
                // for its old parent is not proof that the delegate is gone.
                // Recheck only the ancestry rows absent from the current list.
                for (const row of visitedRows) {
                  if (ownedRememberedRow(context.sessions, row.id, activeProfile, connectionId)) {
                    continue
                  }

                  let fresh: RememberedSession

                  try {
                    fresh = await fetchRememberedRow(row.id, activeProfile, connectionId)
                  } catch (recheckError) {
                    if (!restoreStillCurrent()) {
                      return
                    }

                    if (!isSessionNotFoundError(recheckError)) {
                      const latestRows = restoreContextRef.current.sessions
                      retryWithFreshState =
                        latestRows !== context.sessions ||
                        visitedRows.some(
                          visited => !rememberedCandidateUnchanged(visited, latestRows, activeProfile, connectionId)
                        ) ||
                        (typeof missingSessionId === 'string' &&
                          !!ownedRememberedRow(latestRows, missingSessionId, activeProfile, connectionId))
                      retryRestoreOnNextRefresh = true

                      return
                    }

                    break
                  }

                  if (!restoreStillCurrent()) {
                    return
                  }

                  if (!rememberedRowHasOwner(fresh, activeProfile, connectionId)) {
                    break
                  }

                  if (
                    fresh.source !== row.source ||
                    fresh.parent_session_id !== row.parent_session_id ||
                    fresh._lineage_root_id !== row._lineage_root_id
                  ) {
                    retryRestoreOnNextRefresh = true
                    retryWithFreshState = true

                    return
                  }
                }

                if (!restoreStillCurrent()) {
                  return
                }

                const latestRows = restoreContextRef.current.sessions

                if (
                  latestRows !== context.sessions ||
                  visitedRows.some(
                    row => !rememberedCandidateUnchanged(row, latestRows, activeProfile, connectionId)
                  ) ||
                  (typeof missingSessionId === 'string' &&
                    !!ownedRememberedRow(latestRows, missingSessionId, activeProfile, connectionId))
                ) {
                  retryRestoreOnNextRefresh = true
                  retryWithFreshState = true

                  return
                }

                onNotFound()
                retryRestoreOnNextRefresh = true
                retryWithFreshState = true

                return
              }

              const currentRows = restoreContextRef.current.sessions
              // A refreshed page may have arrived while this lookup was pending,
              // even when the delegate itself is still outside that page.
              retryWithFreshState =
                currentRows !== sessions ||
                (resolvedCandidate !== null &&
                  !rememberedCandidateUnchanged(resolvedCandidate, currentRows, activeProfile, connectionId)) ||
                visitedRows.some(row => !rememberedCandidateUnchanged(row, currentRows, activeProfile, connectionId))
              retryRestoreOnNextRefresh = true
            })
            .finally(() => {
              if (retryRestoreOnNextRefresh && restoreEpochRef.current === epoch) {
                restoredRef.current = false
                pendingRestoreEpochRef.current = epoch

                if (retryWithFreshState) {
                  setRestoreRetryToken(token => token + 1)
                }
              } else if (pendingRestoreEpochRef.current === epoch) {
                pendingRestoreEpochRef.current = null
              }
            })
        }

        if (routeSession && routeRow?.source === 'subagent') {
          restoreRememberedCandidate(routeRow, () => forgetMissingSession(routeSession))

          return
        }

        // The current list may be only one page. Resolve an unlisted route
        // through the captured profile and connection before declaring it stale.
        if (
          routeSession &&
          !routeRow &&
          !hasRememberedRowInForeignOwner(
            sessions,
            routeSession,
            activeProfile,
            connectionId,
            previousConnectionIdRef.current
          )
        ) {
          restoreRememberedCandidate(fetchRememberedRow(routeSession, activeProfile, connectionId), () =>
            forgetMissingSession(routeSession)
          )

          return
        }

        if (
          route &&
          route !== NEW_CHAT_ROUTE &&
          !isOverlayView(appViewForPath(route)) &&
          (!routeSession ||
            (!!routeRow &&
              routeRow.source !== 'subagent' &&
              sessionBelongsToProfile(sessions, routeSession, activeProfile)))
        ) {
          navigate(route, { replace: true })

          return
        }

        // A remembered route carried a session id we can no longer validate —
        // clear the stale entry so the next cold start won't re-try it.
        if (routeSession) {
          setRememberedRoute(null, activeProfile)
        }

        if (last) {
          const listed = rowFor(last)

          if (listed) {
            if (listed.source === 'subagent') {
              restoreRememberedCandidate(listed, () => forgetMissingSession(last))
            } else {
              navigate(sessionRoute(last), { replace: true })
            }

            return
          }

          if (
            hasRememberedRowInForeignOwner(sessions, last, activeProfile, connectionId, previousConnectionIdRef.current)
          ) {
            setRememberedSessionId(null, activeProfile)

            return
          }

          restoreRememberedCandidate(fetchRememberedRow(last, activeProfile, connectionId), () =>
            forgetMissingSession(last)
          )

          return
        }
      } else {
        restoredRef.current = true
      }
    }

    // Remember the open chat (session id for notifications/resume) AND the last
    // non-overlay route (a page like /skills, or a session route) per profile.
    // Session-shaped routes require an explicit matching owner; unresolved and
    // wrong-profile rows must not replace known-safe navigation.
    if (routedSessionId && sessionBelongsToProfile(sessions, routedSessionId, activeProfile)) {
      const row = ownedRememberedRow(sessions, routedSessionId, activeProfile, connectionId)

      if (row?.source === 'subagent') {
        const epoch = restoreEpochRef.current

        void userFacingAncestorId(row, sessions, activeProfile, connectionId)
          .then(ancestor => {
            const context = restoreContextRef.current

            if (
              restoreEpochRef.current !== epoch ||
              context.activeProfile !== activeProfile ||
              context.locationPathname !== locationPathname ||
              context.routedSessionId !== routedSessionId ||
              (getApiRequestConnection() ?? 'local') !== connectionId ||
              !rememberedCandidateUnchanged(row, context.sessions, activeProfile, connectionId) ||
              (ancestor && !rememberedAncestryUnchanged(ancestor, context.sessions, activeProfile, connectionId))
            ) {
              return
            }

            if (ancestor) {
              setRememberedSessionId(ancestor.id, activeProfile)
              setRememberedRoute(sessionRoute(ancestor.id), activeProfile)
            } else {
              if (getRememberedSessionId(activeProfile) === routedSessionId) {
                setRememberedSessionId(null, activeProfile)
              }

              if (routeSessionId(getRememberedRoute(activeProfile) ?? '') === routedSessionId) {
                setRememberedRoute(null, activeProfile)
              }
            }
          })
          .catch(() => undefined)
      } else if (row) {
        const safeId = row._lineage_root_id ?? routedSessionId
        setRememberedSessionId(safeId, activeProfile)
        setRememberedRoute(safeId === routedSessionId ? locationPathname : sessionRoute(safeId), activeProfile)
      }
    } else if (!routedSessionId && !isOverlayView(appViewForPath(locationPathname))) {
      if (pendingRestoreEpochRef.current !== restoreEpochRef.current) {
        setRememberedRoute(locationPathname, activeProfile)
      }
    }
  }, [
    activeProfile,
    connectionId,
    locationPathname,
    navigate,
    profileReady,
    restoreRetryToken,
    routedSessionId,
    sessions
  ])

  useEffect(() => {
    if (!profileReady || !resumeExhaustedSessionId) {
      return
    }

    if (getRememberedSessionId(activeProfile) === resumeExhaustedSessionId) {
      setRememberedSessionId(null, activeProfile)
    }

    if (routeSessionId(getRememberedRoute(activeProfile) ?? '') === resumeExhaustedSessionId) {
      setRememberedRoute(null, activeProfile)
    }
  }, [activeProfile, profileReady, resumeExhaustedSessionId])

  // Native-notification click -> jump to the session WHERE IT ALREADY IS (open
  // tile / main), else beside what's loaded rather than over it — the click
  // came from outside the app and shouldn't cost the user the chat they left
  // on screen. Runtime id is translated to the stored id the chat route is
  // keyed by; action buttons resolve in place.
  useEffect(() => {
    const unsubscribe = window.hermesDesktop?.onFocusSession?.(sessionId => {
      if (sessionId) {
        // Reloads and runtime recovery can leave only the shared mirror bound.
        const viaLocalMap = storedSessionIdForNotification(sessionId, runtimeIdByStoredSessionId.current)
        const storedId = viaLocalMap !== sessionId ? viaLocalMap : (storedSessionIdForRuntimeId(sessionId) ?? sessionId)

        // A notification reveals a tab; it must not reclassify a Bot chat.
        const scope = $sessionTiles.get().find(tile => tile.storedSessionId === storedId)

        if (isOverlayView(appViewForPath(locationPathname))) {
          navigate(sessionRoute($selectedStoredSessionId.get() ?? ''), { replace: true })
        }

        openSession(
          storedId,
          navigate,
          'stack',
          scope ? { ...scope, workspaceMode: scope.workspaceMode ?? 'sessions' } : undefined
        )
      }
    })

    return () => unsubscribe?.()
  }, [locationPathname, navigate, runtimeIdByStoredSessionId])

  useEffect(() => {
    const unsubscribe = window.hermesDesktop?.onNotificationAction?.(
      ({ actionId, connectionId, profile, requestId, sessionId }) => {
        void respondToApprovalAction(sessionId ?? null, actionId, { connectionId, profile, requestId })
      }
    )

    return () => unsubscribe?.()
  }, [])

  // Plugin OS notification body/action → optional callback + navigate. Activation
  // is user-driven (click), so this is offer-not-hijack. Paths share the
  // hermes://index-network/intent/1 vocabulary with deep links.
  useEffect(() => {
    const unsubscribe = window.hermesDesktop?.onNotificationActivate?.(payload => {
      if (!payload) {
        return
      }

      if (payload.actionId) {
        invokePluginNotifyAction(payload.notifyId, payload.actionId)
      } else {
        invokePluginNotifyActivate(payload.notifyId)
      }

      if (payload.activate) {
        // Defense-in-depth: re-resolve at the IPC boundary rather than trusting
        // the pre-IPC validation — any future hermesDesktop.notify caller gets
        // funneled through the same resolver.
        const path = resolveHermesOpenPath(payload.activate)

        if (path) {
          navigate(path)
        }
      }

      clearPluginNotifyHandlers(payload.notifyId)
    })

    return () => unsubscribe?.()
  }, [navigate])

  // hermes:// deep links:
  //  - mcp/install?… → pending MCP install (explicit confirm, never auto-install)
  //  - plugin/install?… (and legacy plugin-agent/plugin-desktop) → plugin install
  //    modal awaiting explicit confirmation. Never auto-installs.
  //  - blueprint/<name>?… → reviewable /blueprint command in the composer
  //  - open/browser?url=… → in-app Browser tab (Chrome/Edge → Hermes hand-off)
  //  - <plugin>/<path>?… → in-app navigate (e.g. index-network/intent/1)
  //  - open/<path>?… → in-app navigate (generic)
  useEffect(() => {
    const unsubscribe = window.hermesDesktop?.onDeepLink?.(payload => {
      if (!payload?.kind) {
        return
      }

      if (payload.kind === 'mcp' && payload.name === 'install') {
        requestMcpInstallFromDeepLink(payload.params || {})

        return
      }

      const action = resolveDeepLinkAction(payload)

      // Core-owned deep links that were claimed (including hard rejects such as
      // open/browser?url=javascript:…) must not fall through to the generic
      // open/ router — that used to navigate to `/browser`, a non-route.
      if (action.type === 'handled') {
        return
      }

      if (action.type === 'open-browser') {
        if (action.url) {
          openPreview(
            { kind: 'url', label: hostPathLabel(action.url), source: action.url, url: action.url },
            'explicit-link'
          )
        } else {
          openBrowserTab()
        }

        return
      }

      if (action.type === 'composer-blueprint') {
        const slots = Object.entries(action.params || {})
          .map(([k, v]) => {
            const sval = /\s/.test(v) ? `"${v.replace(/"/g, '\\"')}"` : v

            return `${k}=${sval}`
          })
          .join(' ')

        const command = `/blueprint ${action.name}${slots ? ' ' + slots : ''}`
        requestComposerInsert(command, { mode: 'block', target: 'main' })
        requestComposerFocus('main')

        return
      }

      if (action.type === 'plugin-install') {
        openPluginInstallRequest({
          repo: action.repo,
          enable: action.enable,
          force: action.force,
          legacyHint: action.legacyHint
        })

        return
      }

      // Not a core action — treat as a plugin-scoped or open/ navigation deep
      // link (hermes://index-network/intent/1, hermes://open/…). The resolver
      // rejects reserved kinds and unsafe paths.
      const path = pathFromHermesDeepLink(payload.kind, payload.name || '', payload.params || {})

      if (path) {
        navigate(path)
      }
    })

    void window.hermesDesktop?.signalDeepLinkReady?.()

    return () => unsubscribe?.()
  }, [navigate])

  // ⌘W via the macOS menu accelerator → close the focused tab; if nothing is
  // closeable, fall back to closing the window (so ⌘W still works as the
  // OS-standard window close, esp. secondary windows). The Win/Linux keyboard
  // path is the `view.closeTab` keybind (use-keybinds), sharing closeActiveTab.
  useEffect(() => {
    const unsubscribe = window.hermesDesktop?.onClosePreviewRequested?.(
      () => void closeActiveTab(id => navigate(sessionRoute(id)))
    )

    return () => unsubscribe?.()
  }, [navigate])

  // Native browser gestures (⌘R, a mouse's back/forward buttons, a trackpad
  // swipe) that landed on the app's own chrome rather than inside a page — main
  // answers those against the focused guest and never asks. Only ⌘R has an
  // app-level meaning to fall back to; an unfocused swipe is a no-op.
  useEffect(() => {
    const unsubscribe = window.hermesDesktop?.onPreviewNav?.(command => {
      if (!commandFocusedPreview(command) && command === 'reload') {
        window.location.reload()
      }
    })

    return () => unsubscribe?.()
  }, [])

  // File > Open Folder… — same open-folder-as-project upsert as the ⌘O keybind.
  useEffect(() => {
    const unsubscribe = window.hermesDesktop?.onOpenFolderRequested?.(() => void openFolderAsProject())

    return () => unsubscribe?.()
  }, [])

  // Another window mutated the shared session list -> re-pull the sidebar.
  useEffect(() => {
    if (isSecondaryWindow() || isBrowserWindow()) {
      return
    }

    return onSessionsChanged(() => void refreshSessions())
  }, [refreshSessions])
}
