/**
 * W05 RED→GREEN: browser profile/session binding must not cross profiles or
 * adopt stale responses. Pure binding helpers — no live Gateway required.
 */
import { describe, expect, it } from 'vitest'

import { bindBrowserSurface, type BrowserSurfaceBinding, rejectStaleProfileResponse } from './webapp-port-profile'

describe('webapp-port profile binding', () => {
  it('binds stored and logical ids to one profile name', () => {
    const binding = bindBrowserSurface({
      profile: 'coder',
      storedSessionId: 'sess-stored-1',
      logicalSessionId: 'sess-logical-1',
      generation: 'gen-a'
    })

    expect(binding.profile).toBe('coder')
    expect(binding.storedSessionId).toBe('sess-stored-1')
    expect(binding.logicalSessionId).toBe('sess-logical-1')
    expect(binding.generation).toBe('gen-a')
  })

  it('rejects a delayed response from another profile', () => {
    const live: BrowserSurfaceBinding = {
      profile: 'coder',
      storedSessionId: 'a',
      logicalSessionId: 'a',
      generation: 'g1'
    }

    const delayed = { ...live, profile: 'writer', generation: 'g1' }
    expect(rejectStaleProfileResponse(live, delayed)).toBe(true)
  })

  it('rejects a response after generation rotation (ACK loss / reconnect)', () => {
    const live: BrowserSurfaceBinding = {
      profile: 'coder',
      storedSessionId: 'a',
      logicalSessionId: 'a',
      generation: 'g1'
    }

    expect(rejectStaleProfileResponse(live, { ...live, generation: 'g2' })).toBe(true)
    expect(rejectStaleProfileResponse(live, live)).toBe(false)
  })

  it('keeps two tabs on the same profile distinct by logical id', () => {
    const tab1 = bindBrowserSurface({
      profile: 'coder',
      storedSessionId: 'shared-store',
      logicalSessionId: 'tab-1',
      generation: 'g1'
    })

    const tab2 = bindBrowserSurface({
      profile: 'coder',
      storedSessionId: 'shared-store',
      logicalSessionId: 'tab-2',
      generation: 'g1'
    })

    expect(tab1.storedSessionId).toBe(tab2.storedSessionId)
    expect(tab1.logicalSessionId).not.toBe(tab2.logicalSessionId)
  })
})
