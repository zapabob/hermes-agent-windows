// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'

describe('favorite model presentation persistence', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.resetModules()
  })

  it('rehydrates provider-specific favorites in a fresh module instance', async () => {
    const first = await import('./favorite-models')
    first.toggleFavoriteModel('custom:local-a', 'same-model')
    first.toggleFavoriteModel('custom:local-b', 'same-model')
    vi.resetModules()
    const fresh = await import('./favorite-models')
    expect(fresh.$favoriteModels.get()).toEqual(['custom:local-a::same-model', 'custom:local-b::same-model'])
    fresh.toggleFavoriteModel('custom:local-a', 'same-model')
    expect(fresh.$favoriteModels.get()).toEqual(['custom:local-b::same-model'])
  })

  it('keeps a temporarily unavailable model when a different favorite is edited', async () => {
    const store = await import('./favorite-models')
    store.toggleFavoriteModel('offline-provider', 'retained-model')
    store.toggleFavoriteModel('available-provider', 'new-model')
    store.toggleFavoriteModel('available-provider', 'new-model')
    expect(store.$favoriteModels.get()).toEqual(['offline-provider::retained-model'])
  })
})
