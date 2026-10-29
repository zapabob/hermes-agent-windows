/**
 * W08: durable prepared-submission journal helpers for browser tabs.
 * Concurrent tabs must not clobber each other via unprotected RMW of one key.
 */
export interface PreparedSubmissionEntry {
  id: string
  profile: string
  createdAt: number
  payloadDigest: string
}

export interface PreparedSubmissionJournal {
  entries: PreparedSubmissionEntry[]
}

const JOURNAL_PREFIX = 'hermes.webapp.prepared-submissions.v1'

export function journalStorageKey(origin: string, profile: string): string {
  return `${JOURNAL_PREFIX}:${origin}:${profile}`
}

/** Merge *incoming* into *existing* by id; never drop an entry the other tab still holds. */
export function mergePreparedSubmissionJournals(
  existing: PreparedSubmissionJournal,
  incoming: PreparedSubmissionJournal
): PreparedSubmissionJournal {
  const byId = new Map<string, PreparedSubmissionEntry>()

  for (const entry of existing.entries) {
    byId.set(entry.id, entry)
  }

  for (const entry of incoming.entries) {
    const prior = byId.get(entry.id)

    if (!prior || entry.createdAt >= prior.createdAt) {
      byId.set(entry.id, entry)
    }
  }

  return {
    entries: [...byId.values()].sort((a, b) => a.createdAt - b.createdAt)
  }
}

export function parsePreparedSubmissionJournal(raw: string | null): PreparedSubmissionJournal {
  if (!raw) {
    return { entries: [] }
  }

  try {
    const parsed = JSON.parse(raw) as PreparedSubmissionJournal

    if (!parsed || !Array.isArray(parsed.entries)) {
      return { entries: [] }
    }

    return {
      entries: parsed.entries.filter(
        (e): e is PreparedSubmissionEntry =>
          !!e &&
          typeof e.id === 'string' &&
          typeof e.profile === 'string' &&
          typeof e.createdAt === 'number' &&
          typeof e.payloadDigest === 'string'
      )
    }
  } catch {
    return { entries: [] }
  }
}
