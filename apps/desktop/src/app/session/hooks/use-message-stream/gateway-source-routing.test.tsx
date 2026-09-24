import { act, cleanup, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { GatewayEventPayload } from '@/lib/chat-messages/types'
import { $clarifyRequests, clearClarifyRequest } from '@/store/clarify'
import { $gateway, gatewayScope, setPrimaryGateway } from '@/store/gateway'
import { $mcpSetupRequests } from '@/store/mcp-setup'
import * as nativeNotifications from '@/store/native-notifications'
import { clearAllPrompts, sessionApprovalRequest, sessionSecretRequest, sessionSudoRequest } from '@/store/prompts'
import type { RpcEvent, SessionResumeResponse } from '@/types/hermes'

import { type MessageStreamHarness, renderMessageStream } from './test-harness'

const SID = 'session-source'
const SOURCE_CONNECTION = 'connection-source'
const SOURCE_PROFILE = 'profile-source'
const SOURCE_SCOPE = gatewayScope(SOURCE_CONNECTION, SOURCE_PROFILE)

const sourceRequest = vi.fn()
const activeRequest = vi.fn()

let stream: MessageStreamHarness

function sourceEvent(type: string, payload: Record<string, unknown>, sessionId = SID): void {
  act(() =>
    stream.handleEvent({
      connectionId: SOURCE_CONNECTION,
      payload,
      profile: SOURCE_PROFILE,
      session_id: sessionId,
      type
    })
  )
}

describe('gateway privileged reply source routing', () => {
  beforeEach(() => {
    sourceRequest.mockReset().mockResolvedValue({})
    activeRequest.mockReset().mockResolvedValue({})

    setPrimaryGateway({ connectionState: 'open', request: sourceRequest } as never, SOURCE_PROFILE, SOURCE_CONNECTION)
    $gateway.set({ connectionState: 'open', request: activeRequest } as never)

    clearClarifyRequest()
    $mcpSetupRequests.set({})
    clearAllPrompts()
    stream = renderMessageStream(SID)
  })

  afterEach(() => {
    cleanup()
    clearClarifyRequest()
    $mcpSetupRequests.set({})
    clearAllPrompts()
    $gateway.set(null)
    setPrimaryGateway(null)
    vi.restoreAllMocks()
  })

  it('parks every blocking request with the exact source scope', async () => {
    sourceEvent('clarify.request', {
      choices: ['yes', 'no'],
      question: 'Ship it?',
      request_id: 'clarify-single'
    })
    sourceEvent(
      'clarify.request',
      {
        questions: [
          { qid: 'q0', question: 'Environment?' },
          { qid: 'q1', question: 'Region?' }
        ],
        request_id: 'clarify-batch'
      },
      'session-batch'
    )
    sourceEvent('mcp.setup.request', {
      action: 'install',
      reason: 'Needed for this task',
      request_id: 'mcp-1',
      server: 'example'
    })
    sourceEvent('approval.request', {
      command: 'example command',
      description: 'Run the example',
      request_id: 'approval-1'
    })
    sourceEvent('sudo.request', { request_id: 'sudo-1' })
    sourceEvent('secret.request', {
      env_var: 'EXAMPLE_TOKEN',
      prompt: 'Enter token',
      request_id: 'secret-1'
    })

    expect($clarifyRequests.get()[SID]?.scope).toEqual(SOURCE_SCOPE)
    expect($clarifyRequests.get()['session-batch']?.scope).toEqual(SOURCE_SCOPE)
    expect($mcpSetupRequests.get()[SID]?.scope).toEqual(SOURCE_SCOPE)
    expect(sessionApprovalRequest(SID).get()?.scope).toEqual(SOURCE_SCOPE)
    expect(sessionSudoRequest(SID).get()?.scope).toEqual(SOURCE_SCOPE)
    expect(sessionSecretRequest(SID).get()?.scope).toEqual(SOURCE_SCOPE)

    await waitFor(() =>
      expect(sourceRequest).toHaveBeenCalledWith('approval.received', {
        request_id: 'approval-1',
        session_id: SID
      })
    )
    expect(activeRequest).not.toHaveBeenCalled()
  })

  it('retains the full strict control binding from the source approval event', async () => {
    const resource = `https://mcp.example.test/operations/${'source-bound-resource/'.repeat(24)}run`

    const control = {
      operation_id: 'op-source',
      intent_digest: 'b'.repeat(64),
      resource,
      grant_revision: 11
    } satisfies NonNullable<GatewayEventPayload['control']>

    const replayedApproval = { control } satisfies NonNullable<SessionResumeResponse['pending_approval']>
    const dispatchNotification = vi.spyOn(nativeNotifications, 'dispatchNativeNotification')

    sourceEvent('approval.request', {
      command: 'Hermes control operation op-source',
      control,
      description: 'Start approved run',
      request_id: 'approval-control-source',
      choices: ['once', 'deny']
    })

    await waitFor(() =>
      expect(sessionApprovalRequest(SID).get()?.control).toEqual({
        operationId: 'op-source',
        intentDigest: 'b'.repeat(64),
        resource,
        grantRevision: 11
      })
    )
    expect(replayedApproval.control).toEqual(control)
    await waitFor(() => expect(sourceRequest).toHaveBeenCalledWith('approval.received', {
      request_id: 'approval-control-source', session_id: SID
    }))
    const approvalNotification = dispatchNotification.mock.calls.find(([input]) => input.kind === 'approval')?.[0]
    expect(approvalNotification?.actions?.map(action => action.id)).toEqual(['reject'])
    expect(activeRequest).not.toHaveBeenCalled()
  })

  it('replays approval state through the source gateway', async () => {
    sourceRequest.mockImplementation(async (method: string) =>
      method === 'approval.pending'
        ? {
            approvals: [
              {
                command: 'example command',
                description: 'Run the example',
                request_id: 'approval-replayed'
              }
            ]
          }
        : {}
    )

    sourceEvent('session.info', {})

    await waitFor(() =>
      expect(sourceRequest).toHaveBeenCalledWith('approval.pending', {
        session_id: SID
      })
    )
    await waitFor(() => expect(sessionApprovalRequest(SID).get()?.requestId).toBe('approval-replayed'))

    expect(sessionApprovalRequest(SID).get()?.scope).toEqual(SOURCE_SCOPE)
    expect(activeRequest).not.toHaveBeenCalled()
  })

  it('returns desktop bridge replies only through the source gateway', async () => {
    sourceEvent('terminal.read.request', { request_id: 'terminal-1' })
    sourceEvent('preview.read.request', { request_id: 'preview-1' })
    sourceEvent('window.read.request', { request_id: 'window-1' })
    sourceEvent('tour.request', { request_id: 'tour-1' }, 'session-background')

    await waitFor(() => {
      const methods = sourceRequest.mock.calls.map(([method]) => method)

      expect(methods).toEqual(
        expect.arrayContaining(['terminal.read.respond', 'preview.read.respond', 'window.read.respond', 'tour.respond'])
      )
    })
    expect(activeRequest).not.toHaveBeenCalled()
  })

  it('fails closed when privileged events have no non-blank profile tag', async () => {
    const events: RpcEvent[] = [
      {
        connectionId: SOURCE_CONNECTION,
        payload: { choices: ['yes'], question: 'Ship it?', request_id: 'clarify-missing' },
        session_id: SID,
        type: 'clarify.request'
      },
      {
        connectionId: SOURCE_CONNECTION,
        payload: { request_id: 'approval-blank' },
        profile: '   ',
        session_id: SID,
        type: 'approval.request'
      },
      {
        connectionId: SOURCE_CONNECTION,
        payload: { request_id: 'terminal-missing' },
        session_id: SID,
        type: 'terminal.read.request'
      },
      {
        connectionId: SOURCE_CONNECTION,
        payload: {},
        profile: ' ',
        session_id: SID,
        type: 'session.info'
      }
    ]

    act(() => events.forEach(event => stream.handleEvent(event)))
    await Promise.resolve()

    expect($clarifyRequests.get()).toEqual({})
    expect(sessionApprovalRequest(SID).get()).toBeNull()
    expect(sourceRequest).not.toHaveBeenCalled()
    expect(activeRequest).not.toHaveBeenCalled()
  })
})
