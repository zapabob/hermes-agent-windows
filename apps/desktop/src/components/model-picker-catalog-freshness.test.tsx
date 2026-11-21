import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { ModelPickerDialog } from '@/components/model-picker'
import type { ModelOptionsResponse } from '@/types/hermes'

vi.mock('@/hermes', () => ({ getGlobalModelOptions: vi.fn(), setApiRequestProfile: vi.fn() }))

beforeAll(() => {
  // cmdk measures its list with ResizeObserver, which jsdom doesn't ship.
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as never
  Element.prototype.scrollIntoView = vi.fn()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

const catalog = {
  provider: 'openrouter',
  cache_key: 'openrouter',
  source: 'live',
  fetched_at: 1_700_000_000,
  age_seconds: 300,
  stale: false,
  fallback: false,
  authoritative: true,
  model_count: 1,
  ttl_seconds: 3600,
  trust_expires_at: 1_700_000_000 + 3600,
  cache_schema: 2
}

function picker(data: ModelOptionsResponse) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const request = vi.fn(async () => data)

  const view = render(
    <QueryClientProvider client={client}>
      <ModelPickerDialog
        currentModel="m1"
        currentProvider="openrouter"
        onOpenChange={vi.fn()}
        onSelect={vi.fn()}
        open
        request={request as never}
      />
    </QueryClientProvider>
  )

  return { ...view, client, request }
}

describe('model picker catalog freshness', () => {
  it('refresh sends refresh:true so the backend updates the upstream registry', async () => {
    const view = picker({
      providers: [{ slug: 'openrouter', name: 'OpenRouter', models: ['m1'], catalog }]
    })

    await view.findByText('OpenRouter')
    const buttons = view.getAllByRole('button', { name: /refresh/i })
    buttons[0].click()

    await vi.waitFor(() => {
      expect(view.request).toHaveBeenCalledWith('model.options', expect.objectContaining({ refresh: true }))
    })
  })

  it('labels a curated snapshot so it is never mistaken for live data', async () => {
    const view = picker({
      providers: [
        {
          slug: 'openrouter',
          name: 'OpenRouter',
          models: ['m1'],
          catalog: { ...catalog, source: 'curated', authoritative: false, stale: false }
        }
      ]
    })

    expect(await view.findByText('curated snapshot')).toBeTruthy()
    expect(view.getByText(/as of/)).toBeTruthy()
  })

  it('labels a stale catalog', async () => {
    const view = picker({
      providers: [
        {
          slug: 'openrouter',
          name: 'OpenRouter',
          models: ['m1'],
          catalog: { ...catalog, source: 'stale', authoritative: false, stale: true }
        }
      ]
    })

    expect(await view.findByText('stale catalog')).toBeTruthy()
  })

  it('warns only when a fresh live catalog says the model is gone', async () => {
    const view = picker({
      providers: [{ slug: 'openrouter', name: 'OpenRouter', models: ['other'], catalog }],
      current_model_status: {
        state: 'not_listed',
        reason: 'missing_from_live_catalog',
        provider: 'openrouter',
        model: 'm1',
        catalog_source: 'live',
        checked_at: 1_700_000_000
      }
    })

    expect(await view.findByText('No longer listed by this provider')).toBeTruthy()
  })

  it('stays quiet when the catalog is not authoritative', async () => {
    const view = picker({
      providers: [
        {
          slug: 'openrouter',
          name: 'OpenRouter',
          models: ['other'],
          catalog: { ...catalog, source: 'curated', authoritative: false }
        }
      ],
      current_model_status: {
        state: 'unverified',
        reason: 'catalog_not_authoritative',
        provider: 'openrouter',
        model: 'm1',
        catalog_source: 'curated',
        checked_at: 1_700_000_000
      }
    })

    await view.findByText('OpenRouter')
    expect(view.queryByText('No longer listed by this provider')).toBeNull()
  })
})
