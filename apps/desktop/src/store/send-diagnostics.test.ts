import { afterEach, describe, expect, it, vi } from 'vitest'

import { $gateway } from '@/store/gateway'
import {
  $sendDiagnostics,
  confirmExportLocalDiagnostics,
  confirmSendDiagnostics,
  confirmUploadNousDiagnostics,
  dismissSendDiagnostics,
  requestSendDiagnostics
} from '@/store/send-diagnostics'

function stubGateway(
  request: (method: string, params?: Record<string, unknown>, timeout?: number) => Promise<unknown>
) {
  const original = $gateway.get()

  $gateway.set({ request } as never)

  return () => $gateway.set(original)
}

function stubDesktopLogs(lines: null | string[]) {
  const original = window.hermesDesktop

  Object.defineProperty(window, 'hermesDesktop', {
    configurable: true,
    value: lines ? { getRecentLogs: async () => ({ lines, path: '/tmp/desktop.log' }) } : undefined
  })

  return () => Object.defineProperty(window, 'hermesDesktop', { configurable: true, value: original })
}

describe('send-diagnostics store (local-first)', () => {
  afterEach(() => {
    $sendDiagnostics.set(null)
    vi.restoreAllMocks()
  })

  it('opens in consent phase without any gateway I/O', () => {
    const request = vi.fn()
    const restore = stubGateway(request)

    try {
      requestSendDiagnostics('layer: provider')

      expect($sendDiagnostics.get()).toEqual({
        destination: 'local',
        errorContext: 'layer: provider',
        phase: 'consent'
      })
      expect(request).not.toHaveBeenCalled()
    } finally {
      restore()
    }
  })

  it('primary confirm exports locally (no Nous RPC)', async () => {
    const request = vi.fn().mockResolvedValue({
      ok: true,
      path: 'C:/Users/x/.hermes/diagnostics-exports/Hermes-Diagnostics-20260908-120000.zip',
      filename: 'Hermes-Diagnostics-20260908-120000.zip',
      redacted: true,
      bytes: 12
    })

    const restoreGateway = stubGateway(request)
    const restoreDesktop = stubDesktopLogs(['boot ok', 'ws connected'])

    try {
      requestSendDiagnostics('layer: streaming\ncode: stream_drop')
      await confirmExportLocalDiagnostics()

      expect(request).toHaveBeenCalledTimes(1)
      const [method, params] = request.mock.calls[0]

      expect(method).toBe('diagnostics.export_local')
      expect(params.error_context).toContain('stream_drop')
      expect(params.extra_files['desktop.log']).toContain('ws connected')

      const state = $sendDiagnostics.get()

      expect(state?.phase).toBe('done')
      expect(state?.destination).toBe('local')
      expect(state?.result?.localPath).toContain('Hermes-Diagnostics-')
    } finally {
      restoreDesktop()
      restoreGateway()
    }
  })

  it('confirmSendDiagnostics aliases to local export', async () => {
    const request = vi.fn().mockResolvedValue({
      ok: true,
      path: '/tmp/Hermes-Diagnostics-20260908-120000.zip',
      filename: 'Hermes-Diagnostics-20260908-120000.zip'
    })
    const restoreGateway = stubGateway(request)
    const restoreDesktop = stubDesktopLogs(null)

    try {
      requestSendDiagnostics()
      await confirmSendDiagnostics()

      expect(request.mock.calls[0][0]).toBe('diagnostics.export_local')
    } finally {
      restoreDesktop()
      restoreGateway()
    }
  })

  it('secondary Nous upload stays opt-in and separate', async () => {
    const request = vi.fn().mockResolvedValue({
      ok: true,
      view_url: 'https://nas.example/view/x1',
      upload_id: 'x1'
    })
    const restoreGateway = stubGateway(request)
    const restoreDesktop = stubDesktopLogs(null)

    try {
      requestSendDiagnostics()
      await confirmUploadNousDiagnostics()

      expect(request.mock.calls[0][0]).toBe('diagnostics.share_nous')
      expect($sendDiagnostics.get()?.destination).toBe('nous')
      expect($sendDiagnostics.get()?.result?.viewUrl).toContain('nas.example')
    } finally {
      restoreDesktop()
      restoreGateway()
    }
  })

  it('surfaces local export failures inline', async () => {
    const request = vi.fn().mockResolvedValue({ ok: false, error: 'disk full' })
    const restoreGateway = stubGateway(request)
    const restoreDesktop = stubDesktopLogs(null)

    try {
      requestSendDiagnostics()
      await confirmExportLocalDiagnostics()

      const state = $sendDiagnostics.get()

      expect(state?.phase).toBe('error')
      expect(state?.error).toContain('disk full')
    } finally {
      restoreDesktop()
      restoreGateway()
    }
  })

  it('dismissal mid-export ignores stale completion', async () => {
    let resolveRequest: (value: unknown) => void = () => {}

    const request = vi.fn().mockImplementation(() => new Promise(resolve => (resolveRequest = resolve)))

    const restoreGateway = stubGateway(request as never)
    const restoreDesktop = stubDesktopLogs(null)

    try {
      requestSendDiagnostics()
      const pending = confirmExportLocalDiagnostics()

      await vi.waitFor(() => expect(request).toHaveBeenCalled())
      dismissSendDiagnostics()
      expect($sendDiagnostics.get()).toBeNull()

      resolveRequest({
        ok: true,
        path: '/tmp/Hermes-Diagnostics-stale.zip',
        filename: 'Hermes-Diagnostics-stale.zip'
      })
      await pending

      expect($sendDiagnostics.get()).toBeNull()

      requestSendDiagnostics('fresh')
      expect($sendDiagnostics.get()?.phase).toBe('consent')
    } finally {
      restoreDesktop()
      restoreGateway()
    }
  })
})
