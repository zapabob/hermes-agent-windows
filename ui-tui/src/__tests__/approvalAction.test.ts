import { describe, expect, it } from 'vitest'

import { approvalResponseRequest } from '../app/controlApproval.js'
import { approvalAction, approvalOptions, controlPresentationLines } from '../components/prompts.js'
import { renderedPresentationDigest } from '../lib/controlPresentation.js'

describe('approvalAction — pure key dispatch for ApprovalPrompt', () => {
  it('maps Esc to deny — parity with global Ctrl+C cancellation', () => {
    expect(approvalAction('', { escape: true }, 0)).toEqual({ kind: 'choose', choice: 'deny' })
    expect(approvalAction('', { escape: true }, 2)).toEqual({ kind: 'choose', choice: 'deny' })
  })

  it('maps number keys 1..4 to once/session/always/deny in registration order', () => {
    expect(approvalAction('1', {}, 0)).toEqual({ kind: 'choose', choice: 'once' })
    expect(approvalAction('2', {}, 0)).toEqual({ kind: 'choose', choice: 'session' })
    expect(approvalAction('3', {}, 0)).toEqual({ kind: 'choose', choice: 'always' })
    expect(approvalAction('4', {}, 0)).toEqual({ kind: 'choose', choice: 'deny' })
  })

  it('ignores out-of-range numbers', () => {
    expect(approvalAction('0', {}, 1)).toEqual({ kind: 'noop' })
    expect(approvalAction('5', {}, 1)).toEqual({ kind: 'noop' })
    expect(approvalAction('9', {}, 1)).toEqual({ kind: 'noop' })
  })

  it('confirms the current selection on Enter', () => {
    expect(approvalAction('', { return: true }, 0)).toEqual({ kind: 'choose', choice: 'once' })
    expect(approvalAction('', { return: true }, 3)).toEqual({ kind: 'choose', choice: 'deny' })
  })

  it('moves selection up/down within bounds', () => {
    expect(approvalAction('', { upArrow: true }, 2)).toEqual({ kind: 'move', delta: -1 })
    expect(approvalAction('', { downArrow: true }, 1)).toEqual({ kind: 'move', delta: 1 })
  })

  it('clamps selection movement at the edges', () => {
    expect(approvalAction('', { upArrow: true }, 0)).toEqual({ kind: 'noop' })
    expect(approvalAction('', { downArrow: true }, 3)).toEqual({ kind: 'noop' })
  })

  it('Esc beats numeric/return — denying is always the first interpretation', () => {
    // If a terminal somehow delivers Esc + a digit in the same event, deny
    // wins.  Documents the precedence so a future refactor doesn't flip it.
    expect(approvalAction('1', { escape: true }, 0)).toEqual({ kind: 'choose', choice: 'deny' })
    expect(approvalAction('', { escape: true, return: true }, 1)).toEqual({ kind: 'choose', choice: 'deny' })
  })

  it('returns noop for unrelated keystrokes (printable letters etc.)', () => {
    expect(approvalAction('a', {}, 0)).toEqual({ kind: 'noop' })
    expect(approvalAction(' ', {}, 0)).toEqual({ kind: 'noop' })
  })

  it('respects a reduced option set when permanent allow is disabled', () => {
    // tirith content-security warning present → no "always"; the 3-item set is
    // once/session/deny, so 3 maps to deny and 4 is out of range.
    const opts = ['once', 'session', 'deny'] as const

    expect(approvalAction('3', {}, 0, opts)).toEqual({ kind: 'choose', choice: 'deny' })
    expect(approvalAction('4', {}, 0, opts)).toEqual({ kind: 'noop' })
    expect(approvalAction('', { downArrow: true }, 2, opts)).toEqual({ kind: 'noop' })
    expect(approvalAction('', { return: true }, 2, opts)).toEqual({ kind: 'choose', choice: 'deny' })
  })

  it('offers only once and deny for Smart DENY owner override', () => {
    const opts = approvalOptions({
      allowPermanent: true,
      command: 'rm -rf /',
      description: 'blocked',
      smartDenied: true
    })

    expect(opts).toEqual(['once', 'deny'])
    expect(approvalAction('2', {}, 0, opts)).toEqual({ kind: 'choose', choice: 'deny' })
    expect(approvalAction('3', {}, 0, opts)).toEqual({ kind: 'noop' })
  })

  it('uses explicit gateway choices as the prompt contract', () => {
    expect(
      approvalOptions({
        allowPermanent: true,
        choices: ['once', 'deny'],
        command: 'rm -rf /',
        description: 'blocked'
      })
    ).toEqual(['once', 'deny'])
  })
})

// Shared with tests/control_mcp/test_review_approval_binding.py: the host digests
// the same presentation, so both sides must canonicalise byte-identically.
const PARITY_FIXTURE = {
  task: 'line1\nline2 "quoted" \\ tab\t ctrl\u0001 \u65e5\u672c\u8a9e \u2028 \u{1F600}',
  resource: 'https://hermes.invalid/control/mcp',
  kind: 'start_engineering_run',
  grant_revision: 7,
  expires_at: 1_700_000_000
}

