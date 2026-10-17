import { EventEmitter } from 'node:events'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'

import { _electron, type ElectronApplication } from '@playwright/test'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@playwright/test', () => ({ _electron: { launch: vi.fn(() => { throw new Error('Fixture launch failure') }) } }))
vi.mock('./electron-binary', () => ({ resolveElectronBinary: () => 'owned-synthetic-electron' }))
vi.mock('./test', () => ({ installErrorBannerGuard: vi.fn() }))

import { setupDeadBackend, setupMockBackend, setupNoProvider } from './fixtures'
import * as provider from './mock-server'
import { assertLoopbackListenerStopped } from './owned-process-observer'

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

function fakeApp(stopped = false, windowFails = false): ElectronApplication {
  const child = Object.assign(new EventEmitter(), {
    pid: 2147483647, exitCode: stopped ? 0 : null, signalCode: null
  })

  return {
    firstWindow: vi.fn(async () => {
      if (windowFails) {throw new Error('owned first-window failure')}

      return {}
    }),
    close: vi.fn(async () => undefined),
    process: () => child
  } as unknown as ElectronApplication
}

const modes = [
  { label: 'mock', setup: () => setupMockBackend() },
  { label: 'no-provider', setup: () => setupNoProvider() },
  { label: 'dead-backend', setup: () => setupDeadBackend() }
]

async function closeMockIfPresent(fixture: Awaited<ReturnType<typeof setupMockBackend>> | Awaited<ReturnType<typeof setupNoProvider>>) {
  if ('mock' in fixture) {
    await fixture.mock.close().catch((error: NodeJS.ErrnoException) => {
      if (error.code !== 'ERR_SERVER_NOT_RUNNING') {throw error}
    })
  }
}

function removeOwnedUnitSandbox(name: string): void {
  const owned = path.resolve(os.tmpdir(), name)

  if (path.dirname(owned) !== path.resolve(os.tmpdir()) || !path.basename(owned).startsWith('hermes-e2e-mock-')) {
    throw new Error('Refusing cleanup outside this unit test sandbox')
  }

  fs.rmSync(owned, { recursive: true, force: true })
}

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

  it.each(modes)('$label retains bytes when its Electron cannot be confirmed stopped', async ({ setup }) => {
    vi.mocked(_electron.launch).mockResolvedValueOnce(fakeApp())
    const fixture = await setup()
    const evidence = `${fixture.sandbox.hermesHome}/owned-evidence.txt`
    fs.writeFileSync(evidence, 'retain until exact owner exit is confirmed', 'utf8')

    try {
      vi.useFakeTimers()
      const failure = fixture.cleanup().then(() => undefined, (error: unknown) => error)
      await vi.runAllTimersAsync()
      const error = await failure
      expect(error).toBeInstanceOf(Error)
      expect((error as Error).message).toContain('did not exit after close')
      vi.useRealTimers()

      if ('mockUrl' in fixture && typeof fixture.mockUrl === 'string') {await assertLoopbackListenerStopped(fixture.mockUrl)}
      expect(fs.existsSync(fixture.sandbox.root)).toBe(true)
      expect(fs.readFileSync(evidence, 'utf8')).toBe('retain until exact owner exit is confirmed')
    } finally {
      vi.useRealTimers()
      await closeMockIfPresent(fixture)
      // The child is an in-memory fake; no real process owns this new sandbox.
      fixture.sandbox.cleanup()
    }
  })

  it.each(modes)('$label cleans its sandbox after confirmed process exit', async ({ setup }) => {
    vi.mocked(_electron.launch).mockResolvedValueOnce(fakeApp(true))
    const fixture = await setup()

    try {
      await fixture.cleanup()
      expect(fs.existsSync(fixture.sandbox.root)).toBe(false)

      if ('mockUrl' in fixture && typeof fixture.mockUrl === 'string') {await assertLoopbackListenerStopped(fixture.mockUrl)}
    } finally {
      await closeMockIfPresent(fixture)
      fixture.sandbox.cleanup()
    }
  })

  it('preserves a failed-start sandbox if its owned process also fails to stop', async () => {
    const existing = new Set(fs.readdirSync(os.tmpdir()).filter(name => name.startsWith('hermes-e2e-mock-')))
    vi.mocked(_electron.launch).mockResolvedValueOnce(fakeApp(false, true))
    let retained: string[] = []

    try {
      vi.useFakeTimers()
      const failure = setupMockBackend().then(() => undefined, (error: unknown) => error)
      await vi.runAllTimersAsync()
      const error = await failure
      expect(error).toBeInstanceOf(Error)
      expect((error as Error).message).toContain('did not exit after close')
      vi.useRealTimers()
      retained = fs.readdirSync(os.tmpdir()).filter(name => name.startsWith('hermes-e2e-mock-') && !existing.has(name))
      expect(retained).toHaveLength(1)
      expect(fs.existsSync(path.join(os.tmpdir(), retained[0], 'hermes-home', 'config.yaml'))).toBe(true)
    } finally {
      vi.useRealTimers()

      for (const name of retained) {
        removeOwnedUnitSandbox(name)
      }
    }
  })
})
