import type * as React from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { PAGE_INSET_X } from '@/app/layout-constants'
import { PageLoader } from '@/components/page-loader'
import { StatusDot, type StatusTone } from '@/components/status-dot'
import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { ErrorBanner } from '@/components/ui/error-state'
import { Input } from '@/components/ui/input'
import {
  deleteQuarantineItem,
  getSecurityStatus,
  type QuarantineItem,
  restoreQuarantineItem,
  runSecurityScan,
  type SecurityStatus,
  setSecurityWatch,
  updateSecurityDefinitions
} from '@/hermes'
import { useI18n } from '@/i18n'
import { cn } from '@/lib/utils'
import { confirm } from '@/store/confirm'
import { notify, notifyError } from '@/store/notifications'

import type { SetStatusbarItemGroup } from '../shell/statusbar-controls'

interface SecurityViewProps extends React.ComponentProps<'section'> {
  setStatusbarItemGroup?: SetStatusbarItemGroup
}

function toneForEngine(version: string): StatusTone {
  return version.includes('unavailable') || version.includes('error') ? 'bad' : 'good'
}

function toneForVerdict(verdict: null | string): string {
  if (verdict === 'MALICIOUS' || verdict === 'SCAN_ERROR') {
    return 'text-destructive'
  }

  if (verdict === 'SUSPICIOUS' || verdict === 'UNKNOWN') {
    return 'text-amber-600 dark:text-amber-300'
  }

  return 'text-(--ui-text-secondary)'
}

function canChangeQuarantineItem(item: QuarantineItem): boolean {
  return item.restore_state === undefined || item.restore_state === 'quarantined'
}

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`
  }

  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`
  }

  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

function formatTime(value: string): string {
  const parsed = new Date(value)

  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString()
}

function formatEvidence(serialized: string): string {
  try {
    const value: unknown = JSON.parse(serialized)

    const record =
      value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null

    const findings = Array.isArray(value) ? value : Array.isArray(record?.findings) ? record.findings : []

    const labels = findings.flatMap(item => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) {
        return []
      }

      const finding = item as Record<string, unknown>

      return typeof finding.source === 'string' && typeof finding.name === 'string'
        ? [`${finding.source}: ${finding.name}`]
        : []
    })

    if (labels.length > 0) {
      return labels.join('; ')
    }

    return typeof record?.sha256 === 'string' ? `SHA-256: ${record.sha256}` : '—'
  } catch {
    return '—'
  }
}

