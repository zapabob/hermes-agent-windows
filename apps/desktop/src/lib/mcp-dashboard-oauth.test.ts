import { JsonRpcGatewayError } from '@hermes/shared'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { setApiRequestConnection, setApiRequestProfile } from '@/api/client'
import { requestGatewayForAgent } from '@/store/gateway'

import { completeMcpDesktopOAuth, McpOAuthCancelled } from './mcp-dashboard-oauth'

vi.mock('@/store/gateway', () => ({ requestGatewayForAgent: vi.fn() }))

const redirectUri = 'http://127.0.0.1:49152/callback'
const authUrl = `https://idp.example/authorize?state=expected&redirect_uri=${encodeURIComponent(redirectUri)}`
const started = { ok: true, session_id: 'flow-1', auth_url: authUrl, flow: 'pkce' }
const tools = [{ name: 'list_reports', description: 'List reports' }]

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void

  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })

  return { promise, resolve, reject }
}

function harness() {
  const callback = deferred<{ code: string | null; state: string | null; error: string | null }>()

  const bridge = {
    listen: vi.fn().mockResolvedValue({ id: 'listener-1', redirectUri }),
    wait: vi.fn(() => callback.promise),
    cancel: vi.fn(async () => {
      callback.resolve({ code: null, state: null, error: 'cancelled' })

      return true
    })
  }

  const api = vi.fn().mockRejectedValue(new Error('Desktop OAuth must not use the remote REST callback'))

  const openExternal = vi.fn(async () => {
    callback.resolve({ code: 'code-1', state: 'expected', error: null })
  })

  Object.defineProperty(window, 'hermesDesktop', { configurable: true, value: { mcpOauth: bridge, api, openExternal } })
  let relayed = false
  const rpc = vi.mocked(requestGatewayForAgent)
  rpc.mockImplementation(async (_connection, _profile, method) => {
    if (method.endsWith('.start')) {
      return started
    }

    if (method.endsWith('.callback')) {
      relayed = true

      return { ok: true }
    }

    if (method.endsWith('.cancel')) {
      return { ok: true, status: 'error' }
    }

    return { ok: true, status: relayed ? 'approved' : 'pending', tools }
  })

  return { bridge, callback, api, openExternal, rpc }
}

afterEach(() => {
  vi.resetAllMocks()
  setApiRequestConnection(null)
  setApiRequestProfile(null)
})

describe('Desktop MCP client callback lifecycle', () => {
  it.each(['local', 'remote-gateway'])(
    'relays through the native listener and keeps the %s owner after foreground changes',
    async connectionId => {
      const { bridge, api, openExternal, rpc } = harness()
      setApiRequestConnection(connectionId)
      setApiRequestProfile('origin-profile')
      const callbackResult = { code: 'code-1', state: 'expected', error: null }
      bridge.wait.mockResolvedValue(callbackResult)
      openExternal.mockImplementation(async () => {
        setApiRequestConnection('other-gateway')
        setApiRequestProfile('other-profile')
      })
      const result = await completeMcpDesktopOAuth({ serverName: 'reports', sleep: async () => {} })
      expect(result).toMatchObject({ status: 'approved', tools })
      expect(rpc).toHaveBeenCalledWith(
        connectionId,
        'origin-profile',
        'mcp.servers.oauth.start',
        { name: 'reports', client_redirect_uri: redirectUri },
        60_000
      )
      expect(rpc).toHaveBeenCalledWith(
        connectionId,
        'origin-profile',
        'mcp.servers.oauth.callback',
        { name: 'reports', session_id: 'flow-1', ...callbackResult },
        60_000
      )
      expect(rpc.mock.calls.every(call => call[0] === connectionId && call[1] === 'origin-profile')).toBe(true)
      expect(bridge.cancel).toHaveBeenCalledWith('listener-1')
      expect(api).not.toHaveBeenCalled()
    }
  )

  it.each(['cancel', 'legacy'])('cleans up the owner before opening an unsafe authorization on %s', async outcome => {
    const { rpc, bridge, openExternal, api } = harness()
    setApiRequestConnection('remote-gateway')
    setApiRequestProfile('origin-profile')
    let cancelled = false
    rpc.mockImplementation(async (_connection, _profile, method) => {
      if (method.endsWith('.start')) {
        setApiRequestConnection('other-gateway')
        setApiRequestProfile('other-profile')
        cancelled = outcome === 'cancel'

        return outcome === 'legacy'
          ? { ...started, auth_url: 'https://idp.example/authorize?redirect_uri=http://remote/callback' }
          : started
      }

      return { ok: true }
    })
    const action = completeMcpDesktopOAuth({ serverName: 'reports', cancelled: () => cancelled })

    if (outcome === 'cancel') {
      await expect(action).rejects.toBeInstanceOf(McpOAuthCancelled)
    } else {
      await expect(action).rejects.toThrow('Update the Hermes backend')
    }

    expect(openExternal).not.toHaveBeenCalled()
    expect(bridge.cancel).toHaveBeenCalledWith('listener-1')
    expect(rpc).toHaveBeenCalledWith(
      'remote-gateway',
      'origin-profile',
      'mcp.servers.oauth.cancel',
      { name: 'reports', session_id: 'flow-1' },
      60_000
    )
    expect(rpc.mock.calls.every(call => call[0] === 'remote-gateway' && call[1] === 'origin-profile')).toBe(true)
    expect(api).not.toHaveBeenCalled()
  })
})

