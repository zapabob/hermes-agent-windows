/**
 * The `ctx.files` contract for the Windows-native Desktop: how a grant is
 * minted, how a damaged grants record fails closed, how the protected set is
 * composed (Hermes home, every profile, the vault, userData), the explicit
 * list cap, and the Windows spellings of a path that must never leave a
 * granted folder. Junction fixtures need no elevation; file-symlink cases
 * live in the sibling suites behind `canLinkFiles`.
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { linkDir } from './fixtures/plugin-files-links'
import { createPluginFiles, type PluginFiles } from './plugin-files'
import { overlapsByIdentity } from './plugin-files-guards'
import { registerPluginFilesIpc } from './plugin-files-ipc'
import { pluginFilesProtectedRoots } from './plugin-files-roots'

const onWindows = process.platform === 'win32'

let scratch: string
let userData: string
let home: string
let hermesHome: string
let vault: string
let trashed: string[]

const make = (extra: Partial<Parameters<typeof createPluginFiles>[0]> = {}): PluginFiles =>
  createPluginFiles({
    userDataDir: () => userData,
    protectedRoots: () => pluginFilesProtectedRoots({ hermesHome, home }),
    trashItem: async target => {
      trashed.push(target)
      await fs.promises.rm(target, { recursive: true })
    },
    ...extra
  })

const grant = async (files: PluginFiles, pluginId = 'plexus', folder = vault): Promise<string> => {
  const granted = await files.addGrant(pluginId, folder)

  expect(granted).toMatchObject({ ok: true })

  return (granted as { folder: { id: string } }).folder.id
}

beforeEach(() => {
  scratch = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-plugin-files-contract-')))
  userData = path.join(scratch, 'userData')
  home = path.join(scratch, 'home')
  hermesHome = path.join(home, '.hermes')
  vault = path.join(home, 'Vault')
  fs.mkdirSync(userData, { recursive: true })
  fs.mkdirSync(path.join(hermesHome, 'profiles', 'coder'), { recursive: true })
  fs.mkdirSync(path.join(hermesHome, 'vault'), { recursive: true })
  fs.writeFileSync(path.join(hermesHome, 'profiles', 'coder', '.env'), 'KEY=secret\n')
  fs.mkdirSync(path.join(vault, 'notes'), { recursive: true })
  fs.writeFileSync(path.join(vault, 'notes', 'a.md'), '# A\n')
  trashed = []
})

afterEach(() => {
  vi.restoreAllMocks()
  fs.rmSync(scratch, { recursive: true, force: true })
})

describe('protected set composition', () => {
  it('names the home, each home spelling, profiles and vault, and the owner of a profile home', () => {
    const roots = pluginFilesProtectedRoots({
      hermesHome: path.join(home, '.hermes', 'profiles', 'coder'),
      home,
      localAppData: path.join(scratch, 'Local')
    })

    for (const base of [path.join(home, '.hermes'), path.join(scratch, 'Local', 'hermes')]) {
      expect(roots).toEqual(expect.arrayContaining([base, path.join(base, 'profiles'), path.join(base, 'vault')]))
    }

    expect(roots).toContain(path.join(home, '.hermes', 'profiles', 'coder'))
    expect(new Set(roots).size).toBe(roots.length)
  })

  it.each([
    ['the Hermes home', () => hermesHome],
    ['the profiles tree', () => path.join(hermesHome, 'profiles')],
    ['one profile', () => path.join(hermesHome, 'profiles', 'coder')],
    ['the vault folder', () => path.join(hermesHome, 'vault')],
    ['a folder that holds the Hermes home', () => home],
    ['the app userData folder', () => userData],
    ['a plugin data folder under userData', () => path.join(userData, 'plugin-files')]
  ])('refuses to grant %s', async (_label, pick) => {
    fs.mkdirSync(pick(), { recursive: true })

    expect(await make().addGrant('plexus', pick())).toMatchObject({ ok: false, error: 'protected' })
  })

  it('a Desktop pointed at a profile home still protects the root and sibling profiles', async () => {
    const files = make({
      protectedRoots: () => pluginFilesProtectedRoots({ hermesHome: path.join(hermesHome, 'profiles', 'coder'), home })
    })

    fs.mkdirSync(path.join(hermesHome, 'profiles', 'other'), { recursive: true })

    for (const folder of [hermesHome, path.join(hermesHome, 'profiles', 'other')]) {
      expect(await files.addGrant('plexus', folder)).toMatchObject({ ok: false, error: 'protected' })
    }
  })

  it('no op reaches the vault or a profile through a granted parent that was grantable before', async () => {
    const files = make()
    const id = await grant(files)

    for (const rel of ['../.hermes/vault', '../.hermes/profiles/coder/.env']) {
      expect(await files.run('plexus', { op: 'readText', folder: id, path: rel })).toMatchObject({
        ok: false,
        error: 'invalid-path'
      })
    }
  })
})

describe('a damaged grants record fails closed', () => {
  const record = () => path.join(userData, 'plugin-files', 'grants.json')

  const plant = (content: string) => {
    fs.mkdirSync(path.dirname(record()), { recursive: true })
    fs.writeFileSync(record(), content)
  }

  it.each([
    ['text that is not JSON', 'not json {'],
    ['a JSON null', 'null'],
    ['an array', '[]'],
    ['grants of the wrong shape', JSON.stringify({ grants: { plexus: 'oops' } })],
    ['rows that are not objects', JSON.stringify({ grants: { plexus: [null, 3, 'x'] } })],
    [
      'a row with a bad id',
      JSON.stringify({ grants: { plexus: [{ id: '../../x', name: 'v', path: '/', grantedAt: 'now' }] } })
    ],
    [
      'a row with a relative path',
      JSON.stringify({ grants: { plexus: [{ id: 'a'.repeat(16), name: 'v', path: 'vault', grantedAt: 'now' }] } })
    ]
  ])('treats %s as no grants and refuses use of its ids', async (_label, content) => {
    plant(content)
    const files = make()

    expect(await files.grants('plexus')).toEqual([])
    expect(await files.run('plexus', { op: 'list', folder: 'a'.repeat(16), path: '' })).toMatchObject({
      ok: false,
      error: 'not-granted'
    })
  })

  it('a good row survives beside a bad one and a fresh grant still works', async () => {
    const good = { id: 'b'.repeat(16), name: 'Vault', path: vault, grantedAt: '2026-10-28T00:00:00.000Z' }
    plant(JSON.stringify({ grants: { plexus: [null, good] } }))
    const files = make()

    expect((await files.grants('plexus')).map(row => row.id)).toEqual([good.id])
    expect(await files.run('plexus', { op: 'list', folder: good.id, path: '' })).toMatchObject({ ok: true })
    expect(await files.addGrant('plexus', path.join(home, 'Other'))).toMatchObject({ ok: false })
  })

  it('a grant of a folder that no longer exists is refused, not followed', async () => {
    const files = make()
    const id = await grant(files)
    fs.rmSync(vault, { recursive: true })

    expect(await files.run('plexus', { op: 'list', folder: id, path: '' })).toMatchObject({
      ok: false,
      error: 'folder-missing'
    })
  })
})

describe('listings are capped with an explicit error', () => {
  it('lists exactly the cap, refuses one more, and never returns a shortened list', async () => {
    const files = make({ listMaxEntries: 3 })
    const id = await grant(files)
    const crowd = path.join(vault, 'crowd')
    fs.mkdirSync(crowd)

    for (const name of ['a', 'b', 'c']) {
      fs.writeFileSync(path.join(crowd, name), name)
    }

    const full = await files.run('plexus', { op: 'list', folder: id, path: 'crowd' })

    expect(full).toMatchObject({ ok: true })
    expect((full as unknown as { entries: unknown[] }).entries).toHaveLength(3)

    fs.writeFileSync(path.join(crowd, 'd'), 'd')
    const over = await files.run('plexus', { op: 'list', folder: id, path: 'crowd' })

    expect(over).toMatchObject({ ok: false, error: 'too-large' })
    expect(over).not.toHaveProperty('entries')
  })
})

describe('a grant is minted only by the native picker', () => {
  const handlers = new Map<string, (...args: unknown[]) => Promise<unknown>>()
  let picked: { canceled: boolean; filePaths: string[] }
  let ipcFiles: PluginFiles

  beforeEach(() => {
    handlers.clear()
    picked = { canceled: true, filePaths: [] }
    ipcFiles = registerPluginFilesIpc({
      ipcMain: { handle: (channel: string, handler: never) => handlers.set(channel, handler) } as never,
      dialog: { showOpenDialog: async () => picked } as never,
      windowFor: () => null,
      broadcastChange: () => undefined,
      userDataDir: () => userData,
      hermesHomes: () => pluginFilesProtectedRoots({ hermesHome, home }),
      trashItem: async () => undefined
    })
  })

  const call = (channel: string, ...args: unknown[]) => handlers.get(channel)!({ sender: {} }, ...args)

  it('exposes request/grants/revoke/op and no channel that registers a path', () => {
    expect([...handlers.keys()].sort()).toEqual([
      'hermes:pluginFiles:grants',
      'hermes:pluginFiles:op',
      'hermes:pluginFiles:request',
      'hermes:pluginFiles:revoke'
    ])
  })

  it('ignores a path smuggled in through the labels: a cancelled picker grants nothing', async () => {
    const smuggled = { title: 't', buttonLabel: 'b', path: vault, folder: vault, picked: vault, filePaths: [vault] }

    expect(await call('hermes:pluginFiles:request', 'plexus', smuggled)).toEqual({ ok: true, folder: null })
    expect(await ipcFiles.grants('plexus')).toEqual([])
  })

  it('an op cannot carry an absolute path in place of a handle', async () => {
    for (const folder of [vault, 'data/../x', 'C:\\Windows', '\\\\server\\share']) {
      expect(await call('hermes:pluginFiles:op', 'plexus', { op: 'list', folder, path: '' })).toMatchObject({
        ok: false,
        error: 'not-granted'
      })
    }
  })

  it('what the user picks is granted to the asking plugin only', async () => {
    picked = { canceled: false, filePaths: [vault] }
    const result = (await call('hermes:pluginFiles:request', 'plexus')) as { folder: { id: string } }

    expect(
      await call('hermes:pluginFiles:op', 'plexus', { op: 'list', folder: result.folder.id, path: '' })
    ).toMatchObject({
      ok: true
    })
    expect(
      await call('hermes:pluginFiles:op', 'other', { op: 'list', folder: result.folder.id, path: '' })
    ).toMatchObject({
      ok: false,
      error: 'not-granted'
    })
  })
})

describe('Windows path spellings never leave the folder', () => {
  // Pure input -> output: the platform is data to the path rules, not a faked host.
  it.each([
    ['an absolute drive path', 'C:\\Windows\\win.ini'],
    ['a drive-relative path', 'C:win.ini'],
    ['a rooted path', '\\Windows\\win.ini'],
    ['a UNC path', '\\\\server\\share\\x.txt'],
    ['an extended-length path', '\\\\?\\C:\\Windows\\win.ini'],
    ['a device namespace path', '\\\\.\\PhysicalDrive0'],
    ['a POSIX absolute path', '/etc/passwd'],
    ['traversal with backslashes', 'notes\\..\\..\\x'],
    ['traversal with a trailing space', '.. /x'],
    ['an NTFS stream', 'notes\\a.md:secret'],
    ['the default data stream', 'notes\\a.md::$DATA'],
    ['a reserved device name', 'NUL'],
    ['a reserved name with an extension', 'notes/aux.txt'],
    ['a superscript device name', 'lpt\u00b2'],
    ['a trailing dot', 'notes/a.md.'],
    ['a trailing space', 'notes/a.md '],
    ['a NUL byte', 'notes/a.md\0.txt']
  ])('refuses %s', async (_label, rel) => {
    const files = make({ platform: 'win32' })
    const id = await grant(files)

    for (const op of ['stat', 'readText', 'list'] as const) {
      expect(await files.run('plexus', { op, folder: id, path: rel })).toMatchObject({
        ok: false,
        error: 'invalid-path'
      })
    }

    expect(await files.run('plexus', { op: 'writeText', folder: id, path: rel, text: 'x' })).toMatchObject({
      ok: false,
      error: 'invalid-path'
    })
  })
})

describe.runIf(onWindows)('on a Windows host', () => {
  it('refuses a junction as the grant root when it resolves into the Hermes home', async () => {
    const link = path.join(home, 'innocent')
    linkDir(hermesHome, link)

    expect(await make().addGrant('plexus', link)).toMatchObject({ ok: false, error: 'protected' })
  })

  it('a granted folder replaced by a junction into another tree must be granted again', async () => {
    const files = make()
    const id = await grant(files)
    const elsewhere = path.join(home, 'Elsewhere')
    fs.mkdirSync(elsewhere)
    fs.writeFileSync(path.join(elsewhere, 'leak.txt'), 'not granted')
    fs.renameSync(vault, path.join(home, 'Vault-old'))
    linkDir(elsewhere, vault)

    const read = await files.run('plexus', { op: 'readText', folder: id, path: 'leak.txt' })

    expect(read).toMatchObject({ ok: false, error: 'folder-changed' })
    expect(JSON.stringify(read)).not.toContain('not granted')
  })

  it('a junction inside the folder that leaves it is refused for reads, writes, rename and trash', async () => {
    const files = make()
    const id = await grant(files)
    const elsewhere = path.join(home, 'Elsewhere')
    fs.mkdirSync(elsewhere)
    fs.writeFileSync(path.join(elsewhere, 'leak.txt'), 'not granted')
    linkDir(elsewhere, path.join(vault, 'door'))

    for (const request of [
      { op: 'readText', path: 'door/leak.txt' },
      { op: 'writeText', path: 'door/new.txt', text: 'x' },
      { op: 'rename', path: 'door/leak.txt', name: 'moved.txt' },
      { op: 'trash', path: 'door/leak.txt' },
      { op: 'list', path: 'door' }
    ] as const) {
      expect(await files.run('plexus', { ...request, folder: id } as never)).toMatchObject({
        ok: false,
        error: 'outside-folder'
      })
    }

    expect(fs.readFileSync(path.join(elsewhere, 'leak.txt'), 'utf8')).toBe('not granted')
    expect(fs.existsSync(path.join(elsewhere, 'new.txt'))).toBe(false)
    expect(trashed).toEqual([])
  })

  it('a differently-cased spelling of the Hermes home or of a key file is still refused', async () => {
    const files = make()
    const id = await grant(files)
    fs.writeFileSync(path.join(vault, '.env'), 'KEY=secret\n')

    expect(await files.addGrant('plexus', hermesHome.toUpperCase())).toMatchObject({ ok: false, error: 'protected' })
    expect(await files.addGrant('plexus', path.join(hermesHome, 'PROFILES').toLowerCase())).toMatchObject({
      ok: false,
      error: 'protected'
    })
    expect(await files.run('plexus', { op: 'readText', folder: id, path: '.ENV' })).toMatchObject({
      ok: false,
      error: 'sensitive-file'
    })
  })

  it('a real NTFS stream name is refused before the filesystem sees it', async () => {
    const files = make()
    const id = await grant(files)

    expect(
      await files.run('plexus', { op: 'writeText', folder: id, path: 'notes/a.md:hidden', text: 'x' })
    ).toMatchObject({
      ok: false,
      error: 'invalid-path'
    })
    expect(await files.run('plexus', { op: 'readText', folder: id, path: 'notes/a.md::$DATA' })).toMatchObject({
      ok: false,
      error: 'invalid-path'
    })
  })

  it('works with spaces and Japanese names across every operation', async () => {
    const folder = path.join(home, '日本語 フォルダ')
    fs.mkdirSync(path.join(folder, 'メモ 帳'), { recursive: true })
    const files = make()
    const id = await grant(files, 'plexus', folder)

    expect(
      await files.run('plexus', { op: 'writeText', folder: id, path: 'メモ 帳/日記 1.txt', text: 'こんにちは' })
    ).toMatchObject({ ok: true, path: 'メモ 帳/日記 1.txt' })
    expect(await files.run('plexus', { op: 'readText', folder: id, path: 'メモ 帳/日記 1.txt' })).toMatchObject({
      ok: true,
      text: 'こんにちは'
    })
    expect(await files.run('plexus', { op: 'list', folder: id, path: 'メモ 帳' })).toMatchObject({
      ok: true,
      entries: [{ name: '日記 1.txt', path: 'メモ 帳/日記 1.txt', isDirectory: false }]
    })
    expect(
      await files.run('plexus', { op: 'rename', folder: id, path: 'メモ 帳/日記 1.txt', name: '日記 2.txt' })
    ).toEqual({
      ok: true,
      path: 'メモ 帳/日記 2.txt'
    })
    expect(await files.run('plexus', { op: 'trash', folder: id, path: 'メモ 帳/日記 2.txt' })).toEqual({ ok: true })
    // CI Windows may surface long paths while the fixture still holds 8.3.
    expect(trashed.map(entry => fs.realpathSync.native(entry).toLowerCase())).toEqual([
      fs.realpathSync.native(path.join(folder, 'メモ 帳', '日記 2.txt')).toLowerCase()
    ])
  })
})

describe('file identity is exact (NTFS ids exceed 2^53)', () => {
  // Number-typed inodes round above 2^53, so two different folders could look
  // like one (a false `protected`) or a swapped file could look unchanged.
  it('tells two folders apart whose ids differ only below double precision', async () => {
    const a = path.join(scratch, 'id-a')
    const b = path.join(scratch, 'id-b')
    fs.mkdirSync(a)
    fs.mkdirSync(b)

    const original = fs.promises.stat.bind(fs.promises) as (
      target: fs.PathLike,
      options?: { bigint: true }
    ) => Promise<fs.BigIntStats>

    const forced = new Map([
      [a, 2n ** 60n + 1n],
      [b, 2n ** 60n + 2n]
    ])

    vi.spyOn(fs.promises, 'stat').mockImplementation((async (target: fs.PathLike, options?: { bigint: true }) => {
      const real = await original(target, options)
      const ino = forced.get(String(target))

      return ino === undefined
        ? real
        : Object.assign(Object.create(Object.getPrototypeOf(real)), real, { dev: 7n, ino })
    }) as never)

    expect(Number(2n ** 60n + 1n)).toBe(Number(2n ** 60n + 2n))
    expect(await overlapsByIdentity(a, [b])).toBe(false)
    expect(await overlapsByIdentity(a, [a])).toBe(true)
    vi.restoreAllMocks()
  })

  it('stat and write report plain numbers for size and mtime', async () => {
    const files = make()
    const id = await grant(files)

    expect(await files.run('plexus', { op: 'writeText', folder: id, path: 'n.txt', text: 'abc' })).toMatchObject({
      ok: true,
      size: 3,
      mtimeMs: expect.any(Number)
    })
    expect(await files.run('plexus', { op: 'stat', folder: id, path: 'n.txt' })).toMatchObject({
      exists: true,
      size: 3,
      mtimeMs: expect.any(Number)
    })
    expect(await files.run('plexus', { op: 'readText', folder: id, path: 'n.txt' })).toMatchObject({
      size: 3,
      mtimeMs: expect.any(Number)
    })
  })
})
