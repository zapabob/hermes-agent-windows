import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import type { CustomEndpoint } from '@/types/hermes'

const api = vi.hoisted(() => ({
  activateCustomEndpoint: vi.fn(),
  deleteCustomEndpoint: vi.fn(),
  getCustomEndpoints: vi.fn(),
  saveCustomEndpoint: vi.fn(),
  validateCustomEndpoint: vi.fn()
}))

vi.mock('@/hermes', () => api)
vi.mock('@/lib/haptics', () => ({ triggerHaptic: vi.fn() }))
vi.mock('@/store/notifications', () => ({ notify: vi.fn(), notifyError: vi.fn() }))

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

it('saves a manually entered model absent from discovery and reloads the saved identity', async () => {
  const { CustomEndpointsSettings } = await import('./custom-endpoints-settings')
  const model = 'local/unlisted-test-Q4_K_M.gguf'

  const endpoint: CustomEndpoint = {
    id: 'owned-local',
    name: 'Owned Local',
    base_url: 'http://127.0.0.1:9999/v1',
    model,
    models: ['discovered-only-model', model],
    discover_models: true,
    has_api_key: false,
    is_current: true
  }

  const changed = vi.fn()

  api.getCustomEndpoints.mockResolvedValue({ endpoints: [] })
  api.validateCustomEndpoint.mockResolvedValue({ ok: true, reachable: true, models: ['discovered-only-model'] })
  api.saveCustomEndpoint.mockResolvedValue({ id: endpoint.id, endpoints: [endpoint] })

  const view = render(<CustomEndpointsSettings onMainModelChanged={changed} />)

  fireEvent.change(await screen.findByLabelText('Name'), { target: { value: endpoint.name } })
  fireEvent.change(screen.getByLabelText('Provider ID'), { target: { value: endpoint.id } })
  fireEvent.change(screen.getByLabelText('Endpoint URL'), { target: { value: endpoint.base_url } })
  fireEvent.change(screen.getByLabelText('Default Model'), { target: { value: model } })
  fireEvent.click(screen.getByRole('button', { name: 'Test' }))
  await waitFor(() => expect(api.validateCustomEndpoint).toHaveBeenCalledOnce())
  await waitFor(() => expect(screen.getByRole('button', { name: 'Test' }).hasAttribute('disabled')).toBe(false))
  expect((screen.getByLabelText('Default Model') as HTMLInputElement).value).toBe(model)

  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(changed).toHaveBeenCalledWith(endpoint.id, model))
  expect(api.saveCustomEndpoint).toHaveBeenCalledWith(
    expect.objectContaining({
      id: endpoint.id,
      name: endpoint.name,
      base_url: endpoint.base_url,
      model,
      make_default: true,
      models: ['discovered-only-model']
    })
  )

  view.unmount()
  api.getCustomEndpoints.mockResolvedValue({ endpoints: [endpoint] })
  render(<CustomEndpointsSettings />)
  expect(((await screen.findByLabelText('Default Model')) as HTMLInputElement).value).toBe(model)
  expect((screen.getByLabelText('Provider ID') as HTMLInputElement).value).toBe(endpoint.id)
  expect(api.saveCustomEndpoint).toHaveBeenCalledOnce()
})
