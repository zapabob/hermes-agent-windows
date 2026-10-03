import type { Unstable_TriggerItem } from '@assistant-ui/core'
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import type { HermesGateway } from '@/hermes'
import { queryClient } from '@/lib/query-client'

import { useSlashCompletions } from './use-slash-completions'

afterEach(() => {
  cleanup()
  queryClient.clear()
})
const commandsOf = (items: readonly Unstable_TriggerItem[]) =>
  items.map(i => (i.metadata as { command: string }).command)

it.each(['', 'f04'])('filters public live completion metadata for query %s', async query => {
  const rows = ['/f04-offered', '/f04-hidden', '/f04-terminal', '/f04-messaging', '/f04-advanced']

  const catalog = {
    pairs: rows.map(n => [n, n]),
    commands: {
      '/f04-offered': { desktop: null, argument_mode: 'text' },
      '/f04-hidden': { desktop: 'hidden' },
      '/f04-terminal': { desktop: 'terminal' },
      '/f04-messaging': { desktop: 'messaging' },
      '/f04-advanced': { desktop: 'advanced' }
    }
  }

  const request = vi.fn(async (method: string) =>
    method === 'commands.catalog' ? catalog : { items: rows.map(text => ({ text })) }
  )
  let search!: (q: string) => readonly Unstable_TriggerItem[]

  function Probe() {
    search = useSlashCompletions({ gateway: { request } as unknown as HermesGateway }).adapter.search!

    return null
  }

  render(<Probe />)
  await act(async () => {
    search(query)
    await new Promise(r => setTimeout(r, 160))
  })
  expect(commandsOf(search(query))).toEqual(['/f04-offered'])
})

it.each(['hidden', 'terminal', 'messaging', 'advanced'])(
  'explicit %s arguments retain only supported completion rows',
  async desktop => {
    const request = vi.fn(async (method: string) =>
      method === 'commands.catalog'
        ? { commands: { '/f04-argument': { desktop, argument_mode: 'options' } } }
        : { items: [{ text: 'on', display: 'on' }], replace_from: '/f04-argument '.length }
    )

    let search!: (q: string) => readonly Unstable_TriggerItem[]

    function Probe() {
      search = useSlashCompletions({ gateway: { request } as unknown as HermesGateway }).adapter.search!

      return null
    }

    render(<Probe />)
    await act(async () => {
      search('f04-argument ')
      await new Promise(r => setTimeout(r, 160))
    })
    expect(commandsOf(search('f04-argument '))).toEqual(desktop === 'hidden' ? ['/f04-argument on'] : [])
  }
)
