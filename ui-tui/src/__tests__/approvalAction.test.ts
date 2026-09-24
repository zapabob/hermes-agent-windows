import { describe, expect, it } from 'vitest'

import { approvalResponseRequest } from '../app/controlApproval.js'
import { approvalAction, approvalOptions } from '../components/prompts.js'

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


describe('control approval response', () => {
  const control = { operationId: 'op-1', intentDigest: 'a'.repeat(64) }
  const req = { command: 'Hermes control operation op-1', description: 'Start run', requestId: 'req-1', control }

  it('binds once and deny to the dedicated owner RPC', () => {
    expect(approvalResponseRequest(req, 'human-session', 'once')).toEqual({
      method: 'control_approval.respond', strict: true,
      params: { choice: 'once', session_id: 'human-session', request_id: 'req-1', intent_digest: 'a'.repeat(64) }
    })
    expect(approvalResponseRequest(req, 'human-session', 'deny')?.method).toBe('control_approval.respond')
  })

  it('never sends persistent choices or incomplete bindings', () => {
    expect(approvalOptions({ ...req, choices: ['once', 'session', 'always', 'deny'] })).toEqual(['once', 'deny'])
    expect(approvalResponseRequest(req, 'human-session', 'always')).toBeNull()
    expect(approvalResponseRequest({ ...req, requestId: undefined }, 'human-session', 'once')).toBeNull()
    expect(approvalResponseRequest({ ...req, control: { ...control, intentDigest: 'bad' } }, 'human-session', 'once')).toBeNull()
  })

  it('keeps ordinary approvals on their existing RPC', () => {
    expect(approvalResponseRequest({ command: 'echo hi', description: 'ordinary' }, 's1', 'session')).toEqual({
      method: 'approval.respond', strict: false, params: { choice: 'session', session_id: 's1' }
    })
  })
})
