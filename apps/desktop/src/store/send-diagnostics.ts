// Diagnostics export — consent-gated local-first debug bundle.
//
// Windows Workstation Edition primary action is LOCAL ZIP export via
// diagnostics.export_local (collector → forced redaction → disk). Nous upload
// (diagnostics.share_nous) remains an explicit secondary opt-in and is never
// the default button.
//
// Consent is per-action and explicit — no "always allow". Generation fence:
// dismissing mid-export/upload ignores stale completions.
import { atom } from 'nanostores'

import { $gateway } from '@/store/gateway'

export interface SendDiagnosticsResult {
  bytes?: number
  expiresAt?: string
  filename?: string
  localPath?: string
  uploadId?: string
  viewUrl?: string
}

export type DiagnosticsDestination = 'local' | 'nous'

export interface SendDiagnosticsState {
  /** Active destination for the in-flight / just-completed action. */
  destination: DiagnosticsDestination
  /** Short text describing the failure that prompted the report. */
  errorContext?: string
  error?: string
  phase: 'consent' | 'done' | 'error' | 'exporting' | 'uploading'
  result?: SendDiagnosticsResult
}

export const $sendDiagnostics = atom<SendDiagnosticsState | null>(null)

let generation = 0

/** Open the consent modal. No network I/O and no disk write until confirm. */
export function requestSendDiagnostics(errorContext?: string): void {
  generation += 1
  $sendDiagnostics.set({ destination: 'local', errorContext, phase: 'consent' })
}

export function dismissSendDiagnostics(): void {
  generation += 1
  $sendDiagnostics.set(null)
}

interface ExportLocalResponse {
  bytes?: number
  error?: string
  filename?: string
  ok: boolean
  path?: string
  redacted?: boolean
}

interface ShareNousResponse {
  error?: string
  expires_at?: string
  ok: boolean
  upload_id?: string
  view_url?: string
}

async function collectLocalExtras(): Promise<Record<string, string>> {
  try {
    const logs = await window.hermesDesktop?.getRecentLogs?.()
    const lines = Array.isArray(logs?.lines) ? logs.lines : []

    return lines.length ? { 'desktop.log': lines.join('\n') } : {}
  } catch {
    return {}
  }
}

const ACTION_TIMEOUT_MS = 120_000

function stillCurrent(startedGeneration: number): boolean {
  return generation === startedGeneration
}

async function buildParams(errorContext?: string): Promise<Record<string, unknown>> {
  const extraFiles = await collectLocalExtras()

  return {
    ...(errorContext ? { error_context: errorContext } : {}),
    ...(Object.keys(extraFiles).length ? { extra_files: extraFiles } : {})
  }
}

/** Primary action — local ZIP export. No network. */
export async function confirmExportLocalDiagnostics(): Promise<void> {
  const current = $sendDiagnostics.get()

  if (!current || current.phase !== 'consent') {
    return
  }

  const startedGeneration = generation

  $sendDiagnostics.set({ ...current, destination: 'local', phase: 'exporting' })

  try {
    const gateway = $gateway.get()

    if (!gateway) {
      throw new Error('Hermes gateway unavailable')
    }

    const params = await buildParams(current.errorContext)

    if (!stillCurrent(startedGeneration)) {
      return
    }

    const response = await gateway.request<ExportLocalResponse>(
      'diagnostics.export_local',
      params,
      ACTION_TIMEOUT_MS
    )

    if (!stillCurrent(startedGeneration)) {
      return
    }

    if (!response.ok || !response.path) {
      throw new Error(response.error || 'local export failed')
    }

    $sendDiagnostics.set({
      ...current,
      destination: 'local',
      phase: 'done',
      result: {
        bytes: response.bytes,
        filename: response.filename,
        localPath: response.path
      }
    })
  } catch (error) {
    if (!stillCurrent(startedGeneration)) {
      return
    }

    $sendDiagnostics.set({
      ...current,
      destination: 'local',
      error: error instanceof Error ? error.message : String(error),
      phase: 'error'
    })
  }
}

/**
 * Secondary opt-in — Nous-internal upload.
 * Kept for compatibility with official support channels; never the default.
 */
export async function confirmUploadNousDiagnostics(): Promise<void> {
  const current = $sendDiagnostics.get()

  if (!current || current.phase !== 'consent') {
    return
  }

  const startedGeneration = generation

  $sendDiagnostics.set({ ...current, destination: 'nous', phase: 'uploading' })

  try {
    const gateway = $gateway.get()

    if (!gateway) {
      throw new Error('Hermes gateway unavailable')
    }

    const params = await buildParams(current.errorContext)

    if (!stillCurrent(startedGeneration)) {
      return
    }

    const response = await gateway.request<ShareNousResponse>(
      'diagnostics.share_nous',
      params,
      ACTION_TIMEOUT_MS
    )

    if (!stillCurrent(startedGeneration)) {
      return
    }

    if (!response.ok) {
      throw new Error(response.error || 'upload failed')
    }

    $sendDiagnostics.set({
      ...current,
      destination: 'nous',
      phase: 'done',
      result: {
        expiresAt: response.expires_at,
        uploadId: response.upload_id,
        viewUrl: response.view_url
      }
    })
  } catch (error) {
    if (!stillCurrent(startedGeneration)) {
      return
    }

    $sendDiagnostics.set({
      ...current,
      destination: 'nous',
      error: error instanceof Error ? error.message : String(error),
      phase: 'error'
    })
  }
}

/** @deprecated Prefer confirmExportLocalDiagnostics — kept as alias for callers. */
export async function confirmSendDiagnostics(): Promise<void> {
  await confirmExportLocalDiagnostics()
}