describe('control presentation digest', () => {
  it('matches the host canonicalisation for the shared parity fixture', () => {
    expect(renderedPresentationDigest(PARITY_FIXTURE)).toBe(
      'c0e7ed6e0c659141be826c9ca6af6dd4a62bf96776dcc8d401440c8cea47eba3'
    )
  })

  it('distinguishes presentations that share a long rendered prefix', () => {
    const prefix = 'x'.repeat(5000)

    expect(renderedPresentationDigest({ task: `${prefix}a` })).not.toBe(
      renderedPresentationDigest({ task: `${prefix}b` })
    )
  })

  it.each([[{ value: 1.5 }], [{ value: 2 ** 60 }], [[1]], [null]])('refuses non-canonical input %#', value => {
    expect(renderedPresentationDigest(value)).toBeNull()
  })
})

describe('control approval response', () => {
  const presentation = { operation_id: 'op-1', task: 'Start run' }

  const control = { operationId: 'op-1', intentDigest: 'a'.repeat(64), presentation }

  const req = { command: 'Hermes control operation op-1', description: 'Start run', requestId: 'req-1', control }

  it('binds once and deny to the dedicated owner RPC', () => {
    expect(approvalResponseRequest(req, 'human-session', 'once')).toEqual({
      method: 'control_approval.respond',
      strict: true,
      params: {
        choice: 'once',
        session_id: 'human-session',
        request_id: 'req-1',
        intent_digest: 'a'.repeat(64),
        presentation_digest: renderedPresentationDigest(presentation)
      }
    })
    expect(approvalResponseRequest(req, 'human-session', 'deny')).toEqual({
      method: 'control_approval.respond',
      strict: true,
      params: { choice: 'deny', session_id: 'human-session', request_id: 'req-1', intent_digest: 'a'.repeat(64) }
    })
  })

  it('sends the digest of what it rendered, never a host-supplied one', () => {
    const forged = { ...req, control: { ...control, presentationDigest: 'f'.repeat(64) } }

    expect(approvalResponseRequest(forged, 'human-session', 'once')?.params.presentation_digest).toBe(
      renderedPresentationDigest(presentation)
    )
  })

  it('refuses "once" for a missing, foreign or non-canonical projection', () => {
    const foreign = { ...req, control: { ...control, presentation: { ...presentation, operation_id: 'op-2' } } }
    const missing = { ...req, control: { ...control, presentation: null } }
    const noncanonical = { ...req, control: { ...control, presentation: { ...presentation, ratio: 1.5 } } }

    for (const request of [foreign, missing, noncanonical]) {
      expect(approvalResponseRequest(request, 'human-session', 'once')).toBeNull()
      expect(approvalOptions(request)).toEqual(['deny'])
      expect(approvalResponseRequest(request, 'human-session', 'deny')?.method).toBe('control_approval.respond')
    }
  })

  it('shows a value that fits in full, including a tail that distinguishes it', () => {
    const task = `${'shared prefix '.repeat(40)}TAIL-MARKER`
    const full = { ...presentation, task, workspace_id: 'w1' }
    const request = { ...req, control: { ...control, presentation: full } }
    const lines = controlPresentationLines(request.control, 60)

    expect(lines.some(line => line.startsWith('operation_id: op-1'))).toBe(true)
    expect(lines.some(line => line.startsWith('workspace_id: w1'))).toBe(true)
    expect(lines.join('')).toContain('TAIL-MARKER')
    expect(lines.at(-1)).toBe(`presentation_digest: ${renderedPresentationDigest(full)}`)
    expect(approvalOptions(request)).toEqual(['once', 'deny'])
  })

  it('offers only deny when a value is too long to show in full', () => {
    const tooLong = { ...presentation, task: `${'long task prefix '.repeat(200)}TAIL-MARKER` }
    const tooManyLines = { ...presentation, task: `${'line\n'.repeat(20)}TAIL-MARKER` }

    for (const shown of [tooLong, tooManyLines]) {
      const request = { ...req, control: { ...control, presentation: shown } }
      const lines = controlPresentationLines(request.control, 60)

      expect(lines.join('\n')).not.toContain('TAIL-MARKER')
      expect(lines.some(line => line.includes('only deny is offered'))).toBe(true)
      expect(lines.at(-1)).toContain('approval unavailable in this terminal')
      expect(approvalOptions(request)).toEqual(['deny'])
      expect(approvalResponseRequest(request, 'human-session', 'once')).toBeNull()
    }
  })
  it('never sends persistent choices or incomplete bindings', () => {
    expect(approvalOptions({ ...req, choices: ['once', 'session', 'always', 'deny'] })).toEqual(['once', 'deny'])
    expect(approvalResponseRequest(req, 'human-session', 'always')).toBeNull()
    expect(approvalResponseRequest({ ...req, requestId: undefined }, 'human-session', 'once')).toBeNull()
    expect(
      approvalResponseRequest({ ...req, control: { ...control, intentDigest: 'bad' } }, 'human-session', 'once')
    ).toBeNull()
  })

  it('keeps ordinary approvals on their existing RPC', () => {
    expect(approvalResponseRequest({ command: 'echo hi', description: 'ordinary' }, 's1', 'session')).toEqual({
      method: 'approval.respond',
      strict: false,
      params: { choice: 'session', session_id: 's1' }
    })
  })
})
