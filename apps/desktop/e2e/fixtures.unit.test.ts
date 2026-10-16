import * as fs from 'node:fs'
import * as os from 'node:os'

import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@playwright/test', () => ({ _electron: { launch: vi.fn(() => { throw new Error('Fixture launch failure') }) } }))
vi.mock('./test', () => ({ installErrorBannerGuard: vi.fn() }))

import { setupMockBackend } from './fixtures'
import * as provider from './mock-server'
import { assertLoopbackListenerStopped } from './owned-process-observer'

afterEach(() => vi.restoreAllMocks())

describe('mock backend fixture resource ownership', () => {
  it('closes its real loopback listener and sandbox when setup fails', async () => {
    const existing = new Set(fs.readdirSync(os.tmpdir()).filter(name => name.startsWith('hermes-e2e-mock-')))
    const start = provider.startMockServer
    let url = ''
    vi.spyOn(provider, 'startMockServer').mockImplementation(async options => {
      const mock = await start(options)
      url = mock.url
      return mock
    })
    await expect(setupMockBackend()).rejects.toThrow()
    expect(url).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/)
    await assertLoopbackListenerStopped(url)
    const added = fs.readdirSync(os.tmpdir()).filter(name => name.startsWith('hermes-e2e-mock-') && !existing.has(name))
    expect(added).toEqual([])
  })
})
