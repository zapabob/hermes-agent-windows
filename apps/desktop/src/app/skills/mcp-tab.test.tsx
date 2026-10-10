// @vitest-environment jsdom
// Render the actual settings owner. API effects are counted; no native proof.
import { QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { McpTab } from '@/app/skills/mcp-tab'
import type * as HermesApi from '@/hermes'
import { probeCache } from '@/lib/mcp-probe-cache'
import { queryClient } from '@/lib/query-client'
import { $activeSessionId, $busy } from '@/store/session'

const effects = vi.hoisted(() => ({ save: vi.fn(), request: vi.fn(), probe: vi.fn(), config: vi.fn(), notify: vi.fn() }))
vi.mock('@/hermes', async importOriginal => ({
  ...(await importOriginal<typeof HermesApi>()),
  getHermesConfigRecord: () => effects.config(),
  saveMcpServers: (...args: unknown[]) => effects.save(...args),
  getMcpCatalog: async () => ({ entries: [] }),
  getUsageAnalytics: async () => ({ tools: [] }),
  getLogs: async () => ({ lines: [] }),
  testMcpServer: (...args: unknown[]) => effects.probe(...args)
}))
vi.mock('@/store/notifications', () => ({ notify: effects.notify, notifyError: vi.fn() }))
// Editing visuals are incidental to the server switch. Keep the real owner,
// cache, React hooks, accessible Switch and save callback.
vi.mock('@/components/chat/json-document-editor', () => ({ JsonDocumentEditor: () => null }))

beforeEach(() => {
  effects.config.mockResolvedValue({ mcp_servers: { owned: { url: 'http://127.0.0.1:1/mcp' } } })
  effects.save.mockResolvedValue({ ok: true })
  effects.request.mockResolvedValue({ ok: true })
  effects.probe.mockResolvedValue({ ok: true, tools: [] })
  $activeSessionId.set('owned-cached-conversation')
  queryClient.clear()
  probeCache.clear()
})
afterEach(() => {
  cleanup()
  $activeSessionId.set(null)
  $busy.set(false)
  queryClient.clear()
  probeCache.clear()
  vi.clearAllMocks()
})

describe('MCP saved policy preserves cached conversation catalogue', () => {
  it.each([false, true])('saving disable in cached conversation busy=%s requires no automatic reload consent', async busy => {
    $busy.set(busy)
    const gateway = { request: effects.request } as unknown as HermesApi.HermesGateway
    render(<QueryClientProvider client={queryClient}><MemoryRouter><McpTab gateway={gateway} profile="owned-profile" /></MemoryRouter></QueryClientProvider>)
    const toggle = await screen.findByRole('switch', { name: 'owned' })
    expect(toggle.getAttribute('aria-checked')).toBe('true')
    fireEvent.click(toggle)
    await waitFor(() => expect(effects.save).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('false'))
    expect(effects.save).toHaveBeenCalledWith({ owned: { url: 'http://127.0.0.1:1/mcp', enabled: false } }, 'owned-profile')
    expect(effects.request).not.toHaveBeenCalled()
    expect($activeSessionId.get()).toBe('owned-cached-conversation')
    expect($busy.get()).toBe(busy)
  })
})

describe('MCP save feedback reflects the returned contract and profile', () => {
  it.each([
    [undefined, false],
    [{ policy_check: 'rpc_admission' }, false],
    [{ policy_check: 'unknown', catalogue: 'new_session_or_explicit_reload', admitted_calls: 'may_complete' }, false],
    [{ policy_check: 'rpc_admission', catalogue: 'new_session_or_explicit_reload', admitted_calls: 'may_complete' }, true]
  ])('application %j reports admission only when complete', async (application, admission) => {
    effects.save.mockResolvedValue({ ok: true, application })
    const gateway = { request: effects.request } as unknown as HermesApi.HermesGateway
    render(<QueryClientProvider client={queryClient}><MemoryRouter><McpTab gateway={gateway} profile="owned-profile" /></MemoryRouter></QueryClientProvider>)
    fireEvent.click(await screen.findByRole('switch', { name: 'owned' }))
    await waitFor(() => expect(effects.notify).toHaveBeenCalledTimes(1))
    const notification = effects.notify.mock.calls[0][0] as { kind: string; message: string }
    expect(notification.kind).toBe('success')
    expect(notification.message).toContain('Tool list changes load in a new session or after an explicit MCP reload.')
    expect(notification.message.includes('Saved policy is checked before each call.')).toBe(admission)
    expect(notification.message.includes('Calls already in progress may finish.')).toBe(admission)
    expect(effects.request).not.toHaveBeenCalled()
  })

  it('a pending profile-A save cannot notify or change profile-B settings', async () => {
    let finishSave: ((value: { ok: boolean }) => void) | undefined
    effects.save.mockImplementation(() => new Promise<{ ok: boolean }>(resolve => { finishSave = resolve }))
    const gateway = { request: effects.request } as unknown as HermesApi.HermesGateway
    const view = (profile: string) => <QueryClientProvider client={queryClient}><MemoryRouter><McpTab gateway={gateway} profile={profile} /></MemoryRouter></QueryClientProvider>
    const rendered = render(view('owned-profile'))
    fireEvent.click(await screen.findByRole('switch', { name: 'owned' }))
    await waitFor(() => expect(effects.save).toHaveBeenCalledTimes(1))
    expect(effects.save.mock.calls[0][1]).toBe('owned-profile')
    effects.config.mockResolvedValue({ mcp_servers: { 'owned-b': { url: 'http://127.0.0.1:2/mcp' } } })
    rendered.rerender(view('other-profile'))
    const second = await screen.findByRole('switch', { name: 'owned-b' })
    expect(second.getAttribute('aria-checked')).toBe('true')
    expect(finishSave).toBeDefined()
    await act(async () => { finishSave!({ ok: true }) })
    // The actual promise continuation must leave the new profile untouched.
    await waitFor(() => expect(screen.queryByRole('switch', { name: 'owned' })).toBeNull())
    expect(second.getAttribute('aria-checked')).toBe('true')
    expect(effects.notify).not.toHaveBeenCalled()
    expect(effects.request).not.toHaveBeenCalled()
  })
})
