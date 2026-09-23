import { describe, expect, it } from 'vitest'

import { TRANSLATIONS } from './catalog'

describe('engineering stages in the existing model picker', () => {
  it('provides labels and hints for every supported locale', () => {
    for (const translations of Object.values(TRANSLATIONS)) {
      const models = translations.settings.model

      for (const role of ['planner', 'worker', 'reviewer']) {
        expect(models.tasks[`engineering_${role}`]?.label).toBeTruthy()
        expect(models.tasks[`engineering_${role}`]?.hint).toBeTruthy()
      }
    }
  })
})
