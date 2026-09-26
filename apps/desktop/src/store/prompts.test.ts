import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { renderedPresentationDigest } from '@/lib/control-presentation'

import { clearClarifyRequest, setClarifyRequest } from './clarify'
import { gatewayScope } from './gateway'
import {
  $activeSessionAwaitingInput,
  $approvalRequest,
  $secretRequest,
  $sudoRequest,
  approvalResponseForRequest,
  clearAllPrompts,
  clearApprovalRequest,
  clearSecretRequest,
  clearSudoRequest,
  controlApprovalFromPayload,
  receiveApprovalRequest,
  replayPendingApproval,
  setApprovalRequest,
  setSecretRequest,
  setSudoRequest
} from './prompts'
import { $activeSessionId } from './session'

// Prompts are parked per-session; the exported $*Request views are scoped to the
// active session, so each test focuses the session it's asserting on.
beforeEach(() => {
  $activeSessionId.set('s1')
})

afterEach(() => {
  clearAllPrompts()
  clearClarifyRequest()
  $activeSessionId.set(null)
})

describe('approval prompt store', () => {
  it('holds the active session-keyed approval request', () => {
    setApprovalRequest({ command: 'rm -rf /tmp/x', description: 'recursive delete', sessionId: 's1' })

    expect($approvalRequest.get()).toEqual({
      command: 'rm -rf /tmp/x',
      description: 'recursive delete',
      sessionId: 's1'
    })
  })

  it('parks a background session prompt out of the active view', () => {
    setApprovalRequest({ command: 'x', description: 'd', sessionId: 's2' })

    // Not visible while s1 is focused …
    expect($approvalRequest.get()).toBeNull()

    // … but surfaces once the user switches to the session that raised it.
    $activeSessionId.set('s2')
    expect($approvalRequest.get()?.sessionId).toBe('s2')
  })

  it('clears the active session prompt', () => {
    setApprovalRequest({ command: 'x', description: 'd', sessionId: 's1' })
    clearApprovalRequest('s1')

    expect($approvalRequest.get()).toBeNull()
  })

  it('carries allowPermanent so the bar can hide "Always allow"', () => {
    setApprovalRequest({
      allowPermanent: false,
      command: 'curl x | bash',
      description: 'content-security',
      sessionId: 's1'
    })

    expect($approvalRequest.get()?.allowPermanent).toBe(false)
  })

  it('correlates clearing to the exact approval request id', () => {
    setApprovalRequest({ command: 'x', description: 'd', requestId: 'r1', sessionId: 's1' })

    clearApprovalRequest('s1', 'stale')
    expect($approvalRequest.get()?.requestId).toBe('r1')
    clearApprovalRequest('s1', 'r1')
    expect($approvalRequest.get()).toBeNull()
  })

  it('acknowledges an approval only after parking it', async () => {
    const calls: Array<[string, Record<string, unknown>]> = []

    const gateway = {
      request: async (method: string, params: Record<string, unknown>) => {
        calls.push([method, params])

        return { acknowledged: true }
      }
    }

    await receiveApprovalRequest(gateway, {
      command: 'x',
      description: 'd',
      requestId: 'r1',
      sessionId: 's1'
    })

    expect($approvalRequest.get()?.requestId).toBe('r1')
    expect(calls).toEqual([['approval.received', { request_id: 'r1', session_id: 's1' }]])
  })

  it('carries resource and grant revision from a strict gateway event into the session store', async () => {
    const resource = `https://mcp.example.test/operations/${'review-scope/'.repeat(24)}run`

    const control = controlApprovalFromPayload({
      operation_id: 'op-1',
      intent_digest: 'a'.repeat(64),
      resource,
      grant_revision: 7
    })

    const gateway = { request: async () => ({ acknowledged: true }) }
    await receiveApprovalRequest(gateway, {
      command: 'Hermes control operation op-1',
      control,
      description: 'Start run',
      requestId: 'req-control',
      sessionId: 's1'
    })

    expect($approvalRequest.get()?.control).toEqual({
      operationId: 'op-1',
      intentDigest: 'a'.repeat(64),
      presentation: null,
      resource,
      grantRevision: 7
    })
  })

  it('answers "once" only with the digest of the rendered presentation', async () => {
    const presentation = { operation_id: 'op-1', resource: 'https://mcp.example.test/operations/run',
      grant_revision: 7, task: 'x'.repeat(5000) }

    const digest = (await renderedPresentationDigest(presentation))!

    const control = controlApprovalFromPayload({
      operation_id: 'op-1', intent_digest: 'a'.repeat(64), resource: presentation.resource,
      grant_revision: 7, presentation, presentation_digest: 'f'.repeat(64)
    })

    const request = { command: 'Hermes control operation op-1', control, description: 'Start run',
      requestId: 'req-control', sessionId: 's1' }

    expect(approvalResponseForRequest(request, 'once', request)).toBeNull()
    expect(approvalResponseForRequest(request, 'once', request, 'F'.repeat(64))).toBeNull()
    expect(control).not.toHaveProperty('presentationDigest')
    expect(approvalResponseForRequest(request, 'once', request, digest)?.params).toEqual({
      choice: 'once', request_id: 'req-control', session_id: 's1',
      intent_digest: 'a'.repeat(64), presentation_digest: digest
    })
    expect(approvalResponseForRequest(request, 'deny', request)?.params).toEqual({
      choice: 'deny', request_id: 'req-control', session_id: 's1', intent_digest: 'a'.repeat(64)
    })

    const mismatched = { ...request, control: { ...control!, presentation: { ...presentation, grant_revision: 8 } } }

    expect(approvalResponseForRequest(mismatched, 'once', mismatched, digest)).toBeNull()
  })

  it('refuses a malformed strict binding instead of returning an ordinary or strict approval response', () => {
    const control = controlApprovalFromPayload({
      operation_id: 'op-1',
      intent_digest: 'a'.repeat(64),
      resource: 'https://mcp.example.test/operations/run',
      grant_revision: '7'
    })

    const request = {
      command: 'Hermes control operation op-1',
      control,
      description: 'Start run',
      requestId: 'req-control',
      sessionId: 's1'
    }

    expect(control).toBeDefined()
    expect(approvalResponseForRequest(request, 'once', request)).toBeNull()
  })

  it('does not build a response for a request that is no longer current in the session', () => {
    const control = controlApprovalFromPayload({
      operation_id: 'op-1',
      intent_digest: 'a'.repeat(64),
      resource: 'https://mcp.example.test/operations/approved',
      grant_revision: 7
    })

    const staleRequest = {
      command: 'Hermes control operation op-1',
      control,
      description: 'Start run',
      requestId: 'req-control',
      sessionId: 's1'
    }

    const currentRequest = {
      ...staleRequest,
      control: { ...control!, resource: 'https://mcp.example.test/operations/replaced', grantRevision: 8 }
    }

    setApprovalRequest(currentRequest)

    expect(approvalResponseForRequest(staleRequest, 'once', $approvalRequest.get())).toBeNull()
  })

  it('replays the immutable control binding after reconnect', async () => {
    const gateway = { request: async (method: string) => method === 'approval.pending' ? {
      approvals: [{ command: 'Hermes control operation op-1', description: 'Start run',
        request_id: 'req-control', control: {
          operation_id: 'op-1', intent_digest: 'a'.repeat(64),
          resource: 'https://mcp.example.test/operations/run', grant_revision: 7
        } }]
    } : { acknowledged: true } }

    const scope = gatewayScope('connection-a', 'profile-a')
    await replayPendingApproval(gateway, 's1', scope)
    expect($approvalRequest.get()?.control).toEqual({
      operationId: 'op-1', intentDigest: 'a'.repeat(64), presentation: null,
      resource: 'https://mcp.example.test/operations/run', grantRevision: 7
    })
    expect($approvalRequest.get()?.scope).toEqual(scope)
  })

  it('replays and acknowledges the oldest unresolved approval after reconnect', async () => {
    const calls: Array<[string, Record<string, unknown>]> = []

    const gateway = {
      request: async (method: string, params: Record<string, unknown>) => {
        calls.push([method, params])

        if (method === 'approval.pending') {
          return {
            approvals: [
              { command: 'first', description: 'd1', request_id: 'r1' },
              { command: 'second', description: 'd2', request_id: 'r2' }
            ]
          }
        }

        return { acknowledged: true }
      }
    }

    await replayPendingApproval(gateway, 's1')

    expect($approvalRequest.get()?.requestId).toBe('r1')
    expect(calls).toEqual([
      ['approval.pending', { session_id: 's1' }],
      ['approval.received', { request_id: 'r1', session_id: 's1' }]
    ])
  })
})