const startupData = {
  kind: 'mcp_oauth_startup_failure',
  session_id: 'owned-startup_1',
  server_name: 'reports'
}

describe('Desktop MCP reserved startup failure ownership', () => {
  it.each([
    ['local', false],
    ['remote-gateway', false],
    ['local', true],
    ['remote-gateway', true]
  ] as const)('retains %s scope and original cause when cleanup fails=%s', async (connectionId, cleanupFails) => {
    const { bridge, rpc, openExternal, api } = harness()
    setApiRequestConnection(connectionId)
    setApiRequestProfile('origin-profile')

    const failure = new JsonRpcGatewayError('Owned original worker startup cause', {
      code: 5024,
      data: { ...startupData, future_metadata: 'ignored' }
    })

    rpc.mockImplementation(async (_connection, _profile, method) => {
      if (method.endsWith('.start')) {
        setApiRequestConnection('other-gateway')
        setApiRequestProfile('other-profile')
        throw failure
      }

      if (cleanupFails) {
        throw new Error('Owned backend cleanup failed')
      }

      return { ok: true }
    })

    if (cleanupFails) {
      bridge.cancel.mockRejectedValue(new Error('Owned native cleanup failed'))
    }

    await expect(completeMcpDesktopOAuth({ serverName: 'reports' })).rejects.toBe(failure)
    expect(failure.message).toBe('Owned original worker startup cause')
    expect(bridge.cancel).toHaveBeenCalledExactlyOnceWith('listener-1')
    expect(rpc.mock.calls.map(call => call[2])).toEqual(['mcp.servers.oauth.start', 'mcp.servers.oauth.cancel'])
    expect(rpc).toHaveBeenLastCalledWith(
      connectionId,
      'origin-profile',
      'mcp.servers.oauth.cancel',
      {
        name: 'reports',
        session_id: startupData.session_id
      },
      60_000
    )
    expect(rpc.mock.calls.every(call => call[0] === connectionId && call[1] === 'origin-profile')).toBe(true)
    expect(openExternal).not.toHaveBeenCalled()
    expect(bridge.wait).not.toHaveBeenCalled()
    expect(api).not.toHaveBeenCalled()
  })

  it.each([
    ['legacy', 5024, undefined],
    ['unrelated code', 4001, startupData],
    ['non-object', 5024, 'owned-startup_1'],
    ['array', 5024, [startupData]],
    ['wrong kind', 5024, { ...startupData, kind: 'other_failure' }],
    ['wrong server', 5024, { ...startupData, server_name: 'other-server' }],
    ['missing id', 5024, { kind: startupData.kind, server_name: 'reports' }],
    ['empty id', 5024, { ...startupData, session_id: '' }],
    ['non-string id', 5024, { ...startupData, session_id: 17 }],
    ['invalid id', 5024, { ...startupData, session_id: '../foreign' }],
    ['padded id', 5024, { ...startupData, session_id: ' owned-startup_1 ' }]
  ] as const)('rejects %s metadata without inventing backend cleanup', async (_label, code, data) => {
    const { bridge, rpc, openExternal, api } = harness()
    const failure = new JsonRpcGatewayError('Owned unrecognized startup cause', { code, data })
    rpc.mockRejectedValue(failure)
    await expect(completeMcpDesktopOAuth({ serverName: 'reports' })).rejects.toBe(failure)
    expect(bridge.cancel).toHaveBeenCalledExactlyOnceWith('listener-1')
    expect(rpc).toHaveBeenCalledTimes(1)
    expect(rpc.mock.calls[0][2]).toBe('mcp.servers.oauth.start')
    expect(openExternal).not.toHaveBeenCalled()
    expect(bridge.wait).not.toHaveBeenCalled()
    expect(api).not.toHaveBeenCalled()
  })
})
