import { describe, expect, it } from 'vitest'

import {
  JSON_RPC_METHOD_NOT_FOUND,
  JsonRpcGatewayClient
} from './json-rpc-gateway.js'

/** Minimal WebSocket stub: records outbound frames; fires `open` immediately. */
class OpenSocket {
  readonly sent: string[] = []
  readyState = 1
  private readonly listeners = new Map<string, Set<(ev: { data?: unknown }) => void>>()

  addEventListener(type: string, handler: (ev: { data?: unknown }) => void): void {
    let set = this.listeners.get(type)
    if (!set) {
      set = new Set()
      this.listeners.set(type, set)
    }
    set.add(handler)
    if (type === 'open') {
      queueMicrotask(() => handler({}))
    }
  }

  removeEventListener(type: string, handler: (ev: { data?: unknown }) => void): void {
    this.listeners.get(type)?.delete(handler)
  }

  send(text: string): void {
    this.sent.push(text)
  }

  close(): void {
    this.readyState = 3
  }

  inject(frame: unknown): void {
    const data = typeof frame === 'string' ? frame : JSON.stringify(frame)
    for (const handler of this.listeners.get('message') ?? []) {
      handler({ data })
    }
  }
}

describe('JsonRpcGatewayClient server→client requests (NC-0213-D1)', () => {
  it('routes a server request to the first accepting handler and answers -32601 when nobody accepts', async () => {
    const unhandled: string[] = []
    const live = new OpenSocket()
    const client = new JsonRpcGatewayClient({
      onUnhandledRequest: req => void unhandled.push(req.method),
      socketFactory: () => live as unknown as WebSocket
    })
    await client.connect('ws://127.0.0.1:9')

    client.onRequest(req => (req.method === 'clarify' ? void req.respond({ answer: 'yes' }) : false))

    live.inject({ id: 'srq-1', jsonrpc: '2.0', method: 'clarify', params: { session_id: 's1' } })
    live.inject({ id: 'srq-2', jsonrpc: '2.0', method: 'tour', params: { session_id: 's1' } })

    const frames = live.sent
      .map(f => JSON.parse(f) as { id: string; method?: string; result?: { answer?: string }; error?: { code: number } })
      .filter(f => typeof f.id === 'string' && f.id.startsWith('srq-'))

    expect(frames[0]).toMatchObject({ id: 'srq-1', result: { answer: 'yes' } })
    expect(frames[1]?.id).toBe('srq-2')
    expect(frames[1]?.error?.code).toBe(JSON_RPC_METHOD_NOT_FOUND)
    expect(unhandled).toEqual(['tour'])
  })

  it('re-delivers open_requests from a response before the caller sees the result, tagged replayed', async () => {
    const live = new OpenSocket()
    const client = new JsonRpcGatewayClient({ socketFactory: () => live as unknown as WebSocket })
    await client.connect('ws://127.0.0.1:9')

    const delivered: Array<{ id: string; replayed?: boolean }> = []
    client.onRequest(req => void delivered.push({ id: req.id, replayed: req.replayed }))

    const resume = client.request<{ session_id: string }>('session.resume', { session_id: 's1' })
    const rid = (JSON.parse(live.sent.at(-1)!) as { id: string }).id
    live.inject({
      id: rid,
      jsonrpc: '2.0',
      result: {
        open_requests: [{ id: 'srq-9', method: 'sudo', params: { session_id: 's1' } }],
        session_id: 's1'
      }
    })
    await expect(resume).resolves.toMatchObject({ session_id: 's1' })
    expect(delivered).toEqual([{ id: 'srq-9', replayed: true }])
  })
})
