import { afterEach, describe, expect, it } from 'vitest'

import { $activeGatewayProfile } from '@/store/profile'

import { type CommandsCatalogLike, isDesktopSlashCommand, isDesktopSlashSuggestion } from './desktop-slash-commands'
import { queryClient } from './query-client'

const reviewVerbs = ['pending', 'approve', 'reject', 'diff', 'approval']

const warm = (commands: Record<string, unknown>) =>
  queryClient.setQueryData(['slash-completions', 'catalog'], { commands } as CommandsCatalogLike)

afterEach(() => {
  queryClient.clear()
  $activeGatewayProfile.set('default')
})

describe('F04 review subcommand admission', () => {
  it.each(reviewVerbs)('allows the supported %s review with an older backend', verb => {
    warm({ '/skills': { desktop: 'settings' } })
    expect(isDesktopSlashCommand(` /SKILLS  ${verb.toUpperCase()} record-id `)).toBe(true)
    expect(isDesktopSlashSuggestion('/skills')).toBe(true)
  })

  it.each([
    '',
    'install source',
    'audit',
    'search name',
    'browse',
    'inspect name',
    'update',
    'apply id',
    'deny id',
    'unknown'
  ])('keeps the hub invocation %s off the exec path', arg => {
    expect(isDesktopSlashCommand(`/skills ${arg}`)).toBe(false)
  })

  it('permits live narrowing without widening the local maximum', () => {
    warm({ '/skills': { desktop: null, desktop_subcommands: ['diff', 'install'] } })
    expect(isDesktopSlashCommand('/skills diff record-id')).toBe(true)
    expect(isDesktopSlashCommand('/skills pending')).toBe(false)
    expect(isDesktopSlashCommand('/skills install source')).toBe(false)
  })

  it.each([[], ['install'], 'all', [null, 7]])(
    'does not erase the static scope with invalid or empty data %j',
    scope => {
      warm({ '/skills': { desktop_subcommands: scope } })
      expect(isDesktopSlashCommand('/skills install source')).toBe(false)
    }
  )

  it('makes an empty live scope deny every review verb', () => {
    warm({ '/skills': { desktop_subcommands: [] } })

    for (const verb of reviewVerbs) {
      expect(isDesktopSlashCommand(`/skills ${verb}`)).toBe(false)
    }
  })

  it.each(['/clear', '/snapshot', '/reasoning', '/approve'])('preserves the local unavailable command %s', command => {
    warm({ [command]: { desktop: 'hidden', desktop_subcommands: ['run'] } })
    expect(isDesktopSlashCommand(`${command} run`)).toBe(false)
  })

  it('keeps hidden review execution distinct from discovery and restricts its arguments', () => {
    warm({ '/f04-hidden-review': { desktop: 'hidden', desktop_subcommands: ['diff'] } })
    expect(isDesktopSlashSuggestion('/f04-hidden-review')).toBe(false)
    expect(isDesktopSlashCommand('/f04-hidden-review diff record-id')).toBe(true)
    expect(isDesktopSlashCommand('/f04-hidden-review install source')).toBe(false)
  })

  it('drops a prior profile restriction while retaining the offline maximum', () => {
    $activeGatewayProfile.set('f04-owner')
    warm({ '/skills': { desktop_subcommands: [] } })
    expect(isDesktopSlashCommand('/skills pending')).toBe(false)
    $activeGatewayProfile.set('f04-foreign')
    expect(isDesktopSlashCommand('/skills pending')).toBe(true)
    expect(isDesktopSlashCommand('/skills install source')).toBe(false)
  })
})
