import { afterEach, expect, it } from 'vitest'

import {
  canonicalDesktopSlashCommand,
  type CommandsCatalogLike,
  desktopSlashCommandArgumentMode,
  filterDesktopCommandsCatalog,
  resolveDesktopCommand
} from './desktop-slash-commands'
import { queryClient } from './query-client'

afterEach(() => queryClient.clear())

it('does not count cold offered registry commands as skills in public help', () => {
  const catalog = {
    pairs: [
      ['/f04-builtin', 'Builtin'],
      ['/f04-skill', 'Skill']
    ],
    skill_count: 1,
    commands: { '/f04-builtin': { desktop: null } }
  } as CommandsCatalogLike

  expect(filterDesktopCommandsCatalog(catalog).skill_count).toBe(1)
})

it('retains a curated canonical name even if catalog canon tries to retarget it', () => {
  queryClient.setQueryData(['slash-completions', 'catalog'], {
    canon: { '/new': '/f04-terminal' },
    commands: { '/f04-terminal': { desktop: 'terminal' } }
  })
  expect(canonicalDesktopSlashCommand('/new')).toBe('/new')
  expect(resolveDesktopCommand('/new')?.surface).toEqual({ kind: 'action', action: 'new' })
})

it('resolves alias argument metadata through its canonical registry key', () => {
  queryClient.setQueryData(['slash-completions', 'catalog'], {
    canon: { '/f04-a': '/f04-mixed' },
    commands: { '/f04-mixed': { desktop: null, argument_mode: 'mixed' } }
  })
  expect(desktopSlashCommandArgumentMode('/f04-a')).toBe('mixed')
})