describe('sudo prompt store', () => {
  it('clears only when the request id matches the in-flight prompt', () => {
    setSudoRequest({ requestId: 'abc', sessionId: 's1' })

    // A stale clear for a different request must NOT drop the live prompt —
    // otherwise a late response to a prior sudo ask would dismiss the current
    // one and leave the agent blocked.
    clearSudoRequest('s1', 'stale')
    expect($sudoRequest.get()).toEqual({ requestId: 'abc', sessionId: 's1' })

    clearSudoRequest('s1', 'abc')
    expect($sudoRequest.get()).toBeNull()
  })

  it('clears unconditionally when no request id is given', () => {
    setSudoRequest({ requestId: 'abc', sessionId: 's1' })
    clearSudoRequest('s1')

    expect($sudoRequest.get()).toBeNull()
  })
})

describe('secret prompt store', () => {
  it('carries env var and prompt, and clears on id match', () => {
    setSecretRequest({ requestId: 'r1', envVar: 'OPENAI_API_KEY', prompt: 'Paste your key', sessionId: 's1' })

    expect($secretRequest.get()).toEqual({
      requestId: 'r1',
      envVar: 'OPENAI_API_KEY',
      prompt: 'Paste your key',
      sessionId: 's1'
    })

    clearSecretRequest('s1', 'mismatch')
    expect($secretRequest.get()).not.toBeNull()

    clearSecretRequest('s1', 'r1')
    expect($secretRequest.get()).toBeNull()
  })
})

