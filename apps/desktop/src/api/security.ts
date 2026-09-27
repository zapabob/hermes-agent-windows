import { hermesApi, profileScoped } from './client'

export type SecurityVerdict = 'CLEAN' | 'MALICIOUS' | 'SCAN_ERROR' | 'SUSPICIOUS' | 'UNKNOWN'

export interface SecurityFinding {
  details: Record<string, unknown>
  name: string
  score: number
  source: string
  state: string
}

export interface SecurityScanResult {
  action: string
  cached: boolean
  engine_versions: Record<string, string>
  error: null | string
  findings: SecurityFinding[]
  path: string
  quarantine_id: null | string
  score: number
  sha256: string
  size: number
  verdict: SecurityVerdict
}

export interface SecurityEvent {
  action: string
  created_at: string
  details_json: string
  event_type: string
  id: number
  subject: string
  verdict: null | SecurityVerdict
}

export interface QuarantineItem {
  blob_name: string
  created_at: string
  deleted_at: null | string
  findings_json: string
  id: string
  engine_versions_json: string
  original_filename: string
  original_path: string
  restore_state?: string
  restored_at: null | string
  sha256: string
  size: number
  verdict: SecurityVerdict
}

export interface SecurityFeed {
  details_json: string
  name: string
  status: string
  updated_at: string
  version: string
}

export interface SecuritySummary {
  detections: number
  files_scanned: number
  last_scan: null | string
  last_signature_update: null | string
  quarantine_count: number
  quarantine_pending_count?: number
}

export interface SecurityStatus {
  auto_quarantine: boolean
  enabled: boolean
  engines: Record<string, string>
  error?: string
  feeds: SecurityFeed[]
  quarantine: QuarantineItem[]
  recent_events: SecurityEvent[]
  state: 'KNOWN' | 'UNKNOWN'
  summary: SecuritySummary
  vault_key_protection: string
  watch: { enabled: boolean; error?: string; pid: null | number; running: boolean }
}

export function getSecurityStatus(): Promise<SecurityStatus> {
  return hermesApi<SecurityStatus>({ ...profileScoped(), path: '/api/security/status' })
}

export function runSecurityScan(request: {
  path?: string
  scope: 'custom' | 'full' | 'quick'
  quarantine: boolean
}): Promise<{ results: SecurityScanResult[] }> {
  return hermesApi<{ results: SecurityScanResult[] }>({
    ...profileScoped(),
    path: '/api/security/scan',
    method: 'POST',
    body: { ...request, confirmed: request.quarantine },
    timeoutMs: request.scope === 'full' ? 600_000 : 180_000
  })
}

export function updateSecurityDefinitions(): Promise<{ ok: boolean; error?: string; state: string; version?: string }> {
  return hermesApi({
    ...profileScoped(),
    path: '/api/security/update',
    method: 'POST',
    body: { confirmed: true },
    timeoutMs: 600_000
  })
}

export function setSecurityWatch(action: 'disable' | 'enable'): Promise<{ ok: boolean }> {
  return hermesApi({
    ...profileScoped(),
    path: '/api/security/watch',
    method: 'POST',
    body: { action, confirmed: true }
  })
}

export function restoreQuarantineItem(id: string, force = false): Promise<{ ok: boolean; path: string }> {
  return hermesApi({
    ...profileScoped(),
    path: `/api/security/quarantine/${encodeURIComponent(id)}/restore`,
    method: 'POST',
    body: { confirmed: true, force }
  })
}

export function deleteQuarantineItem(id: string): Promise<{ deleted: boolean; id: string; ok: boolean }> {
  return hermesApi({
    ...profileScoped(),
    path: `/api/security/quarantine/${encodeURIComponent(id)}?confirmed=true`,
    method: 'DELETE'
  })
}
