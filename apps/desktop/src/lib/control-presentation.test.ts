import { describe, expect, it } from 'vitest'

import { canonicalPresentationJson, renderedPresentationDigest } from './control-presentation'

// Shared with tests/control_mcp/test_review_approval_binding.py: the host digests
// the same presentation, so both sides must canonicalise byte-identically.
const PARITY_FIXTURE = {
  task: 'line1\nline2 "quoted" \\ tab\t ctrl\u0001 \u65e5\u672c\u8a9e \u2028 \u{1F600}',
  resource: 'https://hermes.invalid/control/mcp',
  kind: 'start_engineering_run',
  grant_revision: 7,
  expires_at: 1_700_000_000
}

const PARITY_DIGEST = 'c0e7ed6e0c659141be826c9ca6af6dd4a62bf96776dcc8d401440c8cea47eba3'

describe('control presentation digest', () => {
  it('matches the host canonicalisation for the shared parity fixture', async () => {
    expect(await renderedPresentationDigest(PARITY_FIXTURE)).toBe(PARITY_DIGEST)
  })

  it('distinguishes presentations that share a long rendered prefix', async () => {
    const prefix = 'x'.repeat(5000)
    const first = await renderedPresentationDigest({ ...PARITY_FIXTURE, task: `${prefix}a` })
    const second = await renderedPresentationDigest({ ...PARITY_FIXTURE, task: `${prefix}b` })

    expect(first).not.toBeNull()
    expect(first).not.toBe(second)
  })

  it('orders keys independently of insertion order', () => {
    expect(canonicalPresentationJson({ b: 1, a: { d: null, c: true } })).toBe('{"a":{"c":true,"d":null},"b":1}')
  })

  it.each([
    ['a float', { value: 1.5 }],
    ['an unsafe integer', { value: 2 ** 60 }],
    ['a non-plain object', { value: new Date(0) }],
    ['an array root', [1]],
    ['null', null]
  ])('refuses to derive a digest from %s', async (_label, value) => {
    expect(await renderedPresentationDigest(value)).toBeNull()
  })
})
