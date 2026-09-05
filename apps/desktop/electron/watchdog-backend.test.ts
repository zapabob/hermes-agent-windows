import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { afterEach, beforeEach, describe, test, vi } from 'vitest'

import { resolveWatchdogPrewarmedBackend } from './watchdog-backend'

describe('resolveWatchdogPrewarmedBackend', () => {
  let tmpDir = ''
  let previousLocalAppData: string | undefined

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-wd-'))
    previousLocalAppData = process.env.LOCALAPPDATA
    process.env.LOCALAPPDATA = tmpDir
  })

  afterEach(() => {
    if (previousLocalAppData === undefined) {
      delete process.env.LOCALAPPDATA
    } else {
      process.env.LOCALAPPDATA = previousLocalAppData
    }

    vi.unstubAllGlobals()
    fs.rmSync(tmpDir, { recursive: true, force: true })
  })

  test('returns null when manifest is missing', async () => {
    assert.equal(await resolveWatchdogPrewarmedBackend({ platform: 'win32' }), null)
  })

  test('returns connection when authenticated sessions probe succeeds', async () => {
    const manifestDir = path.join(tmpDir, 'HermesWatchdog')
    fs.mkdirSync(manifestDir, { recursive: true })
    fs.writeFileSync(
      path.join(manifestDir, 'desktop-backend.json'),
      JSON.stringify({
        baseUrl: 'http://127.0.0.1:54321',
        token: 'abc',
        port: 54321,
        hermesRoot: 'C:\\repo',
        managed: true
      })
    )

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      assert.match(url, /\/api\/sessions$/)
      assert.equal((init?.headers as Record<string, string>)?.Authorization, 'Bearer abc')

      return { ok: true }
    })

    vi.stubGlobal('fetch', fetchMock)

    const got = await resolveWatchdogPrewarmedBackend({
      hermesRoot: 'C:\\repo',
      platform: 'win32'
    })

    assert.ok(got)
    assert.equal(got?.baseUrl, 'http://127.0.0.1:54321')
    assert.equal(got?.token, 'abc')
    assert.equal(got?.source, 'watchdog')
    assert.equal(fetchMock.mock.calls.length, 1)
  })

  test('rejects when only public status would succeed but sessions auth fails', async () => {
    const manifestDir = path.join(tmpDir, 'HermesWatchdog')
    fs.mkdirSync(manifestDir, { recursive: true })
    fs.writeFileSync(
      path.join(manifestDir, 'desktop-backend.json'),
      JSON.stringify({
        baseUrl: 'http://127.0.0.1:54321',
        token: 'stale-token',
        port: 54321
      })
    )

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)

        if (url.endsWith('/api/status')) {
          return { ok: true }
        }

        return { ok: false, status: 401 }
      })
    )

    assert.equal(await resolveWatchdogPrewarmedBackend({ platform: 'win32' }), null)
  })

  test('rejects manifest when hermes root mismatches explicit override', async () => {
    const manifestDir = path.join(tmpDir, 'HermesWatchdog')
    fs.mkdirSync(manifestDir, { recursive: true })
    fs.writeFileSync(
      path.join(manifestDir, 'desktop-backend.json'),
      JSON.stringify({
        baseUrl: 'http://127.0.0.1:54321',
        token: 'abc',
        port: 54321,
        hermesRoot: 'C:\\other'
      })
    )

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true }))
    )

    assert.equal(await resolveWatchdogPrewarmedBackend({ hermesRoot: 'C:\\repo', platform: 'win32' }), null)
  })
})

test('production primary startup adopts the watchdog prewarmed backend before spawning', () => {
  const mainSource = fs.readFileSync(new URL('./main.ts', import.meta.url), 'utf8').replace(/\r\n/g, '\n')
  const startupStart = mainSource.indexOf('const setup = await runPrimaryBackendStartup({')
  const startupEnd = mainSource.indexOf('\n    })', startupStart)

  assert.notEqual(startupStart, -1, 'primary startup wiring must exist')
  assert.notEqual(startupEnd, -1, 'primary startup wiring must have a bounded options object')

  const startupOptions = mainSource.slice(startupStart, startupEnd)

  assert.match(mainSource, /import \{ resolveWatchdogPrewarmedBackend \} from '\.\/watchdog-backend'/)
  assert.match(startupOptions, /resolvePrewarmedLocal:\s*async/)
  assert.match(startupOptions, /resolveWatchdogPrewarmedBackend\(/)
  assert.match(startupOptions, /source:\s*'watchdog'/)
  assert.match(startupOptions, /waitForHermes\(prewarmed\.baseUrl, prewarmed\.token\)/)
})
