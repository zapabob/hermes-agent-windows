import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { DropdownMenu, DropdownMenuContent } from '@/components/ui/dropdown-menu'
import { $favoriteModels } from '@/store/favorite-models'
import {
  $modelVisibilityOpen,
  $visibleModels,
  modelVisibilityKey,
  setModelVisibilityOpen,
  setVisibleModels
} from '@/store/model-visibility'

import { ModelCatalogMenu, type ModelMenuController } from './model-catalog-menu'

// Radix calls these on open; jsdom doesn't implement them.
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  Element.prototype.hasPointerCapture = vi.fn(() => false)
  Element.prototype.releasePointerCapture = vi.fn()
})

const getGlobalModelOptions = vi.fn()

vi.mock('@/hermes', () => ({
  getGlobalModelOptions: (...args: unknown[]) => getGlobalModelOptions(...args),
  setApiRequestProfile: vi.fn()
}))

beforeEach(() => {
  window.localStorage.removeItem('hermes.desktop.favorite-models')
  $favoriteModels.set([])
  $visibleModels.set(null)
  setModelVisibilityOpen(false)
  getGlobalModelOptions.mockResolvedValue({
    providers: [{ models: ['gemini-3.1-pro', 'gemini-2.5-flash'], name: 'Google', slug: 'google' }]
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

// A minimal controller — these tests are about the CATALOG's own behaviour
// (what it lists, what it offers), not about what any host does with a pick.
function renderMenu(host: Partial<ModelMenuController> = {}) {
  const select = vi.fn()

  const controller: ModelMenuController = {
    applyPreset: vi.fn(),
    current: { effort: '', fast: false, model: '', provider: '' },
    presetFor: () => ({}),
    select,
    setOptions: vi.fn(),
    ...host
  }

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(
    <QueryClientProvider client={client}>
      <DropdownMenu open>
        <DropdownMenuContent>
          <ModelCatalogMenu controller={controller} />
        </DropdownMenuContent>
      </DropdownMenu>
    </QueryClientProvider>
  )

  return select
}

describe('Daybreak is gated by the exact account model capability', () => {
  const providers = [
    {
      slug: 'openai-codex',
      name: 'OpenAI Codex',
      models: ['catalog-supported', 'catalog-unsupported'],
      capabilities: {
        'catalog-supported': { fast: true, reasoning: false, daybreak: true },
        'catalog-unsupported': { fast: true, reasoning: false }
      }
    }
  ]

  async function openRow(name: RegExp) {
    const text = await screen.findByText(name)
    const row = text.closest('[role="menuitem"]')!
    fireEvent.keyDown(row, { key: 'ArrowRight' })

    return row
  }

  it('shows a switch only on the catalog-supported row and keeps model selection untouched', async () => {
    const set = vi.fn()
    getGlobalModelOptions.mockResolvedValue({ providers })
    const select = renderMenu({ daybreak: { on: true, set } })
    const row = await openRow(/Catalog Supported/i)
    expect(row.textContent).toContain('Daybreak')
    fireEvent.click(await screen.findByRole('switch', { name: 'Daybreak' }))
    expect(set).toHaveBeenCalledWith(false)
    expect(select).not.toHaveBeenCalled()
    cleanup()

    renderMenu({ daybreak: { on: true, set } })
    const unsupported = await openRow(/Catalog Unsupported/i)
    await screen.findByRole('switch') // Fast control proves the submenu mounted.
    expect(unsupported.textContent).not.toContain('Daybreak')
    expect(screen.queryByRole('switch', { name: 'Daybreak' })).toBeNull()
  })

  it.each([
    ['legacy capability missing', { fast: true, reasoning: false }, 'openai-codex', false],
    ['explicitly unsupported', { fast: true, reasoning: false, daybreak: false }, 'openai-codex', false],
    ['malformed truthy capability', { fast: true, reasoning: false, daybreak: 'true' }, 'openai-codex', false],
    ['non-Codex provider', { fast: true, reasoning: false, daybreak: true }, 'openai', false],
    ['custom provider using the canonical name', { fast: true, reasoning: false, daybreak: true }, 'openai-codex', true]
  ])('does not expose the profile setting for %s', async (_label, caps, slug, custom) => {
    getGlobalModelOptions.mockResolvedValue({
      providers: [
        {
          slug,
          name: 'Provider',
          is_user_defined: custom,
          models: ['catalog-model'],
          capabilities: { 'catalog-model': caps }
        }
      ]
    })
    renderMenu({ daybreak: { on: true, set: vi.fn() } })
    const row = await openRow(/Catalog Model/i)
    await screen.findByRole('switch')
    expect(row.textContent).not.toContain('Daybreak')
    expect(screen.queryByRole('switch', { name: 'Daybreak' })).toBeNull()
  })

  it('does not borrow base-model support for an active unsupported fast sibling', async () => {
    getGlobalModelOptions.mockResolvedValue({
      providers: [
        {
          slug: 'openai-codex',
          name: 'OpenAI Codex',
          models: ['catalog-model', 'catalog-model-fast'],
          capabilities: {
            'catalog-model': { fast: false, reasoning: false, daybreak: true },
            'catalog-model-fast': { fast: false, reasoning: false, daybreak: false }
          }
        }
      ]
    })
    renderMenu({
      current: { model: 'catalog-model-fast', provider: 'openai-codex', effort: '', fast: false },
      daybreak: { on: true, set: vi.fn() }
    })
    const row = await openRow(/Catalog Model/i)
    await screen.findByRole('switch')
    expect(row.textContent).not.toContain('Daybreak')
    expect(screen.queryByRole('switch', { name: 'Daybreak' })).toBeNull()
  })

  it('leaves detached model pickers without a Daybreak controller unchanged', async () => {
    getGlobalModelOptions.mockResolvedValue({ providers })
    renderMenu()
    const row = await openRow(/Catalog Supported/i)
    await screen.findByRole('switch')
    expect(row.textContent).not.toContain('Daybreak')
    expect(screen.queryByRole('switch', { name: 'Daybreak' })).toBeNull()
  })
})

// Curation is ONE global preference, so it belongs to the catalog rather than
// to whichever surface mounted it. If a host had to opt in, the composer and
// the kanban board would end up disagreeing about what "my models" means —
// which is exactly the drift extracting this component was meant to prevent.
describe('the catalog owns model curation', () => {
  it('stars a model without switching and places it first after the menu is reopened', async () => {
    const select = renderMenu()
    await screen.findByText(/Gemini 2\.5 Flash/i)
    fireEvent.click(screen.getByRole('button', { name: /Favorite Gemini 2\.5 Flash/i }))
    expect(select).not.toHaveBeenCalled()
    expect(JSON.parse(window.localStorage.getItem('hermes.desktop.favorite-models') ?? '[]')).toContain(
      modelVisibilityKey('google', 'gemini-2.5-flash')
    )
    cleanup()
    const reopenedSelect = renderMenu()
    await screen.findByText(/Favorites/)

    const rows = screen
      .getAllByRole('menuitem')
      .filter(row => /Gemini (2\.5 Flash|3\.1 Pro)/i.test(row.textContent ?? ''))

    expect(rows[0].textContent).toMatch(/Gemini 2\.5 Flash/i)
    fireEvent.click(rows[0])
    expect(reopenedSelect).toHaveBeenCalledWith('gemini-2.5-flash', 'google')
  })

  it('honours the stored Edit Models shortlist', async () => {
    setVisibleModels(new Set([modelVisibilityKey('google', 'gemini-2.5-flash')]))

    renderMenu()

    await screen.findByText(/Gemini 2\.5 Flash/i)
    expect(screen.queryByText(/Gemini 3\.1 Pro/i)).toBeNull()
  })

  it('still finds a hidden model by search — curation narrows the default view, not the catalog', async () => {
    setVisibleModels(new Set([modelVisibilityKey('google', 'gemini-2.5-flash')]))

    renderMenu()
    await screen.findByText(/Gemini 2\.5 Flash/i)

    const input = screen.getByRole('textbox', { name: 'Search models' })

    fireEvent.change(input, { target: { value: 'gemini-3.1' } })

    await vi.waitFor(() => {
      expect(screen.queryByText(/Gemini 3\.1 Pro/i)).not.toBeNull()
    })
  })

  it('offers Edit Models without the host wiring it up', async () => {
    renderMenu()
    await screen.findByText(/Gemini 3\.1 Pro/i)

    fireEvent.click(screen.getByText('Edit Models…'))

    expect($modelVisibilityOpen.get()).toBe(true)
  })
})
