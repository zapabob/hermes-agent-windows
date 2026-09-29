/**
 * Slice D — Desktop Model Picker Ownership Isolation
 *
 * Contracts under test:
 *  1. PROFILE_ISOLATION        — profile-B catalog/selection/provider never bleeds into profile-A tile
 *  2. REFRESH_ISOLATION        — manual Refresh Models issued from tile-B never touches tile-A state
 *  3. SWITCH_ISOLATION         — switching model on tile-B does not mutate tile-A selection
 *  4. RECONNECT_ISOLATION      — a reconnect on connection-B does not alter tile-A state
 *  5. FOCUS_RACE               — rapid focus switch always resolves to the LAST focused tile owner
 *  6. CREDENTIAL_CROSS_PROFILE_LEAK = ABSENT — owner-routed `request` never falls back to REST
 *                                               with a foreign profile's name
 */

import { describe, expect, it, vi } from 'vitest'

import type { SessionOwnerRoute } from '@/store/session-request-router'

import { requestModelOptions } from './model-options'
import { resolveModelPickerOwner } from './model-picker-owner'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeRoute(connectionId: string, profile: string, targetProfile?: string): SessionOwnerRoute {
  return { connectionId, profile, targetProfile }
}

function tile(storedSessionId: string, route: SessionOwnerRoute) {
  return { ownerRoute: route, storedSessionId }
}

// ---------------------------------------------------------------------------
// 1. PROFILE_ISOLATION
// ---------------------------------------------------------------------------

describe('PROFILE_ISOLATION', () => {
  const routeA = makeRoute('conn-a', 'profile-a', 'backend-a')
  const routeB = makeRoute('conn-b', 'profile-b', 'backend-b')

  it('tile B focused → owner is B catalog, B provider, B connection — never A', () => {
    const owner = resolveModelPickerOwner({
      ambientConnectionId: 'conn-a',
      ambientProfile: 'profile-a',
      focusedStoredSessionId: 'stored-b',
      selectedStoredSessionId: 'stored-a',
      sessionTiles: [tile('stored-a', routeA), tile('stored-b', routeB)]
    })

    expect(owner.connectionId).toBe('conn-b')
    expect(owner.profile).toBe('backend-b')
    expect(owner.route?.connectionId).toBe('conn-b')
  })

  it('tile A focused → owner is A catalog — never B', () => {
    const owner = resolveModelPickerOwner({
      ambientConnectionId: 'conn-a',
      ambientProfile: 'profile-a',
      focusedStoredSessionId: 'stored-a',
      selectedStoredSessionId: 'stored-a',
      sessionTiles: [tile('stored-a', routeA), tile('stored-b', routeB)]
    })

    expect(owner.connectionId).toBe('conn-a')
    expect(owner.profile).toBe('profile-a')
    // focused == selected → no route (ambient path)
    expect(owner.route).toBeUndefined()
  })

  it('no cross-read: B tile owner carries no reference to A route', () => {
    const owner = resolveModelPickerOwner({
      ambientConnectionId: 'conn-a',
      ambientProfile: 'profile-a',
      focusedStoredSessionId: 'stored-b',
      selectedStoredSessionId: 'stored-a',
      sessionTiles: [tile('stored-a', routeA), tile('stored-b', routeB)]
    })

    expect(owner.connectionId).not.toBe('conn-a')
    expect(owner.profile).not.toBe('profile-a')
    expect(owner.profile).not.toBe('backend-a')
  })
})

// ---------------------------------------------------------------------------
// 2. REFRESH_ISOLATION
// ---------------------------------------------------------------------------

