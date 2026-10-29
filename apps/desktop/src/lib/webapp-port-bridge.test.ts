import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type * as BrowserTransport from './browser-transport'

type WindowStub = {
  hermesDesktop?: unknown
  addEventListener: (...args: unknown[]) => void
  removeEventListener: (...args: unknown[]) => void
  localStorage: Storage
  location: Location & { origin: string; href: string; pathname: string }
  document: Document & { documentElement: { dataset: Record<string, string> } }
}

function ensureWindow(): WindowStub {
  const g = globalThis as { window?: WindowStub; document?: WindowStub['document'] }
  if (!g.window?.addEventListener) {
    const dataset: Record<string, string> = {}
    const document = { documentElement: { dataset } }
    const stub: WindowStub = {
      addEventListener() {},
      removeEventListener() {},
      localStorage: {
        getItem: () => null,
        setItem() {},
        removeItem() {},
        clear() {},
        key: () => null,
        length: 0,
      } as Storage,
      location: {
        origin: 'http://127.0.0.1:9120',
        href: 'http://127.0.0.1:9120/',
        pathname: '/',
      } as WindowStub['location'],
      document: document as unknown as WindowStub['document'],
    }
    g.window = stub
    g.document = stub.document
  }
  return g.window!
}

describe('webapp-port browser bridge install contract', () => {
  beforeEach(() => {
    ensureWindow()
    // eslint-disable-next-line @typescript-eslint/no-dynamic-delete
    delete ensureWindow().hermesDesktop
    vi.resetModules()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.resetModules()
    // eslint-disable-next-line @typescript-eslint/no-dynamic-delete
    delete ensureWindow().hermesDesktop
  })

  it('does not replace an existing Electron preload bridge', async () => {
    const preload = { api: vi.fn(), platform: 'electron' as const }
    ensureWindow().hermesDesktop = preload

    const { installBrowserDesktopBridge } = await import('./browser-desktop-bridge')
    const installed = installBrowserDesktopBridge()
    expect(installed).toBe(false)
    expect(ensureWindow().hermesDesktop).toBe(preload)
  }, 30_000)

  it('does not install when browser bootstrap is absent', async () => {
    vi.doMock('./browser-transport', async () => {
      const actual = await vi.importActual<typeof BrowserTransport>('./browser-transport')
      return {
        ...actual,
        browserBootstrap: () => null,
      }
    })
    const { installBrowserDesktopBridge } = await import('./browser-desktop-bridge')
    expect(installBrowserDesktopBridge()).toBe(false)
    expect(ensureWindow().hermesDesktop).toBeUndefined()
  }, 30_000)
})
