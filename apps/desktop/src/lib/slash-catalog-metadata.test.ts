import { afterEach, describe, expect, it } from 'vitest'

import { desktopSlashCommandArgumentMode, resolveDesktopCommand } from './desktop-slash-commands'
import { queryClient } from './query-client'
import { cachedSlashCompletion, hasCachedSlashCompletion, invalidateSlashCompletions, peekCachedSlashCompletion } from './slash-completion-cache'

afterEach(() => queryClient.clear())

describe('catalog argument metadata', () => {
  it('uses validated live metadata for a command without a local spec', async () => {
    await cachedSlashCompletion('catalog', async () => ({ commands: {
      '/draft-note': { argument_mode: 'text' }, '/finite-fixture': { argument_mode: 'options' },
      '/mixed-fixture': { argument_mode: 'mixed' }, '/broken': { argument_mode: 'invalid' }
    } }))
    expect(desktopSlashCommandArgumentMode('/draft-note')).toBe('text')
    expect(desktopSlashCommandArgumentMode('/finite-fixture')).toBe('options')
    expect(desktopSlashCommandArgumentMode('/mixed-fixture')).toBe('mixed')
    expect(desktopSlashCommandArgumentMode('/broken')).toBeNull()
    expect(desktopSlashCommandArgumentMode('/absent')).toBeNull()
  })

  it('keeps every local surface authoritative, even without an explicit mode', async () => {
    await cachedSlashCompletion('catalog', async () => ({ commands: {
      '/resume': { argument_mode: 'options' }, '/model': { argument_mode: 'text' },
      '/new': { argument_mode: 'text' }, '/save': { argument_mode: 'text' }
    } }))
    expect(desktopSlashCommandArgumentMode('/resume')).toBe('mixed')
    expect(desktopSlashCommandArgumentMode('/model')).toBeNull()
    expect(desktopSlashCommandArgumentMode('/new')).toBeNull()
    expect(desktopSlashCommandArgumentMode('/save')).toBeNull()
    expect(resolveDesktopCommand('/model')?.surface).toEqual({ kind: 'picker', picker: 'model' })
    expect(resolveDesktopCommand('/save')?.surface.kind).toBe('rpc')
  })

  it('falls back for older and malformed catalogs', async () => {
    for (const catalog of [{ pairs: [] }, { commands: null }, { commands: { '/draft-note': null } }]) {
      queryClient.clear()
      await cachedSlashCompletion('catalog', async () => catalog)
      expect(desktopSlashCommandArgumentMode('/draft-note')).toBeNull()
    }
  })

  it('keeps registry arguments editable on existing exec surfaces without changing their dispatch', async () => {
    await cachedSlashCompletion('catalog', async () => ({ commands: {
      '/rollback': { argument_mode: 'text' }, '/undo': { argument_mode: 'text' }
    } }))
    expect(desktopSlashCommandArgumentMode('/rollback')).toBe('text')
    expect(desktopSlashCommandArgumentMode('/undo')).toBe('text')
    expect(resolveDesktopCommand('/rollback')?.surface).toEqual({ kind: 'exec' })
    expect(resolveDesktopCommand('/undo')?.surface).toEqual({ kind: 'exec' })
  })

  it('does not expose a catalog after invalidation', async () => {
    await cachedSlashCompletion('catalog', async () => ({ commands: { '/draft-note': { argument_mode: 'text' } } }))
    invalidateSlashCompletions()
    expect(hasCachedSlashCompletion('catalog')).toBe(false)
    expect(peekCachedSlashCompletion('catalog')).toBeUndefined()
    expect(desktopSlashCommandArgumentMode('/draft-note')).toBeNull()
  })

  it('does not let an obsolete pending response repopulate an invalidated catalog', async () => {
    let finish!: (value: object) => void
    const pending = cachedSlashCompletion('catalog', () => new Promise<object>(resolve => { finish = resolve }))
    const settled = pending.catch(() => undefined)
    invalidateSlashCompletions()
    finish({ commands: { '/draft-note': { argument_mode: 'text' } } })
    await settled
    expect(peekCachedSlashCompletion('catalog')).toBeUndefined()
    await cachedSlashCompletion('catalog', async () => ({ commands: { '/replacement': { argument_mode: 'mixed' } } }))
    expect(desktopSlashCommandArgumentMode('/replacement')).toBe('mixed')
    expect(desktopSlashCommandArgumentMode('/draft-note')).toBeNull()
  })

  it('rejects a cancelled refetch instead of delivering its reverted old catalog', async () => {
    await cachedSlashCompletion('catalog', async () => ({ commands: { '/old': { argument_mode: 'text' } } }))
    await queryClient.invalidateQueries({ queryKey: ['slash-completions', 'catalog'] })
    let finish!: (value: object) => void
    const pending = cachedSlashCompletion('catalog', () => new Promise<object>(resolve => { finish = resolve }))
    const settled = pending.then(() => 'delivered obsolete catalog', () => 'cancelled')
    invalidateSlashCompletions()
    finish({ commands: { '/late': { argument_mode: 'text' } } })
    expect(await settled).toBe('cancelled')
    expect(peekCachedSlashCompletion('catalog')).toBeUndefined()
  })
})
