import { resolve } from 'node:path'
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { loadDistributionIdentity } from './set-exe-identity.mjs'

describe('Windows executable identity', () => {
  it('comes from downstream distribution metadata', () => {
    const distribution = loadDistributionIdentity(resolve(import.meta.dirname, '..'))
    const desktop = JSON.parse(readFileSync(resolve(import.meta.dirname, '../package.json'), 'utf8'))

    expect(distribution.id).toBe('hermes-agent-windows')
    expect(distribution.display_name).toBe('Hermes Agent Windows Workstation Edition')
    expect(distribution.version).toBe(desktop.version)
    expect(distribution.windowsVersion).toBe(`${desktop.version}.0`)
  })
})
