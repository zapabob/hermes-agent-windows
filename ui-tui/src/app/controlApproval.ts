import { isHex64, renderedPresentationDigest } from '../lib/controlPresentation.js'
import type { ApprovalReq } from '../types.js'

type ControlBinding = NonNullable<ApprovalReq['control']>
type Presentation = Record<string, unknown>

// The terminal prompt has no scroll region, so it only offers "once" for a
// projection it can show in full. The limits do not depend on terminal width,
// so the prompt and the answer path always agree.
export const PRESENTATION_VALUE_CHARS = 800
export const PRESENTATION_VALUE_LINES = 12

export const presentationValueText = (value: unknown): string =>
  typeof value === 'string' ? value : value === null || value === undefined ? '—' : JSON.stringify(value)

export const presentationValueFits = (value: unknown): boolean => {
  const text = presentationValueText(value)

  return text.length <= PRESENTATION_VALUE_CHARS && text.split('\n').length <= PRESENTATION_VALUE_LINES
}

const digests = new WeakMap<Presentation, null | string>()

/**
 * The digest of the projection this prompt renders in full, or null when "once"
 * must not be offered (missing, foreign, too long to show, or not canonical).
 * The host withholds its own digest and compares this one against its binding.
 */
export function renderedControlDigest(control: ControlBinding): null | string {
  const presentation = control.presentation

  if (!presentation || presentation.operation_id !== control.operationId) {
    return null
  }

  if (!digests.has(presentation)) {
    digests.set(
      presentation,
      Object.values(presentation).every(presentationValueFits) ? renderedPresentationDigest(presentation) : null
    )
  }

  return digests.get(presentation) ?? null
}

/** A control decision is addressed to the live human session and exact intent. */
export function approvalResponseRequest(
  request: ApprovalReq, sessionId: string | null, choice: string
): { method: string; params: Record<string, unknown>; strict: boolean } | null {
  if (!request.control) {
    return { method: 'approval.respond', params: { choice, session_id: sessionId }, strict: false }
  }

  const { intentDigest } = request.control
  const digest = choice === 'once' ? renderedControlDigest(request.control) : null

  if (
    !sessionId || !request.requestId || !isHex64(intentDigest) ||
    (choice !== 'once' && choice !== 'deny') ||
    (choice === 'once' && !isHex64(digest))
  ) {
    return null
  }

  return {
    method: 'control_approval.respond', strict: true,
    params: {
      choice, session_id: sessionId, request_id: request.requestId, intent_digest: intentDigest,
      ...(choice === 'once' ? { presentation_digest: digest } : {})
    }
  }
}
