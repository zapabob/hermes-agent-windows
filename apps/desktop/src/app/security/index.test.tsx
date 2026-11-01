// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SecurityPostureReport, SecurityStatus } from '@/hermes'
import { $gateway } from '@/store/gateway'

import { SecurityView } from './index'

const getSecurityStatus = vi.fn()
const runSecurityScan = vi.fn()
const runSecurityPostureAudit = vi.fn()
const updateSecurityDefinitions = vi.fn()
const setSecurityWatch = vi.fn()
const activation = vi.hoisted(() => ({ epoch: 0 }))

vi.mock('@/store/gateway', async () => {
  const { atom } = await import('nanostores')

  return {
    $gateway: atom<unknown>(null),
    $activeGatewayRoute: atom('default'),
    gatewayActivationEpoch: () => activation.epoch
  }
})

vi.mock('@/hermes', () => ({
  getApiRequestConnection: () => null,
  getApiRequestProfile: () => null,
  deleteQuarantineItem: vi.fn(),
  getSecurityStatus: () => getSecurityStatus(),
  restoreQuarantineItem: vi.fn(),
  runSecurityPostureAudit: (request: unknown) => runSecurityPostureAudit(request),
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

const posture: SecurityPostureReport = {
  schema: 'hermes-security-posture-v1',
  generated_at: '2026-11-01T00:00:00+00:00',
  overall: 'high_risk',
  counts: { fail: 2, pass: 5 },
  checks: [
    { id: 'approvals.interactive', status: 'fail', severity: 'high', observed: 'off', expected: 'smart' },
    {
      id: 'supply_chain.known_vulnerabilities',
      status: 'fail',
      severity: 'high',
      observed: { critical: 0, high: 1, moderate: 0 },
      expected: 0
    }
  ],
  host: {
    platform: 'win32',
    defender: {
      status: 'running',
      antivirus_enabled: true,
      realtime_enabled: true,
      signature_age_hours: 1
    },
    firewall: { profiles: { Public: { enabled: true, default_inbound_action: 'block' } } },
    disk: { free_bytes: 20 * 1024 ** 3 },
    listeners: {
      api_addresses: ['127.0.0.1'],
      api_owner_verified: true,
      loopback: 4,
      network: 2,
      records: []
    }
  },
  supply_chain: {
    total_components_scanned: 10,
    finding_count: 1,
    severity_counts: { HIGH: 1 },
    findings: [],
    findings_truncated: false
  }
}

beforeEach(() => {
  activation.epoch = 0
  $gateway.set(null)
  getSecurityStatus.mockResolvedValue(status)
  runSecurityScan.mockResolvedValue({ results: [] })
  runSecurityPostureAudit.mockResolvedValue(posture)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('SecurityView', () => {
  it('clears displayed results when a different connection serves the same profile', async () => {
    runSecurityScan.mockResolvedValue({
      results: [{ path: 'connection-a.exe', verdict: 'CLEAN', engine_health: 'HEALTHY', execution_decision: 'ALLOW' }]
    })
    render(<SecurityView />)
    fireEvent.click(await screen.findByRole('button', { name: 'Quick scan' }))
    expect(await screen.findByText('connection-a.exe')).toBeTruthy()
    act(() => {
      activation.epoch += 1
      $gateway.set({} as never)
    })
    await waitFor(() => expect(screen.queryByText('connection-a.exe')).toBeNull())
  })

  it('rejects array-shaped values even when their string conversion names a valid verdict', async () => {
    runSecurityScan.mockResolvedValue({
      results: [
        {
          path: 'malformed.exe',
          verdict: ['CLEAN'],
          file_verdict: ['CLEAN'],
          engine_health: ['HEALTHY'],
          execution_decision: ['ALLOW']
        }
      ]
    })
    render(<SecurityView />)
    fireEvent.click(await screen.findByRole('button', { name: 'Quick scan' }))
    expect(await screen.findByText('malformed.exe')).toBeTruthy()
    expect(screen.queryByText('HEALTHY')).toBeNull()
    expect(screen.queryByText('ALLOW')).toBeNull()
    expect(screen.queryByText('CLEAN')).toBeNull()
    expect(screen.getAllByText('UNKNOWN')).toHaveLength(2)
    expect(screen.getByText('REVIEW')).toBeTruthy()
  })
  it('discards an old scan after the active route changes away and back', async () => {
    let finish!: (value: unknown) => void
    runSecurityScan.mockReturnValue(
      new Promise(resolve => {
        finish = resolve
      })
    )
    render(<SecurityView />)
    fireEvent.click(await screen.findByRole('button', { name: 'Quick scan' }))
    await waitFor(() => expect(runSecurityScan).toHaveBeenCalled())
    activation.epoch += 2
    finish({
      results: [
        {
          path: 'old-scope.exe',
          verdict: 'CLEAN',
          file_verdict: 'CLEAN',
          engine_health: 'HEALTHY',
          execution_decision: 'ALLOW'
        }
      ]
    })
    await waitFor(() => expect(runSecurityScan).toHaveBeenCalledTimes(1))
    await act(async () => {
      await Promise.resolve()
    })
    expect(getSecurityStatus).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('old-scope.exe')).toBeNull()
  })
  it('keeps malicious verdict, degraded engines and blocked execution separate after scanning', async () => {
    runSecurityScan.mockResolvedValue({
      results: [
        {
          path: 'C:\\owned-fixture.exe',
          verdict: 'MALICIOUS',
          file_verdict: 'MALICIOUS',
          engine_health: 'DEGRADED',
          execution_decision: 'BLOCK',
          findings: [],
          error: null
        }
      ]
    })
    render(<SecurityView />)
    fireEvent.click(await screen.findByRole('button', { name: 'Quick scan' }))
    expect(await screen.findByText('DEGRADED')).toBeTruthy()
    expect(screen.getByText('MALICIOUS')).toBeTruthy()
    expect(screen.getByText('BLOCK')).toBeTruthy()
    expect(screen.getByText('File verdict')).toBeTruthy()
    expect(screen.getByText('Engine health')).toBeTruthy()
    expect(screen.getByText('Execution decision')).toBeTruthy()
  })

  it('does not infer healthy engines or allowed execution from a legacy clean verdict', async () => {
    runSecurityScan.mockResolvedValue({ results: [{ path: 'C:\\legacy.exe', verdict: 'CLEAN', findings: [] }] })
    render(<SecurityView />)
    fireEvent.click(await screen.findByRole('button', { name: 'Quick scan' }))
    expect(await screen.findByText('CLEAN')).toBeTruthy()
    expect(screen.getByText('UNKNOWN')).toBeTruthy()
    expect(screen.getByText('REVIEW')).toBeTruthy()
    expect(screen.queryByText('HEALTHY')).toBeNull()
    expect(screen.queryByText('ALLOW')).toBeNull()
  })

  it('shows an unknown or malformed three-axis value conservatively', async () => {
    runSecurityScan.mockResolvedValue({
      results: [
        {
          path: 'C:\\future.exe',
          verdict: 'UNKNOWN',
          file_verdict: 'FUTURE',
          engine_health: true,
          execution_decision: 'future-allow',
          findings: []
        }
      ]
    })
    render(<SecurityView />)
    fireEvent.click(await screen.findByRole('button', { name: 'Quick scan' }))
    expect(await screen.findByText('REVIEW')).toBeTruthy()
    expect(screen.getAllByText('UNKNOWN')).toHaveLength(2)
    expect(screen.queryByText('ALLOW')).toBeNull()
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

  it('runs a bounded posture audit and exposes failed controls without changing them', async () => {
    render(<SecurityView />)
    fireEvent.click(await screen.findByRole('button', { name: 'Run posture audit' }))

    await waitFor(() => expect(runSecurityPostureAudit).toHaveBeenCalledWith({ include_supply_chain: true }))
    expect(await screen.findByRole('heading', { name: 'Windows and agent posture' })).toBeTruthy()
    expect(screen.getByText('High risk')).toBeTruthy()
    expect(screen.getByText('Interactive approvals')).toBeTruthy()
    expect(screen.getByText('Known dependency vulnerabilities')).toBeTruthy()
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
