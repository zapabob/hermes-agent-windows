import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { DropdownMenu, DropdownMenuContent } from '@/components/ui/dropdown-menu'
import { modelOptionsQueryKey } from '@/lib/model-options'
import {
  $activeSessionId,
  $currentFastMode,
  $currentModel,
  $currentProvider,
  $currentReasoningEffort
} from '@/store/session'
import type { ModelOptionsResponse } from '@/types/hermes'

import { ModelMenuPanel } from './model-menu-panel'

vi.mock('@/hermes', () => ({ getGlobalModelOptions: vi.fn(), setApiRequestProfile: vi.fn() }))
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  Element.prototype.hasPointerCapture = vi.fn(() => false)
  Element.prototype.releasePointerCapture = vi.fn()
})
beforeEach(() => {
  $activeSessionId.set('owned-session')
  $currentModel.set('selected-new-model')
  $currentProvider.set('owned-provider')
  $currentReasoningEffort.set('high')
  $currentFastMode.set(true)
})
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

const original: ModelOptionsResponse = {
  providers: [{ slug: 'owned-provider', name: 'Owned provider', models: ['listed-model'] }]
}

const refreshed: ModelOptionsResponse = {
  providers: [{ slug: 'other-provider', name: 'Other provider', models: ['first-fallback'] }]
}

function panel(refresh: Promise<ModelOptionsResponse>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const select = vi.fn()

  const request = vi.fn(async (_method: string, params?: Record<string, unknown>) =>
    params?.refresh ? refresh : original
  )

  const view = render(
    <QueryClientProvider client={client}>
      <DropdownMenu open>
        <DropdownMenuContent>
          <ModelMenuPanel
            onSelectModel={select}
            ownerConnectionId="owned-connection"
            profile="work"
            requestGateway={request as never}
          />
        </DropdownMenuContent>
      </DropdownMenu>
    </QueryClientProvider>
  )

  return { client, select, request, view }
}

describe('public Refresh Models retains the workstation selection', () => {
  it('updates the catalogue without switching a missing ordinary model or effort/fast', async () => {
    const { client, select, view } = panel(Promise.resolve(refreshed))
    await view.findByText('Owned provider')
    fireEvent.click(await view.findByText('Refresh Models'))
    await vi.waitFor(() =>
      expect(client.getQueryData(modelOptionsQueryKey('work', 'owned-session', 'owned-connection'))).toEqual(refreshed)
    )
    expect(select).not.toHaveBeenCalled()
    expect([
      $currentModel.get(),
      $currentProvider.get(),
      $currentReasoningEffort.get(),
      $currentFastMode.get()
    ]).toEqual(['selected-new-model', 'owned-provider', 'high', true])
  })

  it('does not overwrite a newer user selection while refresh is waiting', async () => {
    let resolve!: (data: ModelOptionsResponse) => void

    const { select, request, view } = panel(
      new Promise(done => {
        resolve = done
      })
    )

    await view.findByText('Owned provider')
    fireEvent.click(await view.findByText('Refresh Models'))
    await vi.waitFor(() =>
      expect(request).toHaveBeenCalledWith('model.options', expect.objectContaining({ refresh: true }))
    )
    act(() => {
      $currentModel.set('newer-choice')
      $currentProvider.set('newer-provider')
      $currentReasoningEffort.set('medium')
    })
    await act(async () => resolve(refreshed))
    expect(select).not.toHaveBeenCalled()
    expect([$currentModel.get(), $currentProvider.get(), $currentReasoningEffort.get()]).toEqual([
      'newer-choice',
      'newer-provider',
      'medium'
    ])
  })

  it('keeps the successful catalogue on failure and only invalidates this owner', async () => {
    let reject!: (error: Error) => void

    const { client, select, view } = panel(
      new Promise((_done, fail) => {
        reject = fail
      })
    )

    await view.findByText('Owned provider')
    const other = modelOptionsQueryKey('work', 'owned-session', 'other-connection')
    client.setQueryData(other, refreshed)
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    fireEvent.click(await view.findByText('Refresh Models'))
    await act(async () => reject(new Error('owned refresh failure')))
    expect(select).not.toHaveBeenCalled()
    expect(client.getQueryData(modelOptionsQueryKey('work', 'owned-session', 'owned-connection'))).toEqual(original)
    expect(client.getQueryState(other)?.isInvalidated).toBe(false)
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: modelOptionsQueryKey('work', 'owned-session', 'owned-connection'),
      exact: true
    })
  })
})