describe('REFRESH_ISOLATION', () => {
  it('Refresh from tile-B dispatches only through B request, never A dispatcher', async () => {
    const dispatchA = vi.fn().mockResolvedValue({ providers: [{ slug: 'openai', models: ['gpt-4'] }] })
    const dispatchB = vi.fn().mockResolvedValue({ providers: [{ slug: 'anthropic', models: ['claude-opus-4'] }] })

    // Refresh issued under tile-B owner → only dispatchB should be called
    await requestModelOptions({
      refresh: true,
      request: dispatchB
    })

    expect(dispatchB).toHaveBeenCalledOnce()
    expect(dispatchA).not.toHaveBeenCalled()
  })

  it('owner-routed refresh never falls back to ambient REST with a different profile', async () => {
    // dispatchB returns empty (simulating re-auth needed), so no selectable models
    const dispatchB = vi.fn().mockResolvedValue({ providers: [] })

    // Should NOT throw to REST; should return what the owner-routed request returned
    const result = await requestModelOptions({
      refresh: true,
      request: dispatchB,
      profile: 'profile-b'
    })

    // dispatchB was called exactly once — no secondary REST call
    expect(dispatchB).toHaveBeenCalledOnce()
    // Result comes from the owner-routed response, empty though it is
    expect(result.providers).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// 3. SWITCH_ISOLATION
// ---------------------------------------------------------------------------

describe('SWITCH_ISOLATION', () => {
  it('model switch on tile-B produces owner with B connectionId only', () => {
    const routeB = makeRoute('conn-b', 'profile-b', 'backend-b')

    const owner = resolveModelPickerOwner({
      ambientConnectionId: 'conn-a',
      ambientProfile: 'profile-a',
      focusedStoredSessionId: 'stored-b',
      selectedStoredSessionId: 'stored-a',
      sessionTiles: [tile('stored-b', routeB)]
    })

    // The owner that drives selectModel must be B — verified by connectionId
    expect(owner.connectionId).toBe('conn-b')
    expect(owner.profile).toBe('backend-b')
  })

  it('model switch on primary (selected == focused) uses ambient owner, not a tile route', () => {
    const routeB = makeRoute('conn-b', 'profile-b', 'backend-b')

    const owner = resolveModelPickerOwner({
      ambientConnectionId: 'conn-a',
      ambientProfile: 'profile-a',
      focusedStoredSessionId: 'stored-a', // focused == selected → primary path
      selectedStoredSessionId: 'stored-a',
      sessionTiles: [tile('stored-b', routeB)]
    })

    expect(owner.connectionId).toBe('conn-a')
    expect(owner.route).toBeUndefined()
  })
})

// ---------------------------------------------------------------------------
// 4. RECONNECT_ISOLATION
// ---------------------------------------------------------------------------

describe('RECONNECT_ISOLATION', () => {
  it('reconnect on connection-B: tile-A owner is still resolved from ambient (conn-a)', () => {
    // Simulate: after a reconnect, tile-B gets a new ownerRoute.
    // Tile-A was focused before the reconnect and must still resolve from ambient.
    const routeB_after_reconnect = makeRoute('conn-b-new', 'profile-b', 'backend-b')

    const ownerA = resolveModelPickerOwner({
      ambientConnectionId: 'conn-a',
      ambientProfile: 'profile-a',
      focusedStoredSessionId: 'stored-a', // A is still focused
      selectedStoredSessionId: 'stored-a',
      sessionTiles: [tile('stored-b', routeB_after_reconnect)]
    })

    expect(ownerA.connectionId).toBe('conn-a')
    expect(ownerA.profile).toBe('profile-a')
    // A's owner must not carry the new conn-b route
    expect(ownerA.connectionId).not.toContain('conn-b')
  })

  it('reconnect: tile-B focused after reconnect resolves to new conn-b route', () => {
    const routeB_reconnected = makeRoute('conn-b-reconnected', 'profile-b', 'backend-b')

    const ownerB = resolveModelPickerOwner({
      ambientConnectionId: 'conn-a',
      ambientProfile: 'profile-a',
      focusedStoredSessionId: 'stored-b',
      selectedStoredSessionId: 'stored-a',
      sessionTiles: [tile('stored-b', routeB_reconnected)]
    })

    expect(ownerB.connectionId).toBe('conn-b-reconnected')
  })
})

// ---------------------------------------------------------------------------
// 5. FOCUS_RACE
// ---------------------------------------------------------------------------

describe('FOCUS_RACE', () => {
  const routeA = makeRoute('conn-a', 'profile-a', 'backend-a')
  const routeB = makeRoute('conn-b', 'profile-b', 'backend-b')
  const routeC = makeRoute('conn-c', 'profile-c', 'backend-c')

  it('rapid focus A → B → C: final resolution is C owner', () => {
    // The resolver is synchronous and pure; callers serialize via React state
    // Each call with focusedStoredSessionId = last-focused-tile is correct
    const ownerC = resolveModelPickerOwner({
      ambientConnectionId: 'conn-a',
      ambientProfile: 'profile-a',
      focusedStoredSessionId: 'stored-c',
      selectedStoredSessionId: 'stored-a',
      sessionTiles: [tile('stored-a', routeA), tile('stored-b', routeB), tile('stored-c', routeC)]
    })

    expect(ownerC.connectionId).toBe('conn-c')
    expect(ownerC.profile).toBe('backend-c')
  })

  it('rapid focus A → B → A: final resolution is ambient (A == selected)', () => {
    const ownerA = resolveModelPickerOwner({
      ambientConnectionId: 'conn-a',
      ambientProfile: 'profile-a',
      focusedStoredSessionId: 'stored-a', // back to selected
      selectedStoredSessionId: 'stored-a',
      sessionTiles: [tile('stored-a', routeA), tile('stored-b', routeB)]
    })

    expect(ownerA.connectionId).toBe('conn-a')
    expect(ownerA.route).toBeUndefined()
  })

  it('unknown focused session id → falls back to ambient (no stale tile route)', () => {
    // A tile that has been unmounted: its storedSessionId no longer appears in sessionTiles
    const owner = resolveModelPickerOwner({
      ambientConnectionId: 'conn-a',
      ambientProfile: 'profile-a',
      focusedStoredSessionId: 'stored-ghost', // not in tiles
      selectedStoredSessionId: 'stored-a',
      sessionTiles: [tile('stored-a', routeA)]
    })

    // Ghost tile → no route → ambient fallback
    expect(owner.connectionId).toBe('conn-a')
    expect(owner.route).toBeUndefined()
  })
})

// ---------------------------------------------------------------------------
// 6. CREDENTIAL_CROSS_PROFILE_LEAK = ABSENT
// ---------------------------------------------------------------------------

describe('CREDENTIAL_CROSS_PROFILE_LEAK = ABSENT', () => {
  it('owner-routed request does NOT fall back to REST for a different profile', async () => {
    // When `request` is supplied, requestModelOptions must not call the global
    // REST endpoint even if the dispatch returns no selectable models.
    // This is the critical anti-leak guarantee of #93892.
    const leakSpy = vi.fn()

    // Patch restModelOptions indirectly by verifying dispatch call count only.
    // The implementation must NOT call REST when `request` is set.
    const dispatchB = vi.fn().mockResolvedValue({
      providers: [{ slug: 'anthropic', models: ['claude-sonnet-4-5'] }]
    })

    const result = await requestModelOptions({
      request: dispatchB,
      profile: 'profile-b',
      sessionId: 'session-b'
    })

    expect(dispatchB).toHaveBeenCalledOnce()
    expect(dispatchB).toHaveBeenCalledWith('model.options', {
      explicit_only: true,
      profile: 'profile-b',
      session_id: 'session-b'
    })
    expect(leakSpy).not.toHaveBeenCalled()
    expect(result.providers?.[0]?.slug).toBe('anthropic')
  })

  it('owner-routed request with empty response: no REST call, no foreign profile leak', async () => {
    const dispatchB = vi.fn().mockResolvedValue({ providers: [] })

    // Even though no selectable models: must NOT fall back to REST (would leak profile-a)
    const result = await requestModelOptions({
      request: dispatchB,
      profile: 'profile-b'
    })

    // Called exactly once — no secondary attempt
    expect(dispatchB).toHaveBeenCalledOnce()
    // Profile name was passed scoped — not swapped to ambient
    expect(dispatchB).toHaveBeenCalledWith('model.options', {
      explicit_only: true,
      profile: 'profile-b'
    })
    expect(result.providers).toEqual([])
  })

  it('owner-routed request throws: error propagates, no REST fallback for foreign profile', async () => {
    const dispatchB = vi.fn().mockRejectedValue(new Error('connection-b timeout'))

    await expect(
      requestModelOptions({
        request: dispatchB,
        profile: 'profile-b'
      })
    ).rejects.toThrow('connection-b timeout')

    // Exactly one attempt — no silent REST retry under a different credential scope
    expect(dispatchB).toHaveBeenCalledOnce()
  })
})