export function SecurityView({
  setStatusbarItemGroup: _setStatusbarItemGroup,
  className,
  ...props
}: SecurityViewProps) {
  const { t } = useI18n()
  const s = t.security
  const [status, setStatus] = useState<SecurityStatus | null>(null)
  const [busy, setBusy] = useState<null | string>(null)
  const [error, setError] = useState<null | string>(null)
  const [customPath, setCustomPath] = useState('')

  const refresh = useCallback(async () => {
    try {
      setError(null)
      setStatus(await getSecurityStatus())
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      notifyError(err, s.failedLoad)
    }
  }, [s.failedLoad])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const run = useCallback(
    async (name: string, operation: () => Promise<unknown>) => {
      setBusy(name)
      setError(null)

      try {
        await operation()
        await refresh()
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
        notifyError(err, s.actionFailed)
      } finally {
        setBusy(null)
      }
    },
    [refresh, s.actionFailed]
  )

  const scan = useCallback(
    async (scope: 'custom' | 'quick') => {
      const title = scope === 'quick' ? s.confirmQuick : s.confirmCustom

      if (!(await confirm({ title, confirmLabel: scope === 'quick' ? s.quickScan : s.customScan }))) {
        return
      }

      await run(scope, async () => {
        const response = await runSecurityScan({
          scope,
          quarantine: true,
          ...(scope === 'custom' ? { path: customPath.trim() } : {})
        })

        notify({
          id: 'security-scan-complete',
          kind: 'success',
          title: s.title,
          message: s.scanComplete(response.results.length)
        })
      })
    },
    [customPath, run, s]
  )

  const updateDefinitions = useCallback(async () => {
    if (!(await confirm({ title: s.confirmUpdate, confirmLabel: s.updateDefinitions }))) {
      return
    }

    await run('update', async () => {
      const result = await updateSecurityDefinitions()

      if (!result.ok) {
        throw new Error(result.error || result.state)
      }
    })
  }, [run, s])

  const toggleWatch = useCallback(async () => {
    if (!status) {
      return
    }

    const action = status.watch.running ? 'disable' : 'enable'
    await run('watch', () => setSecurityWatch(action))
  }, [run, status])

  const restore = useCallback(
    async (item: QuarantineItem) => {
      if (!(await confirm({ title: s.confirmRestore, confirmLabel: s.restore }))) {
        return
      }

      await run(`restore:${item.id}`, () => restoreQuarantineItem(item.id))
    },
    [run, s]
  )

  const remove = useCallback(
    async (item: QuarantineItem) => {
      if (!(await confirm({ title: s.confirmDelete, confirmLabel: s.delete, destructive: true }))) {
        return
      }

      await run(`delete:${item.id}`, () => deleteQuarantineItem(item.id))
    },
    [run, s]
  )

  const engines = useMemo(() => Object.entries(status?.engines ?? {}), [status?.engines])

  const scannerReady = engines.some(
    ([name, version]) => ['clamav', 'yara'].includes(name) && toneForEngine(version) === 'good'
  )

  const observationUnknown = status?.state !== 'KNOWN'
  const protectionReady = Boolean(!observationUnknown && status?.enabled && scannerReady)

  if (!status && !error) {
    return <PageLoader label={s.refresh} />
  }

  return (
    <section className={cn('h-full min-h-0 min-w-0 overflow-y-auto pb-16', PAGE_INSET_X, className)} {...props}>
      <header className="flex flex-wrap items-start justify-between gap-5 border-b border-(--ui-stroke-secondary) py-8">
        <div className="min-w-[min(100%,16rem)] flex-1">
          <h1 className="text-2xl font-semibold tracking-tight text-(--ui-text-primary)">{s.title}</h1>
          <p className="mt-1 max-w-3xl text-sm leading-5 text-(--ui-text-secondary)">{s.subtitle}</p>
        </div>
        <Button aria-label={s.refresh} disabled={busy !== null} onClick={() => void refresh()} variant="outline">
          <Codicon name="refresh" />
          {s.refresh}
        </Button>
      </header>

      {error && <ErrorBanner className="mt-5">{error}</ErrorBanner>}
      {status?.error && <ErrorBanner className="mt-5">{s.failedLoad}</ErrorBanner>}

      {status && (
        <>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,18rem),1fr))] gap-x-6 gap-y-6 border-b border-(--ui-stroke-secondary) py-6">
            <section className="min-w-0">
              <h2 className="text-sm font-semibold text-(--ui-text-primary)">{s.protectionStatus}</h2>
              <dl className="mt-4 grid gap-2 text-xs">
                <div className="flex items-center justify-between gap-4">
                  <dt className="text-(--ui-text-secondary)">{s.title}</dt>
                  <dd className="flex items-center gap-2">
                    <StatusDot tone={protectionReady ? 'good' : 'warn'} />
                    {observationUnknown ? s.unknown : protectionReady ? s.enabled : s.needsAttention}
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <dt className="text-(--ui-text-secondary)">{s.watcher}</dt>
                  <dd>{observationUnknown ? s.unknown : status.watch.running ? s.enabled : s.needsAttention}</dd>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <dt className="text-(--ui-text-secondary)">{s.automaticQuarantine}</dt>
                  <dd>{observationUnknown ? s.unknown : status.auto_quarantine ? s.enabled : s.needsAttention}</dd>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <dt className="text-(--ui-text-secondary)">{s.vaultProtection}</dt>
                  <dd className="min-w-0 break-all text-right font-mono text-[11px]">
                    {observationUnknown ? s.unknown : status.vault_key_protection}
                  </dd>
                </div>
              </dl>
              <Button
                className="mt-4"
                disabled={busy !== null}
                onClick={() => void toggleWatch()}
                size="sm"
                variant="outline"
              >
                {status.watch.running ? t.common.off : t.common.on}
              </Button>
            </section>

            <section className="min-w-0">
              <h2 className="text-sm font-semibold text-(--ui-text-primary)">{s.engineAvailability}</h2>
              <dl className="mt-4 grid gap-2 text-xs">
                {engines.map(([name, version]) => (
                  <div className="flex items-center justify-between gap-4" key={name}>
                    <dt className="font-mono text-(--ui-text-secondary)">{name}</dt>
                    <dd className="flex min-w-0 items-center gap-2">
                      <StatusDot tone={toneForEngine(version)} />
                      <span className="max-w-52 truncate font-mono text-[11px]" title={version}>
                        {version}
                      </span>
                    </dd>
                  </div>
                ))}
              </dl>
              <h3 className="mt-5 text-xs font-semibold text-(--ui-text-primary)">{s.activeFeeds}</h3>
              {status.feeds.length === 0 ? (
                <p className="mt-2 text-xs text-(--ui-text-tertiary)">{observationUnknown ? s.unknown : s.notYet}</p>
              ) : (
                <dl className="mt-2 grid gap-2 text-xs">
                  {status.feeds.map(feed => (
                    <div className="flex items-center justify-between gap-4" key={feed.name}>
                      <dt className="min-w-0 truncate font-mono text-(--ui-text-secondary)" title={feed.name}>
                        {feed.name}
                      </dt>
                      <dd className="flex items-center gap-2 font-mono text-[11px]">
                        <StatusDot tone={feed.status === 'ok' ? 'good' : 'bad'} />
                        {feed.status}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </section>

            <section className="min-w-0">
              <h2 className="text-sm font-semibold text-(--ui-text-primary)">{s.scanActions}</h2>
              <div className="mt-4 grid gap-2">
                <Button disabled={busy !== null} onClick={() => void scan('quick')} variant="outline">
                  <Codicon name="search" />
                  {s.quickScan}
                </Button>
                <div className="flex min-w-0 flex-wrap gap-2">
                  <Input
                    aria-label={s.pathPlaceholder}
                    className="min-w-0 basis-48 flex-1"
                    onChange={event => setCustomPath(event.target.value)}
                    placeholder={s.pathPlaceholder}
                    value={customPath}
                  />
                  <Button
                    className="min-w-fit flex-1"
                    disabled={busy !== null || !customPath.trim()}
                    onClick={() => void scan('custom')}
                    variant="outline"
                  >
                    {s.customScan}
                  </Button>
                </div>
                <Button disabled={busy !== null} onClick={() => void updateDefinitions()} variant="outline">
                  <Codicon name="cloud-download" />
                  {s.updateDefinitions}
                </Button>
              </div>
            </section>
          </div>

          <section className="border-b border-(--ui-stroke-secondary) py-6">
            <h2 className="text-sm font-semibold text-(--ui-text-primary)">{s.securitySummary}</h2>
            <dl className="mt-4 grid grid-cols-[repeat(auto-fit,minmax(min(100%,9rem),1fr))] gap-x-6 gap-y-4 text-xs">
              <div>
                <dt className="text-(--ui-text-tertiary)">{s.filesScanned}</dt>
                <dd className="mt-1 text-lg font-medium text-(--ui-text-primary)">
                  {observationUnknown ? s.unknown : status.summary.files_scanned}
                </dd>
              </div>
              <div>
                <dt className="text-(--ui-text-tertiary)">{s.detections}</dt>
                <dd className="mt-1 text-lg font-medium text-(--ui-text-primary)">
                  {observationUnknown ? s.unknown : status.summary.detections}
                </dd>
              </div>
              <div>
                <dt className="text-(--ui-text-tertiary)">{s.quarantineCount}</dt>
                <dd className="mt-1 text-lg font-medium text-(--ui-text-primary)">
                  {observationUnknown ? s.unknown : status.summary.quarantine_count}
                </dd>
              </div>
              <div>
                <dt className="text-(--ui-text-tertiary)">{s.pendingDisposition}</dt>
                <dd className="mt-1 text-lg font-medium text-amber-600 dark:text-amber-300">
                  {observationUnknown ? s.unknown : (status.summary.quarantine_pending_count ?? 0)}
                </dd>
              </div>
              <div>
                <dt className="text-(--ui-text-tertiary)">{s.lastScan}</dt>
                <dd className="mt-1 text-(--ui-text-primary)">
                  {observationUnknown ? s.unknown : status.summary.last_scan ? formatTime(status.summary.last_scan) : s.notYet}
                </dd>
              </div>
              <div>
                <dt className="text-(--ui-text-tertiary)">{s.lastSignatureUpdate}</dt>
                <dd className="mt-1 text-(--ui-text-primary)">
                  {observationUnknown
                    ? s.unknown
                    : status.summary.last_signature_update
                      ? formatTime(status.summary.last_signature_update)
                      : s.notYet}
                </dd>
              </div>
            </dl>
          </section>

          <section className="border-b border-(--ui-stroke-secondary) py-6">
            <h2 className="text-sm font-semibold text-(--ui-text-primary)">{s.recentEvents}</h2>
            {status.recent_events.length === 0 ? (
              <p className="mt-4 text-xs text-(--ui-text-tertiary)">{observationUnknown ? s.unknown : s.noEvents}</p>
            ) : (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-3xl border-collapse text-left text-xs">
                  <thead className="text-(--ui-text-tertiary)">
                    <tr>
                      <th className="pb-2 font-medium">{s.time}</th>
                      <th className="pb-2 font-medium">{s.subject}</th>
                      <th className="pb-2 font-medium">{s.verdict}</th>
                      <th className="pb-2 font-medium">{s.evidence}</th>
                      <th className="pb-2 font-medium">{s.action}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {status.recent_events.map(event => (
                      <tr className="border-t border-(--ui-stroke-secondary)" key={event.id}>
                        <td className="py-2 pr-4 whitespace-nowrap">{formatTime(event.created_at)}</td>
                        <td className="max-w-xl truncate py-2 pr-4 font-mono text-[11px]" title={event.subject}>
                          {event.subject}
                        </td>
                        <td className={cn('py-2 pr-4 font-mono text-[11px]', toneForVerdict(event.verdict))}>
                          {event.verdict || '—'}
                        </td>
                        <td
                          className="max-w-xl truncate py-2 pr-4 font-mono text-[11px]"
                          title={formatEvidence(event.details_json)}
                        >
                          {formatEvidence(event.details_json)}
                        </td>
                        <td className="py-2">{event.action}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="py-6">
            <h2 className="text-sm font-semibold text-(--ui-text-primary)">{s.encryptedQuarantine}</h2>
            {status.quarantine.filter(item => !item.deleted_at && !item.restored_at).length === 0 ? (
              <p className="mt-4 text-xs text-(--ui-text-tertiary)">{observationUnknown ? s.unknown : s.noQuarantine}</p>
            ) : (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-4xl border-collapse text-left text-xs">
                  <thead className="text-(--ui-text-tertiary)">
                    <tr>
                      <th className="pb-2 font-medium">{s.time}</th>
                      <th className="pb-2 font-medium">{s.originalPath}</th>
                      <th className="pb-2 font-medium">{s.verdict}</th>
                      <th className="pb-2 font-medium">{s.evidence}</th>
                      <th className="pb-2 font-medium">{s.size}</th>
                      <th className="pb-2 font-medium">{s.action}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {status.quarantine
                      .filter(item => !item.deleted_at && !item.restored_at)
                      .map(item => (
                        <tr className="border-t border-(--ui-stroke-secondary)" key={item.id}>
                          <td className="py-2 pr-4 whitespace-nowrap">{formatTime(item.created_at)}</td>
                          <td className="max-w-xl truncate py-2 pr-4 font-mono text-[11px]" title={item.original_path}>
                            {item.original_path}
                            {!canChangeQuarantineItem(item) && (
                              <span className="mt-1 block text-amber-600 dark:text-amber-300">
                                {item.restore_state === 'pending_source_disposition' ? s.pendingDisposition : s.unknown}
                              </span>
                            )}
                          </td>
                          <td className={cn('py-2 pr-4 font-mono text-[11px]', toneForVerdict(item.verdict))}>
                            {item.verdict}
                          </td>
                          <td
                            className="max-w-xl truncate py-2 pr-4 font-mono text-[11px]"
                            title={formatEvidence(item.findings_json)}
                          >
                            {formatEvidence(item.findings_json)}
                          </td>
                          <td className="py-2 pr-4 whitespace-nowrap">{formatBytes(item.size)}</td>
                          <td className="py-2">
                            <div className="flex gap-3">
                              <Button
                                disabled={busy !== null || !canChangeQuarantineItem(item)}
                                onClick={() => void restore(item)}
                                size="inline"
                                variant="text"
                              >
                                {s.restore}
                              </Button>
                              <Button
                                disabled={busy !== null || !canChangeQuarantineItem(item)}
                                onClick={() => void remove(item)}
                                size="inline"
                                variant="text"
                              >
                                {s.delete}
                              </Button>
                            </div>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </section>
  )
}
