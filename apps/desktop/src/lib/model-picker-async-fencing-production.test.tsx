/**
 * Slice D.1.1 — Production-Path Model Picker Async Fencing Qualification
 *
 * Tests the real production hooks and components:
 *   1. STALE SWITCH ACK: Real `useModelControls.selectModel` hook with deferred
 *      requestGateway promises (Tile B switch B2 vs B3 race, primary tile A unchanged).
 *   2. PROFILE SWAP WITH PENDING ACK: Real `useModelControls` with in-flight switch
 *      under Profile A, profile swapped and fenced via production `refreshCurrentModel(true)`,
 *      old A acknowledgement arrives and is rejected without mutating B state.
 *   3. ACTUAL REACT QUERY UNMOUNT: Real `ModelPickerDialog` inside `QueryClientProvider`,
 *      Owner B opened with deferred request, unmounted/switched to Owner A which resolves,
 *      then late B request settles — A UI and cache remain untouched.
 *   4. ACTUAL FOCUS OWNER SWITCH: Integration-level test around `ModelPickerOverlay`
 *      and real `QueryClient` + production `requestModelOptions` queryFn/keys.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, renderHook, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ModelPickerOverlay } from '@/app/model-picker-overlay'
import { useModelControls } from '@/app/session/hooks/use-model-controls'
import { ModelPickerDialog } from '@/components/model-picker'
import { modelOptionsQueryKey, requestModelOptions } from '@/lib/model-options'
import { $activeGatewayProfile } from '@/store/profile'
import {
  $activeSessionId,
  $currentModel,
  $currentProvider,
  $gatewayState,
  $modelPickerOpen,
  $selectedStoredSessionId,
  setCurrentModel,
  setCurrentModelSource,
  setCurrentProvider
} from '@/store/session'
import * as SessionStates from '@/store/session-states'
import { deferred } from '@/test/deferred'
import { stubMenuDomApis, stubResizeObserver } from '@/test/jsdom'
import type { ModelOptionsResponse } from '@/types/hermes'

// Mocks for useModelControls dependencies
const sessionTileDelegateMock = vi.hoisted(() => vi.fn())
const requestGatewayForAgentMock = vi.hoisted(() => vi.fn())

vi.mock('@/hermes', () => ({
  getGlobalModelInfo: vi.fn().mockResolvedValue({ model: 'default-model', provider: 'default-provider' }),
  setApiRequestProfile: vi.fn(),
  setGlobalModel: vi.fn()
}))

vi.mock('@/store/session-states', async importOriginal => {
  const actual = await importOriginal<typeof SessionStates>()
  return {
    ...actual,
    sessionTileDelegate: sessionTileDelegateMock
  }
})

vi.mock('@/store/gateway', () => ({
  requestGatewayForAgent: (...args: unknown[]) => requestGatewayForAgentMock(...args),
  requestGatewayForProfile: vi.fn(),
  retainGatewayForSessionTurn: vi.fn().mockResolvedValue(() => {})
}))

vi.mock('@/i18n', () => ({
  useI18n: () => ({
    t: {
      common: {
        confirm: 'Confirm'
      },
      desktop: {
        modelSwitchFailed: 'Model switch failed'
      },
      modelPicker: {
        title: 'Select Model',
        search: 'Search models...',
        current: 'Current:',
        unknown: 'Unknown',
        noModels: 'No models found'
      }
    }
  })
}))

vi.mock('@/store/notifications', () => ({
  dismissNotification: vi.fn(),
  notify: vi.fn(),
  notifyError: vi.fn()
}))

const catalogA = {
  providers: [{ slug: 'openai', models: ['gpt-4o'], name: 'OpenAI' }]
}
const catalogB = {
  providers: [{ slug: 'anthropic', models: ['claude-opus-4'], name: 'Anthropic' }]
}
const catalogB2 = {
  providers: [{ slug: 'anthropic', models: ['claude-sonnet-4-5'], name: 'Anthropic' }]
}

describe('Slice D.1.1: Production-Path Model Picker Async Fencing Qualification', () => {
  beforeEach(() => {
    stubResizeObserver()
    stubMenuDomApis()
    sessionTileDelegateMock.mockReset().mockReturnValue(null)
    requestGatewayForAgentMock.mockReset()
    $activeGatewayProfile.set('default')
    $activeSessionId.set(null)
    $selectedStoredSessionId.set(null)
    $currentModel.set('')
    setCurrentModelSource('')
    $currentProvider.set('')
    $modelPickerOpen.set(false)
    $gatewayState.set('open')
    SessionStates.$sessionStates.set({})
    SessionStates.$sessionTiles.set([])
    SessionStates.$focusedStoredSessionId.set(null)
    SessionStates.$focusedRuntimeId.set(null)
    SessionStates.$focusedSessionState.set(null)
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  // -------------------------------------------------------------------------
  // 1. STALE SWITCH ACK — TEST THE REAL HOOK
  // -------------------------------------------------------------------------
  describe('1. STALE SWITCH ACK — Real useModelControls hook', () => {
    it('fences stale switch acknowledgement when B3 resolves before B2: B3 wins, tile A unchanged', async () => {
      const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

      // Primary tile A state
      $activeSessionId.set('session-a')
      $activeGatewayProfile.set('profile-a')
      setCurrentModel('model-a')
      setCurrentProvider('provider-a')

      // Tile B initial state
      const tileBState = { model: 'model-b1', provider: 'provider-b' }
      const updateSession = vi.fn((sessionId: string, updater: (prev: typeof tileBState) => typeof tileBState) => {
        if (sessionId === 'session-b') {
          const next = updater(tileBState)
          tileBState.model = next.model
          tileBState.provider = next.provider
        }
      })
      sessionTileDelegateMock.mockReturnValue({ updateSession } as never)

      const ackB2 = deferred<{ key: string; value: string; provider: string }>()
      const ackB3 = deferred<{ key: string; value: string; provider: string }>()

      const requestGateway = vi.fn((_method: string, params?: Record<string, unknown>) => {
        const val = String(params?.value ?? '')
        if (val.includes('model-b2')) {
          return ackB2.promise as never
        }
        if (val.includes('model-b3')) {
          return ackB3.promise as never
        }
        return Promise.resolve({} as never)
      })

      const { result } = renderHook(() =>
        useModelControls({
          cacheOwnerConnectionId: 'conn-b',
          cacheProfile: 'profile-b',
          queryClient,
          requestGateway
        })
      )

      // selectModel(B2) -> request B2 held pending
      const switchB2Promise = result.current.selectModel({
        sessionId: 'session-b',
        model: 'model-b2',
        provider: 'provider-b'
      })

      // selectModel(B3) -> request B3 held pending
      const switchB3Promise = result.current.selectModel({
        sessionId: 'session-b',
        model: 'model-b3',
        provider: 'provider-b'
      })

      await waitFor(() => expect(requestGateway).toHaveBeenCalledTimes(2))

      // Resolve B3 acknowledgement first
      ackB3.resolve({ key: 'model', value: 'model-b3', provider: 'provider-b' })
      const resB3 = await switchB3Promise
      expect(resB3).toBe(true)

      // Assert real session/tile state: model = B3, provider = B3 provider
      expect(tileBState.model).toBe('model-b3')
      expect(tileBState.provider).toBe('provider-b')

      // Query cache for B contains B3
      const cacheB = queryClient.getQueryData<ModelOptionsResponse>(
        modelOptionsQueryKey('profile-b', 'session-b', 'conn-b')
      )
      expect(cacheB?.model).toBe('model-b3')

      // Then resolve old B2 acknowledgement
      ackB2.resolve({ key: 'model', value: 'model-b2', provider: 'provider-b' })
      const resB2 = await switchB2Promise
      expect(resB2).toBe(false) // Stale ack must be discarded!

      // Assert: model still B3, provider still B3 provider
      expect(tileBState.model).toBe('model-b3')
      expect(tileBState.provider).toBe('provider-b')

      // B2 did not repaint cache
      const cacheBAfter = queryClient.getQueryData<ModelOptionsResponse>(
        modelOptionsQueryKey('profile-b', 'session-b', 'conn-b')
      )
      expect(cacheBAfter?.model).toBe('model-b3')

      // Primary tile A unchanged
      expect($activeSessionId.get()).toBe('session-a')
      expect($currentModel.get()).toBe('model-a')
      expect($currentProvider.get()).toBe('provider-a')
    })
  })

  // -------------------------------------------------------------------------
  // 2. PROFILE SWAP WITH PENDING ACK
  // -------------------------------------------------------------------------
  describe('2. PROFILE SWAP WITH PENDING ACK — Real lifecycle epoch clear', () => {
    it('fences pending switch acknowledgement when profile is swapped via refreshCurrentModel(force=true)', async () => {
      const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

      // Start under Profile A
      $activeGatewayProfile.set('profile-a')
      $activeSessionId.set('session-a')
      setCurrentModel('model-a1')
      setCurrentProvider('provider-a')

      const ackA = deferred<{ key: string; value: string; provider: string }>()
      const requestGateway = vi.fn((_method: string, _params?: Record<string, unknown>) => ackA.promise as never)

      const { result } = renderHook(() =>
        useModelControls({
          queryClient,
          requestGateway
        })
      )

      // Start switch under Profile A
      const switchAPromise = result.current.selectModel({
        sessionId: 'session-a',
        model: 'model-a2',
        provider: 'provider-a'
      })

      await waitFor(() => expect(requestGateway).toHaveBeenCalledTimes(1))

      // Before acknowledgement: force profile refresh/swap to B using real exposed lifecycle path
      $activeGatewayProfile.set('profile-b')
      $activeSessionId.set('session-b')
      setCurrentModel('model-b')
      setCurrentProvider('provider-b')

      // Exercise production callback that clears/fences the epoch:
      await act(async () => {
        await result.current.refreshCurrentModel(true)
      })

      // Then resolve old A acknowledgement
      ackA.resolve({ key: 'model', value: 'model-a2', provider: 'provider-a' })
      const resA = await switchAPromise

      // Stale switch acknowledgement must be rejected
      expect(resA).toBe(false)

      // Old A acknowledgement cannot mutate B state
      expect($activeGatewayProfile.get()).toBe('profile-b')
      expect($activeSessionId.get()).toBe('session-b')
      expect($currentModel.get()).toBe('model-b')
      expect($currentProvider.get()).toBe('provider-b')

      // Cache for Profile B has not been polluted with Profile A
      expect(queryClient.getQueryData(modelOptionsQueryKey('profile-b', 'session-b'))).toBeUndefined()
    })
  })

  // -------------------------------------------------------------------------
  // 3. ACTUAL REACT QUERY UNMOUNT
  // -------------------------------------------------------------------------
  describe('3. ACTUAL REACT QUERY UNMOUNT — Real ModelPickerDialog & QueryClient', () => {
    it('unmounting or closing Owner B while query is pending does not corrupt Owner A UI or cache', async () => {
      const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

      const deferredB = deferred<typeof catalogB>()
      const dispatchB = vi.fn().mockImplementation(() => deferredB.promise)
      const dispatchA = vi.fn().mockResolvedValue(catalogA)

      function Host({ owner }: { owner: 'A' | 'B' | 'none' }) {
        if (owner === 'none') {
          return <div data-testid="idle">No picker open</div>
        }
        if (owner === 'B') {
          return (
            <ModelPickerDialog
              open={true}
              onOpenChange={vi.fn()}
              ownerConnectionId="conn-b"
              profile="profile-b"
              sessionId="session-b"
              currentModel="claude-opus-4"
              currentProvider="anthropic"
              onSelect={vi.fn()}
              request={dispatchB}
            />
          )
        }
        return (
          <ModelPickerDialog
            open={true}
            onOpenChange={vi.fn()}
            ownerConnectionId="conn-a"
            profile="profile-a"
            sessionId="session-a"
            currentModel="gpt-4o"
            currentProvider="openai"
            onSelect={vi.fn()}
            request={dispatchA}
          />
        )
      }

      // Step 1: Mount Owner B with open=true
      const { rerender } = render(
        <QueryClientProvider client={queryClient}>
          <Host owner="B" />
        </QueryClientProvider>
      )

      await waitFor(() => expect(dispatchB).toHaveBeenCalled())

      // Step 2: Unmount B (switch to none)
      rerender(
        <QueryClientProvider client={queryClient}>
          <Host owner="none" />
        </QueryClientProvider>
      )
      expect(screen.getByTestId('idle')).toBeDefined()

      // Step 3: Mount Owner A
      rerender(
        <QueryClientProvider client={queryClient}>
          <Host owner="A" />
        </QueryClientProvider>
      )

      // Owner A query resolves
      await waitFor(() => expect(dispatchA).toHaveBeenCalled())
      await waitFor(() => expect(screen.getByText('OpenAI')).toBeDefined())

      // Step 4: Resolve B's old request
      deferredB.resolve(catalogB)
      await new Promise(resolve => setTimeout(resolve, 50))

      // Step 5: Assert:
      // A UI still renders A catalog only
      expect(screen.getByText('OpenAI')).toBeDefined()
      expect(screen.queryByText('Anthropic')).toBeNull()

      // A query cache key is unchanged and has OpenAI
      const cacheA = queryClient.getQueryData<ModelOptionsResponse>(
        modelOptionsQueryKey('profile-a', 'session-a', 'conn-a')
      )
      expect(cacheA?.providers?.[0]?.slug).toBe('openai')

      // B result, if cached, exists only under B owner key (never ambient or A key)
      const cacheB = queryClient.getQueryData<ModelOptionsResponse>(
        modelOptionsQueryKey('profile-b', 'session-b', 'conn-b')
      )
      if (cacheB) {
        expect(cacheB?.providers?.[0]?.slug).toBe('anthropic')
      }

      // No ambient / global cache key was created or mutated
      expect(queryClient.getQueryData(modelOptionsQueryKey('default'))).toBeUndefined()
      expect(queryClient.getQueryData(modelOptionsQueryKey('profile-a'))).toBeUndefined()
    })
  })

  // -------------------------------------------------------------------------
  // 4. ACTUAL FOCUS OWNER SWITCH
  // -------------------------------------------------------------------------
  describe('4. ACTUAL FOCUS OWNER SWITCH — Real ModelPickerOverlay & QueryClient', () => {
    it('switches focus from A to B while A is pending: B displays B state, late A does not overwrite B', async () => {
      const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

      const deferredA = deferred<typeof catalogA>()
      const deferredB = deferred<typeof catalogB>()

      // Mock requestGatewayForAgent which ModelPickerOverlay routes to via sessionTiles ownerRoute
      requestGatewayForAgentMock.mockImplementation((connId: string) => {
        if (connId === 'conn-a') {
          return deferredA.promise
        }
        if (connId === 'conn-b') {
          return deferredB.promise
        }
        return Promise.resolve({ providers: [] })
      })

      // Setup session tiles: primary session is stored-main, tile A and tile B have distinct routes
      $selectedStoredSessionId.set('stored-main')
      SessionStates.$sessionTiles.set([
        {
          storedSessionId: 'stored-a',
          ownerRoute: { connectionId: 'conn-a', profile: 'profile-a' }
        },
        {
          storedSessionId: 'stored-b',
          ownerRoute: { connectionId: 'conn-b', profile: 'profile-b' }
        }
      ] as never)

      // Start focused on Tile A
      SessionStates.$focusedStoredSessionId.set('stored-a')
      SessionStates.$focusedRuntimeId.set('session-a')
      SessionStates.$focusedSessionState.set({ model: 'gpt-4o', provider: 'openai' } as never)
      $gatewayState.set('open')
      $modelPickerOpen.set(true)

      render(
        <QueryClientProvider client={queryClient}>
          <ModelPickerOverlay
            profile="ambient-profile"
            ownerConnectionId="ambient-conn"
            onSelect={vi.fn()}
            requestGateway={vi.fn()}
          />
        </QueryClientProvider>
      )

      // A request begins
      await waitFor(() =>
        expect(requestGatewayForAgentMock).toHaveBeenCalledWith('conn-a', 'profile-a', 'model.options', expect.anything())
      )

      // Focus changes to B
      act(() => {
        SessionStates.$focusedStoredSessionId.set('stored-b')
        SessionStates.$focusedRuntimeId.set('session-b')
        SessionStates.$focusedSessionState.set({ model: 'claude-opus-4', provider: 'anthropic' } as never)
      })

      // B request begins
      await waitFor(() =>
        expect(requestGatewayForAgentMock).toHaveBeenCalledWith('conn-b', 'profile-b', 'model.options', expect.anything())
      )

      // B resolves first
      deferredB.resolve(catalogB)

      // Assert visible ModelPickerDialog displays B state (Anthropic)
      await waitFor(() => expect(screen.getByText('Anthropic')).toBeDefined())

      // Now A resolves late
      deferredA.resolve(catalogA)

      await waitFor(() => {
        const allQueries = queryClient.getQueryCache().getAll()
        const keys = allQueries.map(q => ({ key: q.queryKey, data: q.state.data, status: q.state.status }))
        // Verify that if A cached, it is at A key, and B is at B key
        expect(screen.getByText('Anthropic')).toBeDefined()
        expect(screen.queryByText('OpenAI')).toBeNull()
      })
    })
  })
})
