import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { atom } from 'nanostores'
import type { ComponentProps } from 'react'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { PRIMARY_SESSION_VIEW, type SessionView, SessionViewProvider } from '@/app/chat/session-view'
import { DropdownMenu, DropdownMenuContent } from '@/components/ui/dropdown-menu'
import type { HermesGateway } from '@/hermes'
import { $daybreakByProfile } from '@/store/daybreak'
import { $favoriteModels } from '@/store/favorite-models'
import { $modelPresets } from '@/store/model-presets'
import { $visibleModels } from '@/store/model-visibility'
import { $notifications, clearNotifications } from '@/store/notifications'
import { $collapsedProviders } from '@/store/provider-collapse'
import {
  $activeSessionId,
  $currentFastMode,
  $currentModel,
  $currentProvider,
  $currentReasoningEffort
} from '@/store/session'
import { $sessionStates } from '@/store/session-states'

import { ModelMenuPanel } from './model-menu-panel'

type PanelProps = ComponentProps<typeof ModelMenuPanel>
type Request = (method: string, params?: Record<string, unknown>) => Promise<unknown>

const MODEL = 'catalog-model'
const PROVIDER = 'openai-codex'
const MODEL_PRESETS = { 'openai-codex::catalog-model': { effort: 'high', fast: true } }

const supportedCatalog = {
  providers: [
    {
      slug: PROVIDER,
      name: 'OpenAI Codex',
      models: [MODEL],
      capabilities: { [MODEL]: { daybreak: true, fast: true, reasoning: true } }
    }
  ]
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void

  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })

  return { promise, reject, resolve }
}

function gateway(request: Request): HermesGateway {
  return { request } as HermesGateway
}

function renderPanel(props: Omit<PanelProps, 'onSelectModel'>, view: SessionView = PRIMARY_SESSION_VIEW) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const select = vi.fn()

  const scene = (next: Omit<PanelProps, 'onSelectModel'>) => (
    <QueryClientProvider client={client}>
      <SessionViewProvider value={view}>
        <DropdownMenu open>
          <DropdownMenuContent>
            <ModelMenuPanel {...next} onSelectModel={select} />
          </DropdownMenuContent>
        </DropdownMenu>
      </SessionViewProvider>
    </QueryClientProvider>
  )

  const rendered = render(scene(props))

  return { ...rendered, select, show: (next: Omit<PanelProps, 'onSelectModel'>) => rendered.rerender(scene(next)) }
}

async function openOptions() {
  const text = await screen.findByText(/Catalog Model/i)
  const row = text.closest('[role="menuitem"]')!
  fireEvent.keyDown(row, { key: 'ArrowRight' })
}

async function daybreakSwitch() {
  await openOptions()

  return await screen.findByRole<HTMLButtonElement>('switch', { name: 'Daybreak' })
}

function writes(request: ReturnType<typeof vi.fn<Request>>) {
  return request.mock.calls.filter(([method]) => method === 'config.set')
}

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  Element.prototype.hasPointerCapture = vi.fn(() => false)
  Element.prototype.releasePointerCapture = vi.fn()
})

beforeEach(() => {
  $daybreakByProfile.set({})
  $favoriteModels.set([])
  $collapsedProviders.set([])
  $visibleModels.set(null)
  $sessionStates.set({})
  $activeSessionId.set('daybreak-panel-runtime')
  $currentModel.set(MODEL)
  $currentProvider.set(PROVIDER)
  $currentFastMode.set(true)
  $currentReasoningEffort.set('high')
  $modelPresets.set(MODEL_PRESETS)
  clearNotifications()
})

afterEach(() => {
  cleanup()
  clearNotifications()
  vi.clearAllMocks()
})

