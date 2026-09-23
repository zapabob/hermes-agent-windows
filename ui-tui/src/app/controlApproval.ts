import type { ApprovalReq } from '../types.js'

/** A control decision is addressed to the live human session and exact intent. */
export function approvalResponseRequest(
  request: ApprovalReq, sessionId: string | null, choice: string
): { method: string; params: Record<string, unknown>; strict: boolean } | null {
  if (!request.control) {
    return { method: 'approval.respond', params: { choice, session_id: sessionId }, strict: false }
  }

  const { intentDigest } = request.control

  if (
    !sessionId || !request.requestId || !/^[a-f0-9]{64}$/.test(intentDigest) ||
    (choice !== 'once' && choice !== 'deny')
  ) {
    return null
  }

  return {
    method: 'control_approval.respond', strict: true,
    params: { choice, session_id: sessionId, request_id: request.requestId, intent_digest: intentDigest }
  }
}
