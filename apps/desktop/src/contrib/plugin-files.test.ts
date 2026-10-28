import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getRuntimeI18nLocale, setRuntimeI18nLocale } from '@/i18n/runtime'
import { notify } from '@/store/notifications'

import { createPluginContext } from './plugin'
import { revokeGrantsIfUninstalled } from './plugin-files'
import { $pluginRecords, type PluginRecord } from './plugins-store'

vi.mock('@/store/notifications', () => ({ notify: vi.fn(), notifyError: vi.fn() }))

const door = {
  grants: vi.fn(async () => []),
  op: vi.fn(async () => ({ ok: true, text: 'hi' })),
  request: vi.fn(),
  revoke: vi.fn(async () => ({ ok: true, removed: 1 }))
}

beforeEach(() => {
  ;(window as unknown as { hermesDesktop: unknown }).hermesDesktop = { pluginFiles: door }
})

afterEach(() => {
  vi.clearAllMocks()
  delete (window as unknown as { hermesDesktop?: unknown }).hermesDesktop
})

describe('ctx.files', () => {
  it("always names the calling plugin and asks with the app's own picker copy", async () => {
    door.request.mockResolvedValueOnce({ ok: true, folder: { grantedAt: 'x', id: 'f1', name: 'Vault', path: '/v' } })
    const files = createPluginContext('plexus').files

    expect(await files.requestFolder()).toEqual({ ok: true, folder: { id: 'f1', name: 'Vault', path: '/v' } })
    expect(door.request).toHaveBeenCalledWith('plexus', {
      buttonLabel: 'Allow access',
      title: 'Choose a folder for plexus'
    })

    await files.readText('f1', 'notes/a.md')
    expect(door.op).toHaveBeenCalledWith('plexus', { op: 'readText', folder: 'f1', path: 'notes/a.md' })
  })

  it('tells the user when the app refuses the folder they picked', async () => {
    door.request.mockResolvedValueOnce({ ok: false, error: 'protected', message: 'no' })

    expect(await createPluginContext('plexus').files.requestFolder()).toMatchObject({ ok: false, error: 'protected' })
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({ kind: 'warning' }))
  })

  it('answers unavailable on a shell without the door instead of throwing', async () => {
    delete (window as unknown as { hermesDesktop?: unknown }).hermesDesktop
    const files = createPluginContext('plexus').files

    expect(await files.requestFolder()).toMatchObject({ ok: false, error: 'unavailable' })
    expect(await files.list('data')).toMatchObject({ ok: false, error: 'unavailable' })
    expect(await files.folders()).toEqual([])
  })
})

describe('grants after a package removal', () => {
  afterEach(() => $pluginRecords.set({}))

  it('keeps the grants of a desktop plugin another profile still installs', async () => {
    $pluginRecords.set({ plexus: { id: 'plexus' } as PluginRecord })

    expect(await revokeGrantsIfUninstalled('plexus')).toBe(false)
    expect(door.revoke).not.toHaveBeenCalled()
  })

  it('drops the grants once the desktop plugin is gone', async () => {
    expect(await revokeGrantsIfUninstalled('plexus')).toBe(true)
    expect(door.revoke).toHaveBeenCalledWith('plexus')
  })

  it('a revoke that fails is reported, not counted as done', async () => {
    door.revoke.mockRejectedValueOnce(new Error('EACCES: grants.json'))

    await expect(revokeGrantsIfUninstalled('plexus')).rejects.toThrow('EACCES')
  })
})

describe('the door is the only way in', () => {
  it('never falls back to the generic file bridge when the plugin door is missing', async () => {
    const generic = {
      readDir: vi.fn(),
      renamePath: vi.fn(),
      trashPath: vi.fn(),
      writeTextFile: vi.fn()
    }

    ;(window as unknown as { hermesDesktop: unknown }).hermesDesktop = generic
    const files = createPluginContext('plexus').files

    expect(await files.writeText('data', 'a.txt', 'x')).toMatchObject({ ok: false, error: 'unavailable' })
    expect(await files.rename('data', 'a.txt', 'b.txt')).toMatchObject({ ok: false, error: 'unavailable' })
    expect(await files.trash('data', 'a.txt')).toMatchObject({ ok: false, error: 'unavailable' })
    expect(await files.list('data')).toMatchObject({ ok: false, error: 'unavailable' })

    for (const fn of Object.values(generic)) {
      expect(fn).not.toHaveBeenCalled()
    }
  })

  it('exposes the full contract surface on ctx.files', () => {
    const files = createPluginContext('plexus').files

    expect(files.dataFolder).toBe('data')

    for (const member of [
      'requestFolder',
      'folders',
      'release',
      'list',
      'stat',
      'readText',
      'readDataUrl',
      'writeText',
      'rename',
      'trash'
    ] as const) {
      expect(typeof files[member]).toBe('function')
    }
  })

  it('turns a bridge that throws into a structured error, never a rejection', async () => {
    door.op.mockRejectedValueOnce(new Error('ipc closed'))

    expect(await createPluginContext('plexus').files.readText('data', 'a.txt')).toEqual({
      ok: false,
      error: 'io-error',
      message: 'ipc closed'
    })
  })

  it('a writeText call carries only a handle, a relative path and the exclusive flag', async () => {
    await createPluginContext('plexus').files.writeText('f1', 'notes/a.md', 'hi', { exclusive: true })

    expect(door.op).toHaveBeenCalledWith('plexus', {
      op: 'writeText',
      folder: 'f1',
      path: 'notes/a.md',
      text: 'hi',
      exclusive: true
    })
  })
})

describe('picker copy follows the app locale', () => {
  const previous = getRuntimeI18nLocale()

  afterEach(() => setRuntimeI18nLocale(previous))

  it('uses Japanese copy under ja and English for a locale without its own copy', async () => {
    door.request.mockResolvedValue({ ok: true, folder: null })
    setRuntimeI18nLocale('ja')
    await createPluginContext('plexus').files.requestFolder()
    expect(door.request).toHaveBeenLastCalledWith('plexus', expect.objectContaining({ buttonLabel: 'アクセスを許可' }))

    setRuntimeI18nLocale('zh')
    await createPluginContext('plexus').files.requestFolder()
    expect(door.request).toHaveBeenLastCalledWith('plexus', expect.objectContaining({ buttonLabel: 'Allow access' }))
  })
})
