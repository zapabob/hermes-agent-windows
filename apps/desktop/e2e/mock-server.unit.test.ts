import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { INTERIM_TEXTS, MOCK_REPLY, type MockServer, restartMockServer, startMockServer } from './mock-server'

const TRIGGER = 'E2E_INTERIM_TRIGGER'

function titleRequest() {
  return {
    model: 'mock-model',
    messages: [
      { role: 'system', content: 'You name chat sessions. Reply with a JSON title.' },
      { role: 'user', content: TRIGGER }
    ],
    max_tokens: 64,
    temperature: 0.3,
    response_format: {
      type: 'json_schema',
      json_schema: {
        name: 'session_title',
        strict: true,
        schema: {
          type: 'object',
          properties: { title: { type: 'string' } },
          required: ['title'],
          additionalProperties: false
        }
      }
    },
    stream: false
  }
}

function chatRequest() {
  return {
    model: 'mock-model',
    messages: [{ role: 'user', content: TRIGGER }],
    tools: [
      {
        type: 'function',
        function: {
          name: 'todo',
          parameters: { type: 'object', properties: {}, additionalProperties: false }
        }
      }
    ],
    stream: true
  }
}

async function postCompletion(mock: MockServer, body: Record<string, unknown>): Promise<Response> {
  return fetch(`${mock.url}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
}

async function readStream(response: Response): Promise<{ text: string; toolCallCount: number }> {
  const chunks = (await response.text()).split('\n')
  let text = ''
  let toolCallCount = 0

  for (const line of chunks) {
    if (!line.startsWith('data: ') || line === 'data: [DONE]') {
      continue
    }

    const event = JSON.parse(line.slice('data: '.length)) as {
      choices?: Array<{ delta?: { content?: string; tool_calls?: unknown[] } }>
    }

    const delta = event.choices?.[0]?.delta
    text += delta?.content ?? ''
    toolCallCount += delta?.tool_calls?.length ?? 0
  }

  return { text, toolCallCount }
}

describe('interim mock script routing', () => {
  let mock: MockServer

  beforeEach(async () => {
    restartMockServer()
    mock = await startMockServer()
  })

  afterEach(async () => {
    await mock?.close()
    restartMockServer()
  })

  it('does not let a non-streaming title request consume tool-bearing chat turns', async () => {
    const titleResponse = await postCompletion(mock, titleRequest())
    expect(titleResponse.ok).toBe(true)

    const titleCompletion = await titleResponse.json() as {
      choices?: Array<{ message?: { content?: string; tool_calls?: unknown[] } }>
    }

    expect(mock.receivedRequests[0]).toMatchObject({ stream: false, max_tokens: 64, temperature: 0.3 })
    expect(mock.receivedRequests[0]).not.toHaveProperty('tools')
    expect(titleCompletion.choices?.[0]?.message?.content).toBe(MOCK_REPLY)
    expect(titleCompletion.choices?.[0]?.message?.tool_calls).toBeUndefined()

    const firstChatResponse = await postCompletion(mock, chatRequest())
    expect(firstChatResponse.ok).toBe(true)
    const firstChat = await readStream(firstChatResponse)
    expect(firstChat.text).toBe(INTERIM_TEXTS.interims[0])
    expect(firstChat.toolCallCount).toBe(1)

    const secondChatResponse = await postCompletion(mock, chatRequest())
    expect(secondChatResponse.ok).toBe(true)
    const secondChat = await readStream(secondChatResponse)
    expect(secondChat.text).toBe(INTERIM_TEXTS.interims[1])
    expect(secondChat.toolCallCount).toBe(1)
  })
})