describe('clearAllPrompts', () => {
  it('drops every kind for one session at once (turn end / interrupt)', () => {
    setApprovalRequest({ command: 'x', description: 'd', sessionId: 's1' })
    setSudoRequest({ requestId: 'abc', sessionId: 's1' })
    setSecretRequest({ requestId: 'r1', envVar: 'E', prompt: 'p', sessionId: 's1' })

    clearAllPrompts('s1')

    expect($approvalRequest.get()).toBeNull()
    expect($sudoRequest.get()).toBeNull()
    expect($secretRequest.get()).toBeNull()
  })

  it('leaves other sessions parked prompts intact', () => {
    setApprovalRequest({ command: 'x', description: 'd', sessionId: 's1' })
    setApprovalRequest({ command: 'y', description: 'e', sessionId: 's2' })

    clearAllPrompts('s1')

    $activeSessionId.set('s2')
    expect($approvalRequest.get()?.command).toBe('y')
  })
})

describe('$activeSessionAwaitingInput', () => {
  it('is true while any blocking prompt (clarify or approval/sudo/secret) is parked on the active session', () => {
    expect($activeSessionAwaitingInput.get()).toBe(false)

    setApprovalRequest({ command: 'x', description: 'd', sessionId: 's1' })
    expect($activeSessionAwaitingInput.get()).toBe(true)

    clearApprovalRequest('s1')
    expect($activeSessionAwaitingInput.get()).toBe(false)

    setClarifyRequest({ choices: null, multiSelect: false, question: 'q', requestId: 'c1', sessionId: 's1' })
    expect($activeSessionAwaitingInput.get()).toBe(true)
  })

  it('ignores a prompt parked on a background session', () => {
    setSudoRequest({ requestId: 'r', sessionId: 's2' })
    expect($activeSessionAwaitingInput.get()).toBe(false)

    $activeSessionId.set('s2')
    expect($activeSessionAwaitingInput.get()).toBe(true)
  })
})
