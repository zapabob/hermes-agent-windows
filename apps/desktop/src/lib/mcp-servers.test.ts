import { describe, expect, it } from 'vitest'

import cases from './mcp-enabled-cases.json'
import { serverEnabled } from './mcp-servers'

// The backend reads the same table (tests/tools/test_mcp_enabled_reader.py), so
// the MCP page and the runtime cannot disagree about whether a server is on.
describe('serverEnabled', () => {
  it.each(cases)('%j', ({ on, ...entry }) => {
    expect(serverEnabled({ command: 'x', ...entry })).toBe(on)
  })
})
