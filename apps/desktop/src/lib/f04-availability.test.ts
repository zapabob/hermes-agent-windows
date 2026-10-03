import { afterEach, describe, expect, it } from 'vitest'

import { $activeGatewayProfile } from '@/store/profile'

import {
  canonicalDesktopSlashCommand,
  type CommandsCatalogLike,
  desktopSlashCommandArgumentMode,
  desktopSlashUnavailableMessage,
  filterDesktopCommandsCatalog,
  isDesktopSlashCommand,
  isDesktopSlashExtensionCommand,
  isDesktopSlashSuggestion,
  resolveDesktopCommand
} from './desktop-slash-commands'
import { queryClient } from './query-client'
import { invalidateSlashCompletions } from './slash-completion-cache'

const fixture = (): CommandsCatalogLike =>
  ({
    canon: { '/f04-alias': '/f04-hidden' },
    pairs: [
      '/f04-offered',
      '/f04-hidden',
      '/f04-terminal',
      '/f04-messaging',
      '/f04-advanced',
      '/f04-settings',
      '/f04-voice'
    ].map(n => [n, n]),
    commands: {
      '/f04-offered': { argument_mode: 'text', desktop: null },
      '/f04-hidden': { argument_mode: 'mixed', desktop: 'hidden' },
      '/f04-alias': { argument_mode: 'mixed', desktop: 'hidden' },
      '/f04-terminal': { desktop: 'terminal' },
      '/f04-messaging': { desktop: 'messaging' },
      '/f04-advanced': { desktop: 'advanced' },
      '/f04-settings': { desktop: 'settings' },
      '/f04-voice': { desktop: 'composer-voice' }
    }
  }) as CommandsCatalogLike

const warm = (catalog = fixture()) => queryClient.setQueryData(['slash-completions', 'catalog'], catalog)
afterEach(() => queryClient.clear())

describe('F04b availability', () => {
  it('filters a cold public help catalog without needing a prior completion request', () => {
    expect(filterDesktopCommandsCatalog(fixture()).pairs?.map(p => p[0])).toEqual(['/f04-offered'])
  })
  it('offers a registry builtin as exec rather than a skill', () => {
    warm()
    expect(resolveDesktopCommand('/f04-offered')?.surface).toEqual({ kind: 'exec' })
    expect(isDesktopSlashExtensionCommand('/f04-offered')).toBe(false)
    expect(isDesktopSlashSuggestion('/f04-offered')).toBe(true)
    expect(desktopSlashCommandArgumentMode('/f04-offered')).toBe('text')
  })
  it('hides discovery without disabling explicitly typed execution', () => {
    warm()
    expect(isDesktopSlashSuggestion('/f04-hidden')).toBe(false)
    expect(isDesktopSlashCommand('/f04-hidden words')).toBe(true)
    expect(resolveDesktopCommand('/f04-hidden')?.hidden).toBe(true)
    expect(desktopSlashUnavailableMessage('/f04-hidden')).toBeNull()
    expect(desktopSlashCommandArgumentMode('/f04-hidden')).toBe('mixed')
  })
  it.each(['terminal', 'messaging', 'advanced', 'settings', 'composer-voice'] as const)(
    'keeps %s unavailable with the existing reason',
    reason => {
      warm()
      const command = reason === 'composer-voice' ? '/f04-voice' : `/f04-${reason}`
      expect(resolveDesktopCommand(command)?.surface).toEqual({ kind: 'unavailable', reason })
      expect(isDesktopSlashCommand(command)).toBe(false)
      expect(isDesktopSlashSuggestion(command)).toBe(false)
      expect(desktopSlashUnavailableMessage(command)).toBeTruthy()
    }
  )
  it('uses registry alias identity and preserves its hidden status', () => {
    warm()
    expect(canonicalDesktopSlashCommand(' /F04-ALIAS arg')).toBe('/f04-hidden')
    expect(isDesktopSlashSuggestion('/f04-alias')).toBe(false)
    expect(isDesktopSlashCommand('/f04-alias')).toBe(true)
  })
  it('retains local action picker RPC and unavailable priorities over conflicting metadata', () => {
    warm({
      commands: Object.fromEntries(
        ['/model', '/resume', '/new', '/save', '/approve', '/reasoning'].map(n => [
          n,
          { desktop: n === '/approve' || n === '/reasoning' ? null : 'terminal', argument_mode: 'text' }
        ])
      )
    } as CommandsCatalogLike)
    expect(resolveDesktopCommand('/model')?.surface).toEqual({ kind: 'picker', picker: 'model' })
    expect(resolveDesktopCommand('/resume')?.surface).toEqual({ kind: 'picker', picker: 'session' })
    expect(resolveDesktopCommand('/new')?.surface).toEqual({ kind: 'action', action: 'new' })
    expect(resolveDesktopCommand('/save')?.surface.kind).toBe('rpc')
    expect(isDesktopSlashCommand('/approve')).toBe(false)
    expect(isDesktopSlashCommand('/reasoning')).toBe(false)
    expect(desktopSlashCommandArgumentMode('/model')).toBeNull()
    expect(desktopSlashCommandArgumentMode('/resume')).toBe('mixed')
  })
  it('drops availability and alias metadata on invalidation', () => {
    warm()
    expect(isDesktopSlashCommand('/f04-terminal')).toBe(false)
    invalidateSlashCompletions()
    expect(resolveDesktopCommand('/f04-terminal')).toBeNull()
    expect(canonicalDesktopSlashCommand('/f04-alias')).toBe('/f04-alias')
  })
  it('drops the previous profile catalog', () => {
    $activeGatewayProfile.set('f04-one')
    warm()
    expect(isDesktopSlashSuggestion('/f04-hidden')).toBe(false)
    $activeGatewayProfile.set('f04-two')
    expect(resolveDesktopCommand('/f04-hidden')).toBeNull()
    $activeGatewayProfile.set('default')
  })
  it('preserves legacy and malformed metadata fallback without throwing', () => {
    warm({ commands: { '/f04-bad': null, '/f04-invalid': { desktop: 'bogus' } } } as unknown as CommandsCatalogLike)
    expect(resolveDesktopCommand('/f04-bad')).toBeNull()
    expect(resolveDesktopCommand('/f04-invalid')).toBeNull()
    expect(isDesktopSlashSuggestion('/my-skill')).toBe(true)
  })
})
