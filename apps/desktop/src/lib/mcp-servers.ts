// Shape helpers for the `mcp_servers` config map, shared by everything that
// reads or writes it: the MCP tab editor, the paste-anything importer, and the
// `hermes://mcp/install` deeplink dialog. These agree on what a server entry
// looks like, so they belong in one place — a config written by one path has to
// be readable by the others.

export type McpServers = Record<string, Record<string, unknown>>

export const isServerShape = (value: Record<string, unknown>) =>
  typeof value.command === 'string' || typeof value.url === 'string'

/** Cursor/Claude write `type`; Hermes reads `transport`. Normalizing on the way
 *  in makes pasted configs behave identically under the CLI/TUI loader. */
export function normalizeEntry(entry: Record<string, unknown>): Record<string, unknown> {
  if (typeof entry.type === 'string' && entry.transport === undefined) {
    const { type, ...rest } = entry

    return { ...rest, transport: type }
  }

  return entry
}

// `String()` folds the value first: false → 'false', 0 / 0.0 / -0 → '0'; everything
// else (true, other numbers, null, absent, junk) lands outside this set and reads on.
const OFF_WORDS = new Set(['false', '0', 'no', 'off'])

/** Whether a server entry is on. Mirrors the backend's one reader
 *  (`tools/mcp_tool.py::mcp_server_enabled`): false/0 and the off words
 *  (any case, trimmed) are off; absent, `null`, `""` and junk are on.
 *  `mcp-enabled-cases.json` pins both sides to the same table, so the MCP page
 *  never shows a server on that the runtime skips. */
export const serverEnabled = (entry: Record<string, unknown>) =>
  !OFF_WORDS.has(String(entry.enabled).trim().toLowerCase())

/** The `mcp_servers` map out of a config record, or `{}` when absent/malformed. */
export function getServers(config: { mcp_servers?: unknown } | null): McpServers {
  const raw = config?.mcp_servers

  return raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as McpServers) : {}
}