describe('ModelMenuPanel Daybreak ownership and recovery', () => {
  it('waits for a confirmed profile value before allowing the first edit', async () => {
    const initial = deferred<{ value: boolean }>()

    const request = vi.fn<Request>(async method => {
      if (method === 'model.options') {
        return supportedCatalog
      }

      if (method === 'config.get') {
        return initial.promise
      }

      throw new Error(`Unexpected request: ${method}`)
    })

    renderPanel({
      profile: 'panel-initial',
      ownerConnectionId: 'panel-local',
      requestGateway: request as PanelProps['requestGateway']
    })
    const toggle = await daybreakSwitch()
    expect(toggle.disabled).toBe(true)
    fireEvent.click(toggle)
    expect(writes(request)).toEqual([])

    await act(async () => {
      initial.resolve({ value: true })
    })
    await waitFor(() => expect(toggle.disabled).toBe(false))
    expect(toggle.getAttribute('aria-checked')).toBe('true')
    expect(request).toHaveBeenCalledWith('config.get', { key: 'daybreak', profile: 'panel-initial' })
  })

  it('keeps a pending profile A save separate from profile B edits and later views', async () => {
    const firstSave = deferred<{ value: boolean }>()

    const saved = new Map([
      ['panel-profile-a', false],
      ['panel-profile-b', true]
    ])

    const request = vi.fn<Request>(async (method, params) => {
      if (method === 'model.options') {
        return supportedCatalog
      }

      const profile = String(params?.profile)

      if (method === 'config.get') {
        return { value: saved.get(profile) }
      }

      if (method === 'config.set' && profile === 'panel-profile-a') {
        const result = await firstSave.promise
        saved.set(profile, result.value)

        return result
      }

      if (method === 'config.set') {
        saved.set(profile, params?.value === true)

        return { value: params?.value }
      }

      throw new Error(`Unexpected request: ${method}`)
    })

    const owner = gateway(request)

    const host = {
      ownerConnectionId: 'panel-profiles',
      gateway: owner,
      requestGateway: request as PanelProps['requestGateway']
    }

    const panel = renderPanel({ ...host, profile: 'panel-profile-a' })
    const firstToggle = await daybreakSwitch()
    await waitFor(() => expect(firstToggle.disabled).toBe(false))
    fireEvent.click(firstToggle)
    await waitFor(() => expect(writes(request)).toHaveLength(1))

    panel.show({ ...host, profile: 'panel-profile-b' })
    const secondToggle = await daybreakSwitch()
    await waitFor(() => expect(secondToggle.disabled).toBe(false))
    expect(secondToggle.getAttribute('aria-checked')).toBe('true')
    fireEvent.click(secondToggle)
    await waitFor(() => expect(saved.get('panel-profile-b')).toBe(false))

    await act(async () => {
      firstSave.resolve({ value: true })
    })
    await waitFor(() => expect(saved.get('panel-profile-a')).toBe(true))
    expect(secondToggle.getAttribute('aria-checked')).toBe('false')
    expect(writes(request)).toEqual([
      ['config.set', { key: 'daybreak', profile: 'panel-profile-a', value: true }],
      ['config.set', { key: 'daybreak', profile: 'panel-profile-b', value: false }]
    ])

    panel.show({ ...host, profile: 'panel-profile-a' })
    const returnedToggle = await daybreakSwitch()
    await waitFor(() => expect(returnedToggle.getAttribute('aria-checked')).toBe('true'))
    expect(panel.select).not.toHaveBeenCalled()
  })

  it('sends queued flips to the captured local connection after the remote default is focused', async () => {
    const firstSave = deferred<{ value: boolean }>()

    const local = vi.fn<Request>(async (method, params) => {
      if (method === 'config.get') {
        return { value: false }
      }

      if (method === 'config.set' && params?.value === true) {
        return firstSave.promise
      }

      if (method === 'config.set') {
        return { value: params?.value }
      }

      throw new Error(`Unexpected local request: ${method}`)
    })

    const remote = vi.fn<Request>(async (method, params) => {
      if (method === 'config.get') {
        return { value: true }
      }

      if (method === 'config.set') {
        return { value: params?.value }
      }

      throw new Error(`Unexpected remote request: ${method}`)
    })

    const ambient = vi.fn<Request>(async method => {
      if (method === 'model.options') {
        return supportedCatalog
      }

      throw new Error('A profile setting must not follow ambient focus')
    })

    const panel = renderPanel({
      gateway: gateway(local),
      ownerConnectionId: 'panel-queue-local',
      profile: 'default',
      requestGateway: ambient as PanelProps['requestGateway']
    })

    const toggle = await daybreakSwitch()
    await waitFor(() => expect(toggle.disabled).toBe(false))
    fireEvent.click(toggle)
    await waitFor(() => expect(writes(local)).toHaveLength(1))
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-checked')).toBe('false')

    panel.show({
      gateway: gateway(remote),
      ownerConnectionId: 'panel-queue-remote',
      profile: 'default',
      requestGateway: ambient as PanelProps['requestGateway']
    })
    const remoteToggle = await daybreakSwitch()
    await waitFor(() => expect(remoteToggle.disabled).toBe(false))
    expect(remoteToggle.getAttribute('aria-checked')).toBe('true')

    await act(async () => {
      firstSave.resolve({ value: true })
    })
    await waitFor(() => expect(writes(local)).toHaveLength(2))
    expect(writes(local)).toEqual([
      ['config.set', { key: 'daybreak', profile: 'default', value: true }],
      ['config.set', { key: 'daybreak', profile: 'default', value: false }]
    ])
    expect(writes(remote)).toEqual([])
    expect(ambient.mock.calls.every(([method]) => method === 'model.options')).toBe(true)
    expect(remoteToggle.getAttribute('aria-checked')).toBe('true')
  })

  it('uses the tile owner requester and writes profile config without a session override', async () => {
    const request = vi.fn<Request>(async (method, params) => {
      if (method === 'model.options') {
        return supportedCatalog
      }

      if (method === 'config.get') {
        return { value: false }
      }

      if (method === 'config.set') {
        return { value: params?.value }
      }

      throw new Error(`Unexpected request: ${method}`)
    })

    const tile: SessionView = {
      ...PRIMARY_SESSION_VIEW,
      kind: 'tile',
      $runtimeId: atom('tile-runtime'),
      $model: atom(MODEL),
      $provider: atom(PROVIDER),
      $fast: atom(true),
      $reasoningEffort: atom('high')
    }

    const panel = renderPanel(
      {
        ownerConnectionId: 'panel-tile-owner',
        profile: 'panel-tile-profile',
        requestGateway: request as PanelProps['requestGateway']
      },
      tile
    )

    const toggle = await daybreakSwitch()
    await waitFor(() => expect(toggle.disabled).toBe(false))
    fireEvent.click(toggle)
    await waitFor(() => expect(writes(request)).toHaveLength(1))
    expect(writes(request)).toEqual([['config.set', { key: 'daybreak', profile: 'panel-tile-profile', value: true }]])
    expect(tile.$fast.get()).toBe(true)
    expect(tile.$reasoningEffort.get()).toBe('high')
    expect($currentFastMode.get()).toBe(true)
    expect($currentReasoningEffort.get()).toBe('high')
    expect(panel.select).not.toHaveBeenCalled()
  })

  it('does not query or expose Daybreak when the account catalog lists no supporting model', async () => {
    const request = vi.fn<Request>(async method => {
      if (method === 'model.options') {
        return {
          providers: [
            {
              slug: PROVIDER,
              name: 'OpenAI Codex',
              models: [MODEL],
              capabilities: {
                [MODEL]: { daybreak: false, fast: true, reasoning: true }
              }
            }
          ]
        }
      }

      throw new Error(`Unsupported account must not request ${method}`)
    })

    renderPanel({ profile: 'panel-unsupported', requestGateway: request as PanelProps['requestGateway'] })
    await openOptions()
    await waitFor(() => expect(screen.queryAllByRole('switch').length).toBeGreaterThan(0))
    expect(screen.queryByRole('switch', { name: 'Daybreak' })).toBeNull()
    expect(request.mock.calls.every(([method]) => method === 'model.options')).toBe(true)
  })

  it('keeps an unread profile disabled, reports the read failure, and retries when reopened', async () => {
    let failRead = true

    const request = vi.fn<Request>(async method => {
      if (method === 'model.options') {
        return supportedCatalog
      }

      if (method === 'config.get' && failRead) {
        throw new Error('Profile configuration unavailable')
      }

      if (method === 'config.get') {
        return { value: true }
      }

      throw new Error(`Unexpected request: ${method}`)
    })

    const props = {
      ownerConnectionId: 'panel-read-failure',
      profile: 'panel-read-failure',
      requestGateway: request as PanelProps['requestGateway']
    }

    const panel = renderPanel(props)
    const disabled = await daybreakSwitch()
    await waitFor(() => expect($notifications.get().some(item => item.kind === 'error')).toBe(true))
    expect(disabled.disabled).toBe(true)
    fireEvent.click(disabled)
    expect(writes(request)).toEqual([])
    expect($notifications.get().some(item => /Daybreak/i.test(item.title ?? item.message))).toBe(true)

    panel.unmount()
    failRead = false
    renderPanel(props)
    const retry = await daybreakSwitch()
    await waitFor(() => expect(retry.disabled).toBe(false))
    expect(retry.getAttribute('aria-checked')).toBe('true')
    expect(request.mock.calls.filter(([method]) => method === 'config.get')).toHaveLength(2)
  })

  it('restores a failed save without altering Fast Mode, effort, presets, session or model', async () => {
    const save = deferred<{ value: boolean }>()

    const request = vi.fn<Request>(async method => {
      if (method === 'model.options') {
        return supportedCatalog
      }

      if (method === 'config.get') {
        return { value: true }
      }

      if (method === 'config.set') {
        return save.promise
      }

      throw new Error(`Unexpected request: ${method}`)
    })

    const panel = renderPanel({
      profile: 'panel-save-failure',
      ownerConnectionId: 'panel-save-failure',
      requestGateway: request as PanelProps['requestGateway']
    })

    const toggle = await daybreakSwitch()
    await waitFor(() => expect(toggle.disabled).toBe(false))
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-checked')).toBe('false')
    await waitFor(() => expect(writes(request)).toHaveLength(1))

    await act(async () => {
      save.reject(new Error('Access denied'))
    })
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('true'))
    expect($notifications.get().some(item => item.kind === 'error')).toBe(true)
    expect(writes(request)).toEqual([['config.set', { key: 'daybreak', profile: 'panel-save-failure', value: false }]])
    expect($currentFastMode.get()).toBe(true)
    expect($currentReasoningEffort.get()).toBe('high')
    expect($modelPresets.get()).toEqual(MODEL_PRESETS)
    expect($activeSessionId.get()).toBe('daybreak-panel-runtime')
    expect($currentModel.get()).toBe(MODEL)
    expect($currentProvider.get()).toBe(PROVIDER)
    expect(panel.select).not.toHaveBeenCalled()
  })
})
