import { act, renderHook, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setApiRequestConnection } from '@/hermes'
import { createClientSessionState } from '@/lib/chat-runtime'
import { requestMcpInstallFromDeepLink } from '@/store/mcp-deeplink-install'
import { openBrowserTab, openPreview } from '@/store/preview'
import type * as PreviewStore from '@/store/preview'
import { _resetLegacyDiscardForTests } from '@/store/session'
import { dropSessionState, publishSessionState } from '@/store/session-states'
import type * as WindowsStore from '@/store/windows'
import type { SessionInfo } from '@/types/hermes'

import { makeSessionInfo } from '../../../test/session-info'
import { sessionRoute } from '../../routes'

import { useDesktopIntegrations } from './use-desktop-integrations'

// Mutable HUD-window flag so the restore tests can flip the window kind the
// hook believes it runs in. Default false keeps the pre-existing restore
// coverage exercising the real main-window path.
const { hudWindowMock } = vi.hoisted(() => ({ hudWindowMock: vi.fn(() => false) }))

// Incomplete local installs of @icons-pack/react-simple-icons can miss
// individual icon modules (e.g. SiIcon.mjs) while still exporting them from
// the package barrel — which aborts this suite before any Browser hand-off
// assertions run. Stub the barrel for unit tests; production bundling is
// unaffected. getOwnPropertyDescriptor lets Vitest resolve arbitrary Si* exports.
vi.mock('@icons-pack/react-simple-icons', () => {
  const icon = () => null
  const target: Record<string, unknown> = { __esModule: true }

  return new Proxy(target, {
    get(t, prop) {
      if (prop === '__esModule') {
        return true
      }

      if (prop === 'then') {
        return undefined
      }

      if (typeof prop === 'string' && prop.endsWith('Hex')) {
        return '#000000'
      }

      if (typeof prop === 'string') {
        if (!(prop in t)) {
          t[prop] = icon
        }

        return t[prop]
      }

      return undefined
    },
    has: () => true,
    getOwnPropertyDescriptor(t, prop) {
      if (typeof prop !== 'string') {
        return undefined
      }

      if (!(prop in t)) {
        t[prop] = prop === '__esModule' ? true : icon
      }

      return { configurable: true, enumerable: true, writable: true, value: t[prop] }
    },
    ownKeys(t) {
      return Reflect.ownKeys(t)
    }
  })
})

vi.mock('@/store/mcp-deeplink-install', () => ({
  requestMcpInstallFromDeepLink: vi.fn()
}))

vi.mock('@/store/preview', async importOriginal => {
  const actual = await importOriginal<typeof PreviewStore>()

  return {
    ...actual,
    openPreview: vi.fn(),
    openBrowserTab: vi.fn()
  }
})

vi.mock('@/store/windows', async importOriginal => {
  const actual = await importOriginal<typeof WindowsStore>()

  return {
    ...actual,
    isHudWindow: () => hudWindowMock()
  }
})

// Pure-jsdom localStorage (no nanostores persistence module needed — the
// production functions write directly to window.localStorage through the
// persistString/storedString helpers in @/lib/storage, which in jsdom resolves
// to the real localStorage global).
// We import the hook and drive it with explicit rx-stores/props to exercise the
// profile-ready gate, ownership validation, and legacy-key discard.

const desktopWindow = window as unknown as { hermesDesktop?: Window['hermesDesktop'] }
const initialHermesDesktop = desktopWindow.hermesDesktop

const session = (over: Partial<SessionInfo> = {}): SessionInfo => makeSessionInfo({ id: 'live', ...over })

