import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'

import { $connection } from '@/store/session'

import { ArtifactsView } from './index'

// Host installs of @icons-pack can miss individual icon modules while the
// package barrel still exports them — aborting this suite on import. Stub the
// barrel for unit tests only (same pattern as use-desktop-integrations).
vi.mock('@icons-pack/react-simple-icons', () => {
  const icon = () => null
  const target: Record<string, unknown> = { __esModule: true }

  return new Proxy(target, {
    get(t, prop) {
      if (prop === '__esModule') {return true}

      if (prop === 'then') {return undefined}

      if (typeof prop === 'string' && prop.endsWith('Hex')) {return '#000000'}

      if (typeof prop === 'string') {
        if (!(prop in t)) {t[prop] = icon}

        return t[prop]
      }

      return undefined
    },
    has: () => true,
    getOwnPropertyDescriptor(t, prop) {
      if (typeof prop !== 'string') {return undefined}

      if (!(prop in t)) {t[prop] = prop === '__esModule' ? true : icon}

      return { configurable: true, enumerable: true, writable: true, value: t[prop] }
    },
    ownKeys(t) {
      return Reflect.ownKeys(t)
    },
  })
})

const paths = vi.hoisted(() => [
  '~/.hermes/memories/USER.md',
  './report.md',
  '../parent.md',
  String.raw`~\home.txt`,
  String.raw`.\child.txt`,
  String.raw`..\ancestor.txt`,
  'file:///C:/output/drive.txt',
  '/srv/absolute.txt'
])

vi.mock('@/hermes', async () => ({
  ...(await vi.importActual('@/hermes')),
  listAllProfileSessions: async () => ({
    sessions: [{ id: 'artifact-session', title: 'Fixture', profile: 'origin-profile' }]
  }),
  getAllSessionMessages: async () => ({
    messages: [
      {
        role: 'assistant',
        timestamp: 1000,
        content: paths.map(path => `MEDIA:${path}`).join(' ') + ' https://example.com/report.txt'
      }
    ]
  })
}))

afterEach(() => {
  cleanup()
  $connection.set(null)
  vi.unstubAllGlobals()
})

it('keeps discovered file paths and originating session scope intact through remote opening', async () => {
  const saveGatewayFile = vi.fn().mockResolvedValue({ saved: true })
  const openExternal = vi.fn()
  vi.stubGlobal('hermesDesktop', { saveGatewayFile, openExternal })
  $connection.set({
    isFullscreen: false,
    nativeOverlayWidth: 0,
    logs: [],
    windowButtonPosition: null,
    mode: 'remote',
    connectionId: 'remote-fixture',
    profile: 'writer',
    baseUrl: 'http://localhost',
    token: '',
    wsUrl: ''
  })
  render(
    <MemoryRouter>
      <ArtifactsView />
    </MemoryRouter>
  )

  for (const name of [
    'USER.md',
    'report.md',
    'parent.md',
    'home.txt',
    'child.txt',
    'ancestor.txt',
    'drive.txt',
    'absolute.txt'
  ]) {
    fireEvent.click(await screen.findByRole('button', { name }))
  }

  await waitFor(() => expect(saveGatewayFile).toHaveBeenCalledTimes(paths.length))
  expect(saveGatewayFile.mock.calls.map(([request]) => request)).toEqual(
    paths.map(path => ({
      connectionId: 'remote-fixture',
      profile: 'origin-profile',
      sessionId: 'artifact-session',
      path,
      suggestedName: path.split(/[\\/]/).pop()
    }))
  )
  expect(screen.getByRole('link').getAttribute('href')).toBe('https://example.com/report.txt')
  expect(openExternal).not.toHaveBeenCalled()
})
