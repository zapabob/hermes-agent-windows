import { atom } from 'nanostores'

import { persistStringArray, storedStringArray } from '@/lib/storage'

import { modelVisibilityKey } from './model-visibility'

const STORAGE_KEY = 'hermes.desktop.favorite-models'

/** Renderer presentation preference; never changes the backend catalog or route. */
export const $favoriteModels = atom<string[]>(storedStringArray(STORAGE_KEY))

/** Preserve absent catalog entries so an offline provider cannot erase favorites. */
export function toggleFavoriteModel(provider: string, model: string): void {
  const key = modelVisibilityKey(provider, model)
  const current = $favoriteModels.get()
  const next = current.includes(key) ? current.filter(entry => entry !== key) : [...current, key]

  $favoriteModels.set(next)
  persistStringArray(STORAGE_KEY, next)
}
