import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useLiveCompletionAdapter } from './use-live-completion-adapter'

describe('completion epoch ownership', () => {
  it('clears prior rows and ignores a pending old-scope response when epoch changes', async () => {
    let finish!: (value: { query: string; items: { text: string }[] }) => void

    const hook = renderHook(({ epoch }) => useLiveCompletionAdapter({
      enabled: true, epoch, debounceMs: 0,
      fetcher: query => query === 'first'
        ? Promise.resolve({ query, items: [{ text: '/old' }] })
        : new Promise(resolve => { finish = resolve }),
      toItem: entry => ({ id: entry.text, label: entry.text, type: 'slash' })
    }), { initialProps: { epoch: 0 } })

    await act(async () => {
      hook.result.current.adapter.search!('first')
      await new Promise(resolve => setTimeout(resolve, 10))
    })
    expect(hook.result.current.adapter.search!('first').map(item => item.id)).toEqual(['/old'])
    await act(async () => {
      hook.result.current.adapter.search!('pending')
      await new Promise(resolve => setTimeout(resolve, 10))
    })
    hook.rerender({ epoch: 1 })
    await act(async () => { finish({ query: 'pending', items: [{ text: '/late-old' }] }) })
    let items: readonly unknown[] = []
    act(() => { items = hook.result.current.adapter.search!('pending') })
    expect(items).toEqual([])
  })
})
