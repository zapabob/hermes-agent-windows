import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { atom } from 'nanostores'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  Element.prototype.hasPointerCapture = vi.fn(() => false)
  Element.prototype.releasePointerCapture = vi.fn()
})

const getDelegationConfig = vi.fn()
const saveDelegationConfig = vi.fn()
let profileSwitchHandler: (() => void) | null = null
const requestProfileAtom = atom<string | undefined>(undefined)

vi.mock('@/hermes', () => ({
  getDelegationConfig: (profile?: null | string) => getDelegationConfig(profile),
  saveDelegationConfig: (delegation: Record<string, unknown>, profile?: null | string) =>
    saveDelegationConfig(delegation, profile)
}))

vi.mock('../hooks/use-on-profile-switch', () => ({
  useOnProfileSwitch: (handler: () => void) => {
    profileSwitchHandler = handler
  }
}))

vi.mock('@/store/settings-scope', () => ({
  $settingsRequestProfile: requestProfileAtom
}))

vi.mock('@/store/notifications', () => ({
  notify: vi.fn(),
  notifyError: vi.fn()
}))

beforeEach(() => {
  getDelegationConfig.mockResolvedValue({
    ok: true,
    delegation: {
      provider: 'openai',
      model: 'gpt-base',
      max_spawn_depth: 1,
      max_concurrent_children: 3,
      orchestrator_enabled: true,
      inherit_mcp_toolsets: true,
      max_iterations: 250,
      max_summary_chars: 24000,
      child_timeout_seconds: 0,
      reasoning_effort: '',
      api_mode: '',
      base_url: '',
      subagent_auto_approve: false,
      surface_child_process_notifications: false
    },
    has_api_key: true,
    schema_affecting_keys: ['max_concurrent_children', 'max_spawn_depth', 'orchestrator_enabled']
  })
  saveDelegationConfig.mockResolvedValue({
    ok: true,
    delegation: {
      provider: 'openai',
      model: 'gpt-applied',
      max_spawn_depth: 2,
      max_concurrent_children: 4,
      orchestrator_enabled: true,
      inherit_mcp_toolsets: true,
      max_iterations: 250,
      max_summary_chars: 24000,
      child_timeout_seconds: 0,
      reasoning_effort: '',
      api_mode: '',
      base_url: '',
      subagent_auto_approve: false,
      surface_child_process_notifications: false,
      fallback_providers: []
    },
    schema_affecting_changed: ['max_concurrent_children', 'max_spawn_depth'],
    applies_on: 'new_session'
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  profileSwitchHandler = null
})

async function renderSubagent() {
  const { SubagentSettings } = await import('./subagent-settings')

  return render(<SubagentSettings />)
}

describe('SubagentSettings', () => {
  it('loads the delegation block and does not save until Apply', async () => {
    await renderSubagent()

    await waitFor(() => expect(getDelegationConfig).toHaveBeenCalledWith(undefined))
    expect(await screen.findByDisplayValue('gpt-base')).toBeTruthy()

    fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'gpt-edited' } })
    expect(saveDelegationConfig).not.toHaveBeenCalled()
    expect(screen.getByText('Unsaved draft')).toBeTruthy()
  })

  it('Applies the full draft in one PUT and never sends api_key', async () => {
    getDelegationConfig.mockResolvedValueOnce({
      ok: true,
      delegation: {
        provider: 'openai',
        model: 'gpt-base',
        max_spawn_depth: 1,
        max_concurrent_children: 3,
        orchestrator_enabled: true,
        inherit_mcp_toolsets: true,
        max_iterations: 250,
        max_summary_chars: 24000,
        child_timeout_seconds: 0,
        reasoning_effort: '',
        api_mode: '',
        base_url: '',
        subagent_auto_approve: false,
        surface_child_process_notifications: false,
        fallback_providers: []
      },
      has_api_key: true,
      schema_affecting_keys: ['max_concurrent_children', 'max_spawn_depth', 'orchestrator_enabled']
    })

    await renderSubagent()
    await screen.findByDisplayValue('gpt-base')

    fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'gpt-applied' } })
    fireEvent.change(screen.getByLabelText('Max spawn depth'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('Max concurrent children'), { target: { value: '4' } })

    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))

    await waitFor(() => expect(saveDelegationConfig).toHaveBeenCalledTimes(1))
    const [payload, profile] = saveDelegationConfig.mock.calls[0]
    expect(profile).toBeUndefined()
    expect(payload).toMatchObject({
      model: 'gpt-applied',
      provider: 'openai',
      max_spawn_depth: 2,
      max_concurrent_children: 4,
      fallback_providers: []
    })
    expect(payload).not.toHaveProperty('api_key')
  })

  it('keeps the draft when Apply fails', async () => {
    saveDelegationConfig.mockRejectedValueOnce(new Error('boom'))
    await renderSubagent()
    await screen.findByDisplayValue('gpt-base')

    fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'still-here' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))

    await waitFor(() => expect(saveDelegationConfig).toHaveBeenCalled())
    expect(screen.getByDisplayValue('still-here')).toBeTruthy()
    expect(screen.getByText('Unsaved draft')).toBeTruthy()
  })

  it('drops a stale Apply after profile switch', async () => {
    let resolveSave: (value: unknown) => void = () => undefined
    saveDelegationConfig.mockImplementationOnce(
      () =>
        new Promise(resolve => {
          resolveSave = resolve
        })
    )

    await renderSubagent()
    await screen.findByDisplayValue('gpt-base')

    fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'stale-draft' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))

    await waitFor(() => expect(saveDelegationConfig).toHaveBeenCalled())

    getDelegationConfig.mockResolvedValueOnce({
      ok: true,
      delegation: { provider: 'anthropic', model: 'claude-new', max_spawn_depth: 1 },
      has_api_key: false,
      schema_affecting_keys: []
    })

    profileSwitchHandler?.()

    await waitFor(() => expect(getDelegationConfig).toHaveBeenCalledTimes(2))

    resolveSave({
      ok: true,
      delegation: { provider: 'openai', model: 'should-not-paint', max_spawn_depth: 9 },
      schema_affecting_changed: [],
      applies_on: 'next_child'
    })

    await waitFor(() => expect(screen.getByDisplayValue('claude-new')).toBeTruthy())
    expect(screen.queryByDisplayValue('should-not-paint')).toBeNull()
    expect(screen.queryByDisplayValue('stale-draft')).toBeNull()
  })
})

describe('draft helpers', () => {
  it('treats missing fallback_providers as inherit (null) and [] as disabled', async () => {
    const { blockToDraft, draftToPayload } = await import('./subagent-settings')

    expect(blockToDraft({ model: 'x' }).fallback_providers).toBeNull()
    expect(blockToDraft({ fallback_providers: [] }).fallback_providers).toEqual([])
    expect(draftToPayload(blockToDraft({ fallback_providers: null })).fallback_providers).toBeNull()
  })
})