describe('useDesktopIntegrations', () => {
  let navigate: ReturnType<typeof vi.fn<(...args: unknown[]) => void>>

  beforeEach(() => {
    window.localStorage.clear()
    _resetLegacyDiscardForTests()
    vi.mocked(requestMcpInstallFromDeepLink).mockClear()
    vi.mocked(openPreview).mockClear()
    vi.mocked(openBrowserTab).mockClear()
    navigate = vi.fn()
    // Every test starts as a main window; only the HUD describe flips this.
    hudWindowMock.mockReturnValue(false)

    // Stub the desktop bridge so the hook's useEffect callbacks don't try to
    // reach real Electron IPC. The established desktop-test pattern assigns a
    // plain object to window.hermesDesktop rather than using vi.spyOn.
    desktopWindow.hermesDesktop = {
      setPreviewShortcutActive: vi.fn(),
      onOpenUpdatesRequested: vi.fn(),
      onFocusSession: vi.fn(),
      onNotificationAction: vi.fn(),
      onNotificationActivate: vi.fn(),
      onDeepLink: vi.fn(),
      signalDeepLinkReady: vi.fn(),
      onClosePreviewRequested: vi.fn(),
      onOpenFolderRequested: vi.fn()
    } as unknown as Window['hermesDesktop']
  })

  afterEach(() => {
    setApiRequestConnection(null)

    if (initialHermesDesktop) {
      desktopWindow.hermesDesktop = initialHermesDesktop
    }

    vi.restoreAllMocks()
  })

  function render({
    activeProfile = 'default',
    locationPathname = '/',
    profileReady = false,
    resumeExhaustedSessionId = null as string | null,
    routedSessionId = null as string | null,
    sessions = [] as readonly SessionInfo[]
  } = {}) {
    return renderHook(
      ({
        activeProfile,
        locationPathname,
        profileReady,
        resumeExhaustedSessionId,
        routedSessionId,
        sessions
      }: {
        activeProfile: string
        locationPathname: string
        profileReady: boolean
        resumeExhaustedSessionId: string | null
        routedSessionId: string | null
        sessions: readonly SessionInfo[]
      }) =>
        useDesktopIntegrations({
          activeProfile,
          chatOpen: false,
          hasPreview: false,
          locationPathname,
          navigate,
          profileReady,
          refreshSessions: vi.fn(),
          resumeExhaustedSessionId,
          routedSessionId,
          runtimeIdByStoredSessionId: { current: new Map() },
          sessions
        }),
      {
        initialProps: {
          activeProfile,
          locationPathname,
          profileReady,
          resumeExhaustedSessionId,
          routedSessionId,
          sessions
        }
      }
    )
  }

  describe('profile-ready gate', () => {
    it('does NOT restore before profileReady is true', () => {
      // Set remembered state, but profileReady=false.
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/remembered-session')
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'remembered-session')

      render({ profileReady: false })

      // no navigation should have occurred
      expect(navigate).not.toHaveBeenCalled()
    })

    it('restores on profileReady when remembered route exists and owns the session', () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/remembered-session')

      const sessions = [session({ id: 'remembered-session', profile: 'default' })]

      render({ profileReady: true, sessions })

      expect(navigate).toHaveBeenCalledWith('/remembered-session', { replace: true })
    })

    it('restores remembered session id when no remembered route exists', () => {
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'remembered-session')

      const sessions = [session({ id: 'remembered-session', profile: 'default' })]

      render({ profileReady: true, sessions })

      // sessionRoute('remembered-session') = '/remembered-session'
      expect(navigate).toHaveBeenCalledWith('/remembered-session', { replace: true })
    })

    it('waits for sessions before validating a remembered session route', () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/remembered-session')

      const result = render({ profileReady: true, sessions: [] })

      expect(navigate).not.toHaveBeenCalled()
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/remembered-session')

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [session({ id: 'remembered-session', profile: 'default' })]
      })

      expect(navigate).toHaveBeenCalledWith('/remembered-session', { replace: true })
    })
  })

  describe('delegate child remembered navigation', () => {
    const child = () =>
      session({
        id: 'delegate-child',
        parent_session_id: 'parent-session',
        profile: 'default',
        source: 'subagent'
      })

    const parent = () => session({ id: 'parent-session', profile: 'default' })

    it('remembers the parent when a routed delegate child appears in a list slice', async () => {
      render({
        locationPathname: '/delegate-child',
        profileReady: true,
        routedSessionId: 'delegate-child',
        sessions: [child(), parent()]
      })

      await waitFor(() =>
        expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('parent-session')
      )
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/parent-session')
    })

    it('repairs a listed delegate child on cold-start restore', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'delegate-child')

      render({ profileReady: true, sessions: [child(), parent()] })

      expect(navigate).not.toHaveBeenCalledWith('/delegate-child', { replace: true })
      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/parent-session', { replace: true }))
    })

    it('does not adopt a foreign-profile child just because its parent is listed locally', () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'delegate-child')

      render({ profileReady: true, sessions: [session({ ...child(), profile: 'other' }), parent()] })

      expect(navigate).not.toHaveBeenCalledWith('/delegate-child', { replace: true })
      expect(navigate).not.toHaveBeenCalledWith('/parent-session', { replace: true })
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBeNull()
    })

    it('does not restore a child row owned by another connection with the same profile', () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'delegate-child')

      render({ profileReady: true, sessions: [session({ ...child(), connection_id: 'remote-other' }), parent()] })

      expect(navigate).not.toHaveBeenCalled()
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBeNull()
    })

    it('resolves a route-only delegate omitted from the current list by its captured owner', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')

      const api = vi.fn(async (request: { connectionId?: string; path?: string; profile?: string }) => {
        expect(request.path).toContain('/api/sessions/delegate-child')
        expect(request.profile).toBe('default')
        expect(request.connectionId).toBe('local')

        return child()
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      render({ profileReady: true, sessions: [parent()] })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/parent-session', { replace: true }))
      expect(api).toHaveBeenCalledTimes(2)
      expect(api.mock.calls[1]?.[0].path).toContain('/api/sessions/delegate-child')
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('parent-session')
    })

    it.each([
      ['profile', { profile: 'other' }],
      ['connection', { connection_id: 'remote-other', profile: 'default' }]
    ] as const)('rejects an unlisted normal route row with a foreign %s owner', async (_owner, owner) => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/normal-session')

      const api = vi.fn(async (request: { connectionId?: string; path?: string; profile?: string }) => {
        expect(request.path).toContain('/api/sessions/normal-session')
        expect(request.profile).toBe('default')
        expect(request.connectionId).toBe('local')

        return session({ id: 'normal-session', source: 'tui', ...owner })
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      render({ profileReady: true, sessions: [session({ id: 'another-session', profile: 'default' })] })

      await waitFor(() => expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBeNull())
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBeNull()
      expect(navigate).not.toHaveBeenCalled()
      expect(api).toHaveBeenCalledTimes(1)
    })

    it('restores an unlisted compressed normal session by its lineage root', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/tip-2')

      const api = vi.fn(async (request: { connectionId?: string; path?: string; profile?: string }) => {
        expect(request.path).toContain('/api/sessions/tip-2')
        expect(request.profile).toBe('default')
        expect(request.connectionId).toBe('local')

        return session({
          id: 'tip-2',
          profile: 'default',
          source: 'tui',
          _lineage_root_id: 'root-session'
        })
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      render({ profileReady: true, sessions: [session({ id: 'another-session', profile: 'default' })] })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/root-session', { replace: true }))
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('root-session')
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/root-session')
      expect(api).toHaveBeenCalledTimes(1)
    })

    it('discards an unlisted route lookup after a foreign-profile row appears', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')
      let completeLookup: ((row: SessionInfo) => void) | undefined

      const api = vi.fn(
        () =>
          new Promise<SessionInfo>(resolve => {
            completeLookup = resolve
          })
      )

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({ profileReady: true, sessions: [session({ id: 'another-session', profile: 'default' })] })

      await waitFor(() => expect(api).toHaveBeenCalledTimes(1))

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [session({ ...child(), profile: 'other' })]
      })

      await act(async () => {
        completeLookup?.(session({ ...child(), source: 'tui' }))
      })

      expect(navigate).not.toHaveBeenCalled()
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBeNull()
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBeNull()
    })

    it('resolves an unlisted delegate by id on the captured profile and connection', async () => {
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'delegate-child')

      const api = vi.fn(async (request: { connectionId?: string; path?: string; profile?: string }) => {
        expect(request.path).toContain('/api/sessions/delegate-child')
        expect(request.profile).toBe('default')
        expect(request.connectionId).toBe('local')

        return child()
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      render({ profileReady: true, sessions: [parent()] })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/parent-session', { replace: true }))
      expect(api).toHaveBeenCalledTimes(2)
      expect(api.mock.calls[1]?.[0].path).toContain('/api/sessions/delegate-child')
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('parent-session')
    })

    it('fetches a delegate parent outside the current list slice with the captured owner', async () => {
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'delegate-child')

      const api = vi.fn(async (request: { connectionId?: string; path?: string; profile?: string }) => {
        expect(request.profile).toBe('default')
        expect(request.connectionId).toBe('local')

        if (request.path?.includes('/api/sessions/delegate-child')) {
          return child()
        }

        expect(request.path).toContain('/api/sessions/parent-session')

        return parent()
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      render({ profileReady: true, sessions: [session({ id: 'another-session', profile: 'default' })] })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/parent-session', { replace: true }))
      expect(api).toHaveBeenCalledTimes(3)
      expect(api.mock.calls[2]?.[0].path).toContain('/api/sessions/delegate-child')
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('parent-session')
    })

    it('restarts remembered restore for a new connection after discarding a stale response', async () => {
      setApiRequestConnection('remote-A')
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'remembered-session')

      let completeRead: ((row: SessionInfo) => void) | undefined

      const api = vi.fn(
        () =>
          new Promise<SessionInfo>(resolve => {
            completeRead = resolve
          })
      )

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({
        profileReady: true,
        sessions: [session({ id: 'other-session', profile: 'default', connection_id: 'remote-A' })]
      })

      await waitFor(() => expect(api).toHaveBeenCalledTimes(1))

      setApiRequestConnection('remote-B')
      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [session({ id: 'remembered-session', profile: 'default', connection_id: 'remote-B' })]
      })

      await act(async () => {
        completeRead?.(session({ id: 'remembered-session', profile: 'default', connection_id: 'remote-A' }))
      })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/remembered-session', { replace: true }))
    })

    it('resolves the remembered id against the new connection while the old connection list is still visible', async () => {
      setApiRequestConnection('remote-A')
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'remembered-session')

      let completeOldConnectionRead: ((row: SessionInfo) => void) | undefined

      const api = vi.fn((request: { connectionId?: string }) => {
        if (request.connectionId === 'remote-A') {
          return new Promise<SessionInfo>(resolve => {
            completeOldConnectionRead = resolve
          })
        }

        return Promise.resolve(session({ id: 'remembered-session', profile: 'default', connection_id: 'remote-B' }))
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({
        profileReady: true,
        sessions: [session({ id: 'other-session', profile: 'default', connection_id: 'remote-A' })]
      })

      await waitFor(() => expect(api).toHaveBeenCalledTimes(1))

      setApiRequestConnection('remote-B')
      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [session({ id: 'remembered-session', profile: 'default', connection_id: 'remote-A' })]
      })

      await waitFor(() => expect(api).toHaveBeenCalledTimes(2))
      expect(api.mock.calls[1]?.[0].connectionId).toBe('remote-B')

      await act(async () => {
        completeOldConnectionRead?.(
          session({ id: 'remembered-session', profile: 'default', connection_id: 'remote-A' })
        )
      })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/remembered-session', { replace: true }))
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('remembered-session')
    })

    it('does not adopt an untagged local parent row for a remote delegate', async () => {
      setApiRequestConnection('remote-A')
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'delegate-child')

      const api = vi.fn(async (request: { connectionId?: string; path?: string; profile?: string }) => {
        expect(request.connectionId).toBe('remote-A')
        expect(request.profile).toBe('default')
        expect(request.path).toContain('/api/sessions/parent-session')

        return session({ ...parent(), _lineage_root_id: 'remote-root', connection_id: undefined })
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      render({
        profileReady: true,
        sessions: [
          session({ ...child(), connection_id: 'remote-A' }),
          session({ ...parent(), _lineage_root_id: 'local-root', connection_id: undefined })
        ]
      })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/remote-root', { replace: true }))
      expect(navigate).not.toHaveBeenCalledWith('/local-root', { replace: true })
      expect(api).toHaveBeenCalledTimes(1)
    })

    it('finishes an off-list parent lookup when the same child route receives a refreshed list', async () => {
      let completeParent: ((row: SessionInfo) => void) | undefined

      const api = vi.fn(
        () =>
          new Promise<SessionInfo>(resolve => {
            completeParent ??= resolve
          })
      )

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({
        locationPathname: '/delegate-child',
        profileReady: true,
        routedSessionId: 'delegate-child',
        sessions: [child()]
      })

      await waitFor(() => expect(api).toHaveBeenCalledTimes(1))

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/delegate-child',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: 'delegate-child',
        sessions: [child()]
      })

      await act(async () => {
        completeParent?.(parent())
      })

      await waitFor(() =>
        expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('parent-session')
      )
    })

    it('discards an old parent lookup when the same route becomes a normal session', async () => {
      let completeParent: ((row: SessionInfo) => void) | undefined

      const api = vi.fn(
        () =>
          new Promise<SessionInfo>(resolve => {
            completeParent = resolve
          })
      )

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({
        locationPathname: '/delegate-child',
        profileReady: true,
        routedSessionId: 'delegate-child',
        sessions: [child()]
      })

      await waitFor(() => expect(api).toHaveBeenCalledTimes(1))

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/delegate-child',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: 'delegate-child',
        sessions: [session({ ...child(), source: 'tui' })]
      })

      await act(async () => {
        completeParent?.(parent())
      })

      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('delegate-child')
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/delegate-child')
    })

    it('discards an old grandparent lookup after the intermediate delegate becomes normal', async () => {
      let completeGrandparent: ((row: SessionInfo) => void) | undefined

      const api = vi.fn(
        () =>
          new Promise<SessionInfo>(resolve => {
            completeGrandparent ??= resolve
          })
      )

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const outer = session({
        id: 'outer-child',
        parent_session_id: 'parent-session',
        profile: 'default',
        source: 'subagent'
      })

      const inner = session({ ...child(), parent_session_id: 'outer-child' })

      const result = render({
        locationPathname: '/delegate-child',
        profileReady: true,
        routedSessionId: 'delegate-child',
        sessions: [inner, outer]
      })

      await waitFor(() => expect(api).toHaveBeenCalledTimes(1))

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/delegate-child',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: 'delegate-child',
        sessions: [inner, session({ ...outer, source: 'tui' })]
      })

      await waitFor(() =>
        expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('outer-child')
      )

      await act(async () => {
        completeGrandparent?.(parent())
      })

      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('outer-child')
    })

    it('restores a listed delegate parent when StrictMode replays mount effects', async () => {
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'delegate-child')

      renderHook(
        () =>
          useDesktopIntegrations({
            activeProfile: 'default',
            chatOpen: false,
            hasPreview: false,
            locationPathname: '/',
            navigate,
            profileReady: true,
            refreshSessions: vi.fn(),
            resumeExhaustedSessionId: null,
            routedSessionId: null,
            runtimeIdByStoredSessionId: { current: new Map() },
            sessions: [child(), parent()]
          }),
        { wrapper: StrictMode }
      )

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/parent-session', { replace: true }))
    })

    it('restores a delegate route without a last ID when StrictMode replays mount effects', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')

      renderHook(
        () =>
          useDesktopIntegrations({
            activeProfile: 'default',
            chatOpen: false,
            hasPreview: false,
            locationPathname: '/',
            navigate,
            profileReady: true,
            refreshSessions: vi.fn(),
            resumeExhaustedSessionId: null,
            routedSessionId: null,
            runtimeIdByStoredSessionId: { current: new Map() },
            sessions: [child(), parent()]
          }),
        { wrapper: StrictMode }
      )

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/parent-session', { replace: true }))
    })

    it('keeps a remembered child when only its parent lookup fails transiently', async () => {
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'delegate-child')

      const api = vi.fn(async () => {
        throw new Error('temporary parent read failure')
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      render({ profileReady: true, sessions: [child()] })

      await waitFor(() => expect(api).toHaveBeenCalledTimes(1))
      await act(async () => undefined)
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('delegate-child')
      expect(navigate).not.toHaveBeenCalled()
    })

    it('keeps a route-only delegate target when a list refresh precedes a transient parent failure', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')
      const failParent: Array<(error: Error) => void> = []

      const api = vi.fn(
        () =>
          new Promise<SessionInfo>((_resolve, reject) => {
            failParent.push(reject)
          })
      )

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({ profileReady: true, sessions: [child()] })

      await waitFor(() => expect(api).toHaveBeenCalledTimes(1))

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [child()]
      })

      await act(async () => {
        failParent[0]?.(new Error('temporary parent read failure'))
      })

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [child()]
      })

      await waitFor(() => expect(api).toHaveBeenCalledTimes(2))

      await act(async () => {
        failParent[1]?.(new Error('temporary parent read failure'))
      })

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [child()]
      })

      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/delegate-child')
      expect(navigate).not.toHaveBeenCalled()
    })

    it('retries changed delegate ancestry after a transient old-parent failure without another list refresh', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')
      let failOldParent: ((error: Error) => void) | undefined

      const api = vi.fn(({ path }: { path?: string }) => {
        expect(path).toContain('/api/sessions/old-parent')

        return new Promise<SessionInfo>((_resolve, reject) => {
          failOldParent = reject
        })
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({
        profileReady: true,
        sessions: [session({ ...child(), parent_session_id: 'old-parent' })]
      })

      await waitFor(() => expect(api).toHaveBeenCalledTimes(1))

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [session({ ...child(), parent_session_id: 'new-parent' }), session({ id: 'new-parent' })]
      })

      await act(async () => {
        failOldParent?.(new Error('temporary parent read failure'))
      })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/new-parent', { replace: true }))
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/new-parent')
    })

    it('retries an unlisted delegate after a list refresh and transient old-parent failure', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')
      let failOldParent: ((error: Error) => void) | undefined
      let childLookups = 0

      const api = vi.fn(({ path }: { path?: string }) => {
        if (path?.includes('/api/sessions/delegate-child')) {
          childLookups += 1

          return Promise.resolve(
            session({ ...child(), parent_session_id: childLookups === 1 ? 'old-parent' : 'new-parent' })
          )
        }

        if (path?.includes('/api/sessions/old-parent')) {
          return new Promise<SessionInfo>((_resolve, reject) => {
            failOldParent = reject
          })
        }

        throw new Error(`unexpected session lookup: ${path}`)
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({ profileReady: true, sessions: [session({ id: 'unrelated' })] })

      await waitFor(() => expect(failOldParent).toBeDefined())

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [session({ id: 'unrelated' }), session({ id: 'new-parent' })]
      })

      await act(async () => {
        failOldParent?.(new Error('temporary parent read failure'))
      })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/new-parent', { replace: true }))
      expect(childLookups).toBeGreaterThanOrEqual(2)
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/new-parent')
    })

    it('keeps an unlisted route-only target and retries after a transient lookup failure', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')
      const failLookup: Array<(error: Error) => void> = []

      const api = vi.fn(
        () =>
          new Promise<SessionInfo>((_resolve, reject) => {
            failLookup.push(reject)
          })
      )

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({ profileReady: true, sessions: [session({ id: 'another-session', profile: 'default' })] })

      await waitFor(() => expect(api).toHaveBeenCalledTimes(1))

      await act(async () => {
        failLookup[0]?.(new Error('temporary session read failure'))
      })

      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/delegate-child')

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [
          session({ id: 'another-session', profile: 'default' }),
          session({ id: 'new-session', profile: 'default' })
        ]
      })

      await waitFor(() => expect(api).toHaveBeenCalledTimes(2))
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/delegate-child')
      expect(navigate).not.toHaveBeenCalled()
    })

    it('falls back to the valid last session when an unlisted remembered route returns 404', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/deleted-session')
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'valid-session')

      const api = vi.fn(async ({ path }: { path?: string }) => {
        if (path?.includes('/api/sessions/deleted-session')) {
          throw Object.assign(new Error('404: session not found'), { statusCode: 404 })
        }

        if (path?.includes('/api/sessions/valid-session')) {
          return session({ id: 'valid-session', profile: 'default' })
        }

        throw new Error(`unexpected session lookup: ${path}`)
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      render({ profileReady: true, sessions: [session({ id: 'another-session', profile: 'default' })] })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/valid-session', { replace: true }))
      expect(navigate).not.toHaveBeenCalledWith('/deleted-session', { replace: true })
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('valid-session')
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/valid-session')
      expect(api).toHaveBeenCalledTimes(2)
    })

    it('falls back to the valid last session when a listed delegate has a missing parent', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'valid-session')

      const api = vi.fn(async ({ path }: { path?: string }) => {
        expect(path).toContain('/api/sessions/parent-session')
        throw Object.assign(new Error('404: session not found'), { statusCode: 404 })
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      render({
        profileReady: true,
        sessions: [child(), session({ id: 'valid-session', profile: 'default' })]
      })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/valid-session', { replace: true }))
      expect(navigate).not.toHaveBeenCalledWith('/delegate-child', { replace: true })
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBeNull()
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('valid-session')
      expect(api).toHaveBeenCalledTimes(1)
    })

    it('retries the current delegate ancestry when the old parent lookup returns 404', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')
      let failOldParent: ((error: Error) => void) | undefined

      const api = vi.fn((request: { path?: string }) => {
        expect(request.path).toContain('/api/sessions/old-parent')

        return new Promise<SessionInfo>((_resolve, reject) => {
          failOldParent = reject
        })
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({
        profileReady: true,
        sessions: [session({ ...child(), parent_session_id: 'old-parent' })]
      })

      await waitFor(() => expect(api).toHaveBeenCalledTimes(1))

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [
          session({ ...child(), parent_session_id: 'new-parent' }),
          session({ id: 'new-parent', profile: 'default' })
        ]
      })

      await act(async () => {
        failOldParent?.(Object.assign(new Error('404: session not found'), { statusCode: 404 }))
      })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/new-parent', { replace: true }))
      expect(navigate).not.toHaveBeenCalledWith('/delegate-child', { replace: true })
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/new-parent')
    })

    it('forgets a listed last-session delegate whose parent is gone', async () => {
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'delegate-child')

      const api = vi.fn(async ({ path }: { path?: string }) => {
        if (path?.includes('/api/sessions/parent-session')) {
          throw Object.assign(new Error('404: session not found'), { statusCode: 404 })
        }

        if (path?.includes('/api/sessions/delegate-child')) {
          return child()
        }

        throw new Error(`unexpected session lookup: ${path}`)
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({ profileReady: true, sessions: [child()] })

      await waitFor(() =>
        expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBeNull()
      )
      const completedLookups = api.mock.calls.length

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [child()]
      })

      expect(api).toHaveBeenCalled()
      expect(api).toHaveBeenCalledTimes(completedLookups)
      expect(navigate).not.toHaveBeenCalledWith('/delegate-child', { replace: true })
    })

    it('retries nested delegate ancestry when an intermediate delegate changes parent before the old parent 404', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/inner-child')
      let failOldParent: ((error: Error) => void) | undefined

      const api = vi.fn(({ path }: { path?: string }) => {
        expect(path).toContain('/api/sessions/old-parent')

        return new Promise<SessionInfo>((_resolve, reject) => {
          failOldParent = reject
        })
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const inner = session({ ...child(), id: 'inner-child', parent_session_id: 'outer-child' })
      const outer = session({ ...child(), id: 'outer-child', parent_session_id: 'old-parent' })
      const result = render({ profileReady: true, sessions: [inner, outer] })

      await waitFor(() => expect(api).toHaveBeenCalledTimes(1))

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [inner, session({ ...outer, parent_session_id: 'new-parent' }), session({ id: 'new-parent' })]
      })

      await act(async () => {
        failOldParent?.(Object.assign(new Error('404: session not found'), { statusCode: 404 }))
      })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/new-parent', { replace: true }))
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/new-parent')
    })

    it('rechecks an unlisted delegate by id when its old parent disappears after a list refresh', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')
      let failOldParent: ((error: Error) => void) | undefined
      let childLookups = 0

      const api = vi.fn(({ path }: { path?: string }) => {
        if (path?.includes('/api/sessions/delegate-child')) {
          childLookups += 1

          return Promise.resolve(
            session({ ...child(), parent_session_id: childLookups === 1 ? 'old-parent' : 'new-parent' })
          )
        }

        if (path?.includes('/api/sessions/old-parent')) {
          return new Promise<SessionInfo>((_resolve, reject) => {
            failOldParent = reject
          })
        }

        throw new Error(`unexpected session lookup: ${path}`)
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({ profileReady: true, sessions: [session({ id: 'unrelated' })] })

      await waitFor(() => expect(failOldParent).toBeDefined())

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [session({ id: 'unrelated' }), session({ id: 'new-parent' })]
      })

      await act(async () => {
        failOldParent?.(Object.assign(new Error('404: session not found'), { statusCode: 404 }))
      })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/new-parent', { replace: true }))
      expect(childLookups).toBeGreaterThanOrEqual(2)
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/new-parent')
    })

    it('keeps a changed route when the list refreshes during a 404 recheck', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')
      let completeRecheck: ((row: SessionInfo) => void) | undefined
      let childLookups = 0

      const oldChild = session({ ...child(), parent_session_id: 'old-parent' })

      const api = vi.fn(({ path }: { path?: string }) => {
        if (path?.includes('/api/sessions/delegate-child')) {
          childLookups += 1

          return childLookups === 1
            ? Promise.resolve(oldChild)
            : new Promise<SessionInfo>(resolve => {
                completeRecheck = resolve
              })
        }

        if (path?.includes('/api/sessions/old-parent')) {
          return Promise.reject(Object.assign(new Error('404: session not found'), { statusCode: 404 }))
        }

        throw new Error(`unexpected session lookup: ${path}`)
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({ profileReady: true, sessions: [session({ id: 'unrelated' })] })

      await waitFor(() => expect(completeRecheck).toBeDefined())

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [session({ ...child(), parent_session_id: 'new-parent' }), session({ id: 'new-parent' })]
      })

      await act(async () => {
        completeRecheck?.(oldChild)
      })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/new-parent', { replace: true }))
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/new-parent')
    })

    it('retries a changed route when a 404 parent recheck has a transient failure after a list refresh', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')
      let failRecheck: ((error: Error) => void) | undefined
      let childLookups = 0
      const oldChild = session({ ...child(), parent_session_id: 'old-parent' })

      const api = vi.fn(({ path }: { path?: string }) => {
        if (path?.includes('/api/sessions/delegate-child')) {
          childLookups += 1

          return childLookups === 1
            ? Promise.resolve(oldChild)
            : new Promise<SessionInfo>((_resolve, reject) => {
                failRecheck = reject
              })
        }

        if (path?.includes('/api/sessions/old-parent')) {
          return Promise.reject(Object.assign(new Error('404: session not found'), { statusCode: 404 }))
        }

        throw new Error(`unexpected session lookup: ${path}`)
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']
      const result = render({ profileReady: true, sessions: [session({ id: 'unrelated' })] })

      await waitFor(() => expect(failRecheck).toBeDefined())
      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [session({ ...child(), parent_session_id: 'new-parent' }), session({ id: 'new-parent' })]
      })
      await act(async () => {
        failRecheck?.(new Error('temporary lookup failure'))
      })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/new-parent', { replace: true }))
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/new-parent')
    })

    it('keeps a changed route when a successful parent lookup has a 404 recheck after a list refresh', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')
      let failRecheck: ((error: Error) => void) | undefined
      let childLookups = 0

      const oldChild = session({ ...child(), parent_session_id: 'old-parent' })

      const api = vi.fn(({ path }: { path?: string }) => {
        if (path?.includes('/api/sessions/delegate-child')) {
          childLookups += 1

          return childLookups === 1
            ? Promise.resolve(oldChild)
            : new Promise<SessionInfo>((_resolve, reject) => {
                failRecheck = reject
              })
        }

        if (path?.includes('/api/sessions/old-parent')) {
          return Promise.resolve(session({ id: 'old-parent' }))
        }

        throw new Error(`unexpected session lookup: ${path}`)
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({ profileReady: true, sessions: [session({ id: 'unrelated' })] })

      await waitFor(() => expect(failRecheck).toBeDefined())

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [session({ ...child(), parent_session_id: 'new-parent' }), session({ id: 'new-parent' })]
      })

      await act(async () => {
        failRecheck?.(Object.assign(new Error('404: session not found'), { statusCode: 404 }))
      })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/new-parent', { replace: true }))
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/new-parent')
    })

    it('rechecks an unlisted delegate before restoring an old parent whose lookup succeeds', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')
      let completeOldParent: ((row: SessionInfo) => void) | undefined
      let childLookups = 0

      const api = vi.fn(({ path }: { path?: string }) => {
        if (path?.includes('/api/sessions/delegate-child')) {
          childLookups += 1

          return Promise.resolve(
            session({ ...child(), parent_session_id: childLookups === 1 ? 'old-parent' : 'new-parent' })
          )
        }

        if (path?.includes('/api/sessions/old-parent')) {
          return new Promise<SessionInfo>(resolve => {
            completeOldParent = resolve
          })
        }

        throw new Error(`unexpected session lookup: ${path}`)
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({ profileReady: true, sessions: [session({ id: 'unrelated' })] })

      await waitFor(() => expect(completeOldParent).toBeDefined())

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [session({ id: 'unrelated' }), session({ id: 'new-parent' })]
      })

      await act(async () => {
        completeOldParent?.(session({ id: 'old-parent' }))
      })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/new-parent', { replace: true }))
      expect(navigate).not.toHaveBeenCalledWith('/old-parent', { replace: true })
      expect(childLookups).toBeGreaterThanOrEqual(2)
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/new-parent')
    })

    it('preserves a valid last session when a remembered delegate has no parent', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/orphan-child')
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'valid-session')

      render({
        profileReady: true,
        sessions: [
          session({ id: 'orphan-child', profile: 'default', source: 'subagent', parent_session_id: '' }),
          session({ id: 'valid-session', profile: 'default' })
        ]
      })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/valid-session', { replace: true }))
      expect(navigate).not.toHaveBeenCalledWith('/orphan-child', { replace: true })
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('valid-session')
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBeNull()
    })

    it('discards a late parent lookup after the user opens another page', async () => {
      let completeParent: ((row: SessionInfo) => void) | undefined

      const api = vi.fn(
        () =>
          new Promise<SessionInfo>(resolve => {
            completeParent = resolve
          })
      )

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({
        locationPathname: '/delegate-child',
        profileReady: true,
        routedSessionId: 'delegate-child',
        sessions: [child()]
      })

      await waitFor(() => expect(api).toHaveBeenCalledTimes(1))

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/skills',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [child()]
      })

      await act(async () => {
        completeParent?.(parent())
      })

      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBeNull()
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/skills')
    })

    it('restarts route-only restore when the delegate ancestry changes during lookup', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')
      let completeOldParent: ((row: SessionInfo) => void) | undefined

      const api = vi.fn(
        () =>
          new Promise<SessionInfo>(resolve => {
            completeOldParent = resolve
          })
      )

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({ profileReady: true, sessions: [child()] })

      await waitFor(() => expect(api).toHaveBeenCalledTimes(1))

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [
          session({ ...child(), parent_session_id: 'new-parent' }),
          session({ id: 'new-parent', profile: 'default' })
        ]
      })

      await act(async () => {
        completeOldParent?.(parent())
      })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/new-parent', { replace: true }))
      expect(navigate).not.toHaveBeenCalledWith('/parent-session', { replace: true })
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('new-parent')
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/new-parent')
    })

    it('walks through nested delegate sessions to the first user-facing ancestor', async () => {
      const outer = session({
        id: 'outer-child',
        parent_session_id: 'parent-session',
        profile: 'default',
        source: 'subagent'
      })

      const inner = session({ ...child(), parent_session_id: 'outer-child' })
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'delegate-child')

      render({ profileReady: true, sessions: [inner, outer, parent()] })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/parent-session', { replace: true }))
      expect(navigate).not.toHaveBeenCalledWith('/outer-child', { replace: true })
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('parent-session')
    })

    it('restores a delegate child through its compressed parent lineage root', async () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/delegate-child')

      const compressedParent = session({ id: 'parent-tip', _lineage_root_id: 'root-session', profile: 'default' })

      const nestedChild = session({
        id: 'delegate-child',
        parent_session_id: 'parent-tip',
        profile: 'default',
        source: 'subagent'
      })

      render({ profileReady: true, sessions: [nestedChild, compressedParent] })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/root-session', { replace: true }))
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('root-session')
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/root-session')
    })

    it('walks a deep valid delegate lineage without clearing its remembered route', async () => {
      const delegateRows = Array.from({ length: 18 }, (_, index) =>
        session({
          id: `delegate-${index}`,
          parent_session_id: index === 17 ? 'parent-session' : `delegate-${index + 1}`,
          profile: 'default',
          source: 'subagent'
        })
      )

      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'delegate-0')

      render({ profileReady: true, sessions: [...delegateRows, parent()] })

      await waitFor(() => expect(navigate).toHaveBeenCalledWith('/parent-session', { replace: true }))
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('parent-session')
    })

    it('keeps the root id after compression while restoring a normal chat', () => {
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'root-session')
      const tip = session({ id: 'tip-2', _lineage_root_id: 'root-session', profile: 'default' })

      render({ profileReady: true, sessions: [tip] })

      expect(navigate).toHaveBeenCalledWith('/root-session', { replace: true })
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('root-session')
    })

    it('remembers the lineage root when a compressed normal chat becomes active', () => {
      const tip = session({ id: 'tip-2', _lineage_root_id: 'root-session', profile: 'default' })

      render({
        locationPathname: '/tip-2',
        profileReady: true,
        routedSessionId: 'tip-2',
        sessions: [tip]
      })

      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('root-session')
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/root-session')
    })

    it('remembers a delegate parent by its stable lineage root after compression', async () => {
      const tip = session({ id: 'parent-session', _lineage_root_id: 'root-session', profile: 'default' })

      render({
        locationPathname: '/delegate-child',
        profileReady: true,
        routedSessionId: 'delegate-child',
        sessions: [child(), tip]
      })

      await waitFor(() =>
        expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('root-session')
      )
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/root-session')
    })

    it('rejects a by-id result from a different profile', async () => {
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'delegate-child')
      const api = vi.fn(async () => session({ ...child(), profile: 'other' }))
      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      render({ profileReady: true, sessions: [parent()] })

      await waitFor(() =>
        expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBeNull()
      )
      expect(navigate).not.toHaveBeenCalled()
    })

    it('preserves a branch child as its own user-facing session', () => {
      render({
        locationPathname: '/branch-child',
        profileReady: true,
        routedSessionId: 'branch-child',
        sessions: [
          session({ id: 'branch-child', parent_session_id: 'parent-session', profile: 'default', source: 'tui' })
        ]
      })

      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('branch-child')
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/branch-child')
    })

    it('does not remember an orphan delegate child', () => {
      render({
        locationPathname: '/orphan-child',
        profileReady: true,
        routedSessionId: 'orphan-child',
        sessions: [session({ id: 'orphan-child', profile: 'default', source: 'subagent' })]
      })

      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBeNull()
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBeNull()
    })

    it('does not navigate from a stale by-id response after a user changes route', async () => {
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'delegate-child')
      let completeRead: ((row: SessionInfo) => void) | undefined

      const api = vi.fn(
        () =>
          new Promise<SessionInfo>(resolve => {
            completeRead = resolve
          })
      )

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      const result = render({ profileReady: true, sessions: [parent()] })
      await waitFor(() => expect(api).toHaveBeenCalled())

      result.rerender({
        activeProfile: 'default',
        locationPathname: '/skills',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: [parent()]
      })
      await act(async () => {
        completeRead?.(child())
      })

      expect(navigate).not.toHaveBeenCalledWith('/parent-session', { replace: true })
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('delegate-child')
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBe('/skills')
    })

    it('keeps a remembered id when a by-id read fails transiently', async () => {
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'unlisted-child')

      const api = vi.fn(async () => {
        throw new Error('temporary read failure')
      })

      desktopWindow.hermesDesktop = { ...desktopWindow.hermesDesktop, api } as unknown as Window['hermesDesktop']

      render({ profileReady: true, sessions: [parent()] })

      await waitFor(() => expect(api).toHaveBeenCalled())
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('unlisted-child')
      expect(navigate).not.toHaveBeenCalled()
    })
  })

  describe('ownership validation', () => {
    it('refuses to restore a session route owned by another profile', () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/ai-session')

      const sessions = [session({ id: 'ai-session', profile: 'ai-engineer' })]

      // The route belongs to ai-engineer; active profile is default.
      // No navigation should happen 窶・wrong owner.
      render({ activeProfile: 'default', profileReady: true, sessions })

      expect(navigate).not.toHaveBeenCalled()
    })

    it('refuses to restore a session id owned by another profile', () => {
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'ai-session')
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/ai-session')

      const sessions = [session({ id: 'ai-session', profile: 'ai-engineer' })]

      render({ activeProfile: 'default', profileReady: true, sessions })

      // Both route and fallback session id are owned by another profile.
      expect(navigate).not.toHaveBeenCalled()
    })

    it('clears stale remembered route owned by wrong profile', () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.ai-engineer', '/ai-session')

      const sessions = [session({ id: 'ai-session', profile: 'ai-engineer' })]

      render({ activeProfile: 'ai-engineer', profileReady: true, sessions })

      // The route and session match the active profile 窶・should restore.
      expect(navigate).toHaveBeenCalledWith('/ai-session', { replace: true })
    })
  })

  describe('two profiles with distinct sessions', () => {
    it('restores profile A session when profile A is active', () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.coder', '/coder-session')

      const sessions = [
        session({ id: 'coder-session', profile: 'coder' }),
        session({ id: 'ops-session', profile: 'ops' })
      ]

      render({ activeProfile: 'coder', profileReady: true, sessions })

      expect(navigate).toHaveBeenCalledWith('/coder-session', { replace: true })
    })

    it('does NOT bleed profile A session into profile B', () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.coder', '/coder-session')

      const sessions = [session({ id: 'coder-session', profile: 'coder' })]

      // ops profile is active but has no own remembered route
      render({
        activeProfile: 'ops',
        profileReady: true,
        sessions
      })

      // No navigation 窶・coder's remembered route doesn't belong to ops.
      expect(navigate).not.toHaveBeenCalled()
    })
  })

  describe('HUD window (win=hud)', () => {
    beforeEach(() => {
      hudWindowMock.mockReturnValue(true)
    })

    it('does NOT restore remembered navigation on a blank new-chat route', () => {
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'remembered-session')
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/remembered-session')

      render({ profileReady: true, sessions: [session({ id: 'remembered-session', profile: 'default' })] })

      // The HUD is a fresh full renderer booting at the default route, but its
      // destination was chosen explicitly by hudTargetSessionId() at open time
      // 窶・remembered-navigation restore must not hijack it to the last session.
      expect(navigate).not.toHaveBeenCalled()
    })

    it('does NOT write remembered navigation while showing a session', () => {
      render({
        profileReady: true,
        routedSessionId: 'live',
        sessions: [session({ id: 'live', profile: 'default' })]
      })

      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBeNull()
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBeNull()
    })

    it('does not restore the remembered session id either', () => {
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'remembered-session')

      render({ profileReady: true, sessions: [session({ id: 'remembered-session', profile: 'default' })] })

      expect(navigate).not.toHaveBeenCalled()
    })
  })

  describe('legacy key behavior', () => {
    it('discards legacy global keys on read and does NOT restore from them', () => {
      // Simulate a pre-per-profile install.
      window.localStorage.setItem('hermes.desktop.lastSessionId', 'legacy-session')
      window.localStorage.setItem('hermes.desktop.lastRoute', '/session/legacy-session')

      // Profile contexts without matching sessions.
      const sessions = [session({ id: 'legacy-session', profile: 'default' })]

      render({ profileReady: true, sessions })

      // Legacy keys must be discarded.
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId')).toBeNull()
      expect(window.localStorage.getItem('hermes.desktop.lastRoute')).toBeNull()

      // And no navigation should happen (the per-profile keys were empty).
      expect(navigate).not.toHaveBeenCalled()
    })
  })

  describe('stale-result suppression during profile switch', () => {
    it('remembers route for the new profile after switch, not the old one', () => {
      const sessions = [
        session({ id: 'coder-session', profile: 'coder' }),
        session({ id: 'ops-session', profile: 'ops' })
      ]

      // Render with coder active and navigate to a session.
      const { rerender } = render({
        activeProfile: 'coder',
        locationPathname: '/coder-session',
        profileReady: true,
        routedSessionId: 'coder-session',
        sessions
      })

      // The coder session should be persisted under coder's key.
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.coder')).toBe('coder-session')

      // Now switch to ops.
      rerender({
        activeProfile: 'ops',
        locationPathname: '/ops-session',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: 'ops-session',
        sessions
      })

      // The ops session should now be persisted under ops's key.
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.ops')).toBe('ops-session')

      // Coder's remembered session should still be there.
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.coder')).toBe('coder-session')
    })

    it('does NOT overwrite remembered state when session ownership fails validation', () => {
      // Simulate an async restore result arriving for a route that doesn't
      // own the active profile.
      const sessions = [session({ id: 'coder-session', profile: 'coder' })]

      // Active profile is ops, but the routed session belongs to coder.
      render({
        activeProfile: 'ops',
        locationPathname: '/',
        profileReady: true,
        routedSessionId: 'coder-session', // wrong profile!
        sessions
      })

      // No session should be remembered for the active profile.
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.ops')).toBeNull()
    })
  })

  describe('route-scoped restoration', () => {
    it('restores a non-session route like /skills', () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/skills')

      const sessions = [session({ id: 'some-session', profile: 'default' })]

      render({ profileReady: true, sessions })

      // /skills is not a session route 窶・no ownership validation needed.
      expect(navigate).toHaveBeenCalledWith('/skills', { replace: true })
    })

    it('does NOT restore overlay routes (settings/command-center)', () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/settings')

      render({ profileReady: true, sessions: [] })

      // Overlay routes should not be restored.
      expect(navigate).not.toHaveBeenCalled()
    })

    it('does NOT persist overlay routes for next boot', () => {
      const { rerender } = render({
        activeProfile: 'default',
        locationPathname: '/settings',
        profileReady: true,
        routedSessionId: null,
        sessions: []
      })

      // Remembering effect fires on route change.
      rerender({
        activeProfile: 'default',
        locationPathname: '/settings',
        profileReady: true,
        resumeExhaustedSessionId: null,
        routedSessionId: null,
        sessions: []
      })

      // Overlay routes must NOT be persisted.
      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBeNull()
    })
  })

  describe('exhausted session cleanup', () => {
    it('clears remembered session id when the exhausted session matches', () => {
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'exhausted')

      const sessions = [session({ id: 'exhausted', profile: 'default' })]

      render({
        profileReady: true,
        resumeExhaustedSessionId: 'exhausted',
        sessions
      })

      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBeNull()
    })

    it('clears remembered route when it carries the exhausted session', () => {
      window.localStorage.setItem('hermes.desktop.lastRoute.profile.default', '/exhausted')

      const sessions = [session({ id: 'exhausted', profile: 'default' })]

      render({
        profileReady: true,
        resumeExhaustedSessionId: 'exhausted',
        sessions
      })

      expect(window.localStorage.getItem('hermes.desktop.lastRoute.profile.default')).toBeNull()
    })

    it('does NOT clear exhausted when profileReady is false', () => {
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'exhausted')

      render({
        profileReady: false,
        resumeExhaustedSessionId: 'exhausted',
        sessions: []
      })

      // profileReady=false gates the cleanup effect.
      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('exhausted')
    })

    it('does NOT clear remembered state when exhausted id does not match', () => {
      window.localStorage.setItem('hermes.desktop.lastSessionId.profile.default', 'other-session')

      render({
        profileReady: true,
        resumeExhaustedSessionId: 'exhausted',
        sessions: [session({ id: 'other-session', profile: 'default' })]
      })

      expect(window.localStorage.getItem('hermes.desktop.lastSessionId.profile.default')).toBe('other-session')
    })
  })

  describe('notification activate + plugin deep links', () => {
    it('navigates when a plugin notification activate payload arrives', () => {
      let activate: ((payload: { activate?: string }) => void) | undefined
      desktopWindow.hermesDesktop = {
        ...desktopWindow.hermesDesktop,
        onNotificationActivate: (cb: (payload: { activate?: string }) => void) => {
          activate = cb

          return () => undefined
        }
      } as unknown as Window['hermesDesktop']

      render({ profileReady: true, sessions: [] })
      activate?.({ activate: '/index-network/intent/1' })
      expect(navigate).toHaveBeenCalledWith('/index-network/intent/1')
    })

    it('navigates hermes://index-network/intent/1 deep links through the same path vocabulary', () => {
      let deepLink: ((payload: { kind: string; name: string; params: Record<string, string> }) => void) | undefined
      desktopWindow.hermesDesktop = {
        ...desktopWindow.hermesDesktop,
        onDeepLink: (cb: (payload: { kind: string; name: string; params: Record<string, string> }) => void) => {
          deepLink = cb

          return () => undefined
        },
        signalDeepLinkReady: vi.fn()
      } as unknown as Window['hermesDesktop']

      render({ profileReady: true, sessions: [] })
      deepLink?.({ kind: 'index-network', name: 'intent/1', params: {} })
      expect(navigate).toHaveBeenCalledWith('/index-network/intent/1')
    })

    it('routes hermes://mcp/install to the pending-install dialog, not navigation', () => {
      let deepLink: ((payload: { kind: string; name: string; params: Record<string, string> }) => void) | undefined
      desktopWindow.hermesDesktop = {
        ...desktopWindow.hermesDesktop,
        onDeepLink: (cb: (payload: { kind: string; name: string; params: Record<string, string> }) => void) => {
          deepLink = cb

          return () => undefined
        },
        signalDeepLinkReady: vi.fn()
      } as unknown as Window['hermesDesktop']

      render({ profileReady: true, sessions: [] })
      deepLink?.({ kind: 'mcp', name: 'install', params: { name: 'context7' } })
      expect(requestMcpInstallFromDeepLink).toHaveBeenCalledWith({ name: 'context7' })
      expect(navigate).not.toHaveBeenCalled()
    })

    it('opens hermes://open/browser?url=窶ｦ in the in-app Browser pane (Chrome/Edge hand-off)', () => {
      let deepLink: ((payload: { kind: string; name: string; params: Record<string, string> }) => void) | undefined
      desktopWindow.hermesDesktop = {
        ...desktopWindow.hermesDesktop,
        onDeepLink: (cb: (payload: { kind: string; name: string; params: Record<string, string> }) => void) => {
          deepLink = cb

          return () => undefined
        },
        signalDeepLinkReady: vi.fn()
      } as unknown as Window['hermesDesktop']

      render({ profileReady: true, sessions: [] })
      deepLink?.({ kind: 'open', name: 'browser', params: { url: 'https://example.com/from-edge' } })
      expect(openPreview).toHaveBeenCalledWith(
        {
          kind: 'url',
          label: 'example.com/from-edge',
          source: 'https://example.com/from-edge',
          url: 'https://example.com/from-edge'
        },
        'explicit-link'
      )
      expect(navigate).not.toHaveBeenCalled()
    })

    it('re-fronts a blank Browser for hermes://open/browser with no url', () => {
      let deepLink: ((payload: { kind: string; name: string; params: Record<string, string> }) => void) | undefined
      desktopWindow.hermesDesktop = {
        ...desktopWindow.hermesDesktop,
        onDeepLink: (cb: (payload: { kind: string; name: string; params: Record<string, string> }) => void) => {
          deepLink = cb

          return () => undefined
        },
        signalDeepLinkReady: vi.fn()
      } as unknown as Window['hermesDesktop']

      render({ profileReady: true, sessions: [] })
      deepLink?.({ kind: 'open', name: 'browser', params: {} })
      expect(openBrowserTab).toHaveBeenCalled()
      expect(navigate).not.toHaveBeenCalled()
    })

    it('does not navigate for hermes://open/browser with a rejected scheme', () => {
      let deepLink: ((payload: { kind: string; name: string; params: Record<string, string> }) => void) | undefined
      desktopWindow.hermesDesktop = {
        ...desktopWindow.hermesDesktop,
        onDeepLink: (cb: (payload: { kind: string; name: string; params: Record<string, string> }) => void) => {
          deepLink = cb

          return () => undefined
        },
        signalDeepLinkReady: vi.fn()
      } as unknown as Window['hermesDesktop']

      render({ profileReady: true, sessions: [] })
      deepLink?.({ kind: 'open', name: 'browser', params: { url: 'javascript:alert(1)' } })
      expect(openPreview).not.toHaveBeenCalled()
      expect(openBrowserTab).not.toHaveBeenCalled()
      expect(navigate).not.toHaveBeenCalled()
    })
  })

  describe('notification click -> focus-session id translation', () => {
    function withFocusSession(): (sessionId: string) => void {
      let handler: ((sessionId: string) => void) | undefined
      desktopWindow.hermesDesktop = {
        ...desktopWindow.hermesDesktop,
        onFocusSession: (cb: (sessionId: string) => void) => {
          handler = cb

          return () => undefined
        }
      } as unknown as Window['hermesDesktop']

      return sessionId => handler?.(sessionId)
    }

    function renderWithRuntimeMap(map: Map<string, string>) {
      return renderHook(
        ({ sessions }: { sessions: readonly SessionInfo[] }) =>
          useDesktopIntegrations({
            activeProfile: 'default',
            chatOpen: false,
            hasPreview: false,
            locationPathname: '/',
            navigate,
            profileReady: true,
            refreshSessions: vi.fn(),
            resumeExhaustedSessionId: null,
            routedSessionId: null,
            runtimeIdByStoredSessionId: { current: map },
            sessions
          }),
        { initialProps: { sessions: [] as readonly SessionInfo[] } }
      )
    }

    it('translates a runtime id via the window map before navigating', () => {
      const fire = withFocusSession()

      renderWithRuntimeMap(new Map([['stored-abc', 'runtime-123']]))
      fire('runtime-123')

      // 'stack' intent spends the unoccupied main draft → in-place navigate.
      expect(navigate).toHaveBeenCalledWith(sessionRoute('stored-abc'))
    })

    it('falls back to the durable per-runtime state mirror when the window map has no binding', () => {
      const fire = withFocusSession()
      const { unmount } = renderWithRuntimeMap(new Map())

      // Simulate a main-pane runtime whose ensureSessionState binding lives in
      // the shared store mirror, not this window's map (window reload /
      // pop-out window / gateway respawn).
      publishSessionState('runtime-999', createClientSessionState('stored-xyz'))
      fire('runtime-999')

      expect(navigate).toHaveBeenCalledWith(sessionRoute('stored-xyz'))

      unmount()
      dropSessionState('runtime-999')
    })
  })
})
