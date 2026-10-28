import { beforeEach, describe, expect, it, vi } from 'vitest'

import { handleToolEvent } from './gateway-event/tools'
import type { GatewayEventContext } from './gateway-event/types'

describe('MCP tool.progress events', () => {
  const upsertToolCall = vi.fn()
  const flushQueuedDeltas = vi.fn()
  const updateSessionState = vi.fn()
  const sessionInterrupted = vi.fn(() => false)

  beforeEach(() => {
    upsertToolCall.mockClear()
    flushQueuedDeltas.mockClear()
    updateSessionState.mockClear()
    sessionInterrupted.mockClear()
  })

  function ctx(partial: Partial<GatewayEventContext> & { event: GatewayEventContext['event'] }): GatewayEventContext {
    return {
      deps: {
        flushQueuedDeltas,
        nativeSubagentSessionsRef: { current: new Set() },
        sessionInterrupted,
        updateSessionState,
        upsertToolCall
      } as GatewayEventContext['deps'],
      payload: {
        tool_id: 'call-a',
        name: 'mcp__demo__work',
        progress: 3,
        total: 10,
        preview: 'step'
      },
      sessionId: 'sess-1',
      isActiveEvent: true,
      occurredAt: 1,
      ...partial
    }
  }

  it('routes tool.progress to the running tool row for the call id', () => {
    const handled = handleToolEvent(
      ctx({
        event: { type: 'tool.progress', session_id: 'sess-1' } as GatewayEventContext['event']
      })
    )

    expect(handled).toBe(true)
    expect(upsertToolCall).toHaveBeenCalledWith(
      'sess-1',
      expect.objectContaining({ tool_id: 'call-a', name: 'mcp__demo__work' }),
      'running',
      'tool.progress',
      1
    )
  })

  it('does not treat progress as tool.complete', () => {
    handleToolEvent(
      ctx({
        event: { type: 'tool.progress', session_id: 'sess-1' } as GatewayEventContext['event']
      })
    )

    expect(upsertToolCall.mock.calls.every(call => call[2] === 'running')).toBe(true)
  })
})
