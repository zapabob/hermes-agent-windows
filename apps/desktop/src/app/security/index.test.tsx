// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SecurityStatus } from '@/hermes'

import { SecurityView } from './index'

const getSecurityStatus = vi.fn()
const runSecurityScan = vi.fn()
const updateSecurityDefinitions = vi.fn()
const setSecurityWatch = vi.fn()

vi.mock('@/hermes', () => ({
  deleteQuarantineItem: vi.fn(),
  getSecurityStatus: () => getSecurityStatus(),
  restoreQuarantineItem: vi.fn(),
  runSecurityScan: (request: unknown) => runSecurityScan(request),
  setSecurityWatch: (action: unknown) => setSecurityWatch(action),
  updateSecurityDefinitions: () => updateSecurityDefinitions()
}))

vi.mock('@/store/confirm', () => ({ confirm: vi.fn(async () => true) }))
vi.mock('@/store/notifications', () => ({ notify: vi.fn(), notifyError: vi.fn() }))

const status: SecurityStatus = {
  auto_quarantine: true,
  enabled: true,
  engines: {
    hash_reputation: 'empty',
    clamav: 'scanner_unavailable',
    yara: 'scanner_unavailable',
    static_heuristics: 'heuristics-1'
  },
  feeds: [],
  quarantine: [],
  recent_events: [],
  state: 'KNOWN',
  summary: {
    detections: 0,
    files_scanned: 0,
    last_scan: null,
    last_signature_update: null,
    quarantine_count: 0
  },
  vault_key_protection: 'windows_dpapi',
  watch: { enabled: false, pid: null, running: false }
}

beforeEach(() => {
  getSecurityStatus.mockResolvedValue(status)
  runSecurityScan.mockResolvedValue({ results: [] })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('SecurityView', () => {
  it('shows unknown when a profile has no security state', async () => {
    getSecurityStatus.mockResolvedValue({ ...status, state: 'UNKNOWN' })
    render(<SecurityView />)
    expect((await screen.findAllByText('Unknown')).length).toBeGreaterThan(0)
    expect(screen.queryByText('0')).toBeNull()
  })

  it('shows an unreadable store as unknown with an error banner', async () => {
    getSecurityStatus.mockResolvedValue({ ...status, state: 'UNKNOWN', error: 'security_store_unreadable' })
    render(<SecurityView />)
    expect((await screen.findAllByText('Unknown')).length).toBeGreaterThan(0)
    expect(screen.getByText('Security status failed to load')).toBeTruthy()
  })

  it('shows unavailable scanners as attention required instead of protected', async () => {
    render(<SecurityView />)
    expect(await screen.findByRole('heading', { level: 1, name: 'Security Center' })).toBeTruthy()
    expect(screen.getAllByText('Needs attention').length).toBeGreaterThan(0)
    expect(screen.getAllByText('scanner_unavailable')).toHaveLength(2)
  })

  it('runs an explicitly confirmed quick scan with quarantine enabled', async () => {
    render(<SecurityView />)
    fireEvent.click(await screen.findByRole('button', { name: 'Quick scan' }))
    await waitFor(() => expect(runSecurityScan).toHaveBeenCalledWith({ scope: 'quick', quarantine: true }))
  })

  it('shows durable scan totals, feed state, and exact detection evidence', async () => {
    getSecurityStatus.mockResolvedValue({
      ...status,
      feeds: [
        { details_json: '{}', name: 'clamav', status: 'ok', updated_at: '2026-08-27T00:00:00Z', version: 'daily-1' }
      ],
      recent_events: [
        {
          action: 'quarantined',
          created_at: '2026-08-27T00:00:00Z',
          details_json: JSON.stringify({
            findings: [{ name: 'Win.Test.Fixture', source: 'clamav', state: 'available' }]
          }),
          event_type: 'detection',
          id: 1,
          subject: 'C:\\fixture.exe',
          verdict: 'MALICIOUS'
        }
      ],
      summary: {
        detections: 1,
        files_scanned: 12,
        last_scan: '2026-08-27T00:00:00Z',
        last_signature_update: '2026-08-27T00:00:00Z',
        quarantine_count: 1
      }
    })
    render(<SecurityView />)
    expect(await screen.findByText('clamav: Win.Test.Fixture')).toBeTruthy()
    expect(screen.getByText('12')).toBeTruthy()
    expect(screen.getByText('Active feed status')).toBeTruthy()
  })
})
