import { describe, expect, it } from 'vitest'

import {
  journalStorageKey,
  mergePreparedSubmissionJournals,
  parsePreparedSubmissionJournal,
  type PreparedSubmissionJournal
} from './webapp-port-recovery'

describe('webapp-port recovery journal', () => {
  it('keys journals per origin and profile', () => {
    expect(journalStorageKey('http://127.0.0.1:9120', 'coder')).toContain('coder')
    expect(journalStorageKey('http://127.0.0.1:9120', 'coder')).not.toBe(
      journalStorageKey('http://127.0.0.1:9120', 'writer')
    )
  })

  it('merges two concurrent tab writes without dropping either entry', () => {
    const a: PreparedSubmissionJournal = {
      entries: [{ id: 'sub-a', profile: 'coder', createdAt: 1, payloadDigest: 'da' }]
    }

    const b: PreparedSubmissionJournal = {
      entries: [{ id: 'sub-b', profile: 'coder', createdAt: 2, payloadDigest: 'db' }]
    }

    const merged = mergePreparedSubmissionJournals(a, b)
    expect(merged.entries.map(e => e.id).sort()).toEqual(['sub-a', 'sub-b'])
  })

  it('keeps the newer digest when the same id is rewritten', () => {
    const a: PreparedSubmissionJournal = {
      entries: [{ id: 'sub-a', profile: 'coder', createdAt: 1, payloadDigest: 'old' }]
    }

    const b: PreparedSubmissionJournal = {
      entries: [{ id: 'sub-a', profile: 'coder', createdAt: 5, payloadDigest: 'new' }]
    }

    expect(mergePreparedSubmissionJournals(a, b).entries[0]?.payloadDigest).toBe('new')
  })

  it('parses corrupt storage as empty rather than throwing', () => {
    expect(parsePreparedSubmissionJournal('not-json').entries).toEqual([])
    expect(parsePreparedSubmissionJournal(null).entries).toEqual([])
  })
})
