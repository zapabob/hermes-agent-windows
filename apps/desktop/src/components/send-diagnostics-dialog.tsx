// Diagnostics export host — local-first consent dialog.
//
// Primary: Export locally (diagnostics.export_local → ZIP on disk).
// Secondary: Upload to Nous (diagnostics.share_nous) — explicit opt-in only.
import { useStore } from '@nanostores/react'

import { Button } from '@/components/ui/button'
import { CopyButton } from '@/components/ui/copy-button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { useI18n } from '@/i18n'
import { ExternalLink as ExternalLinkAnchor, openExternalLink } from '@/lib/external-link'
import { ExternalLink, Loader2Icon, Lock } from '@/lib/icons'
import {
  $sendDiagnostics,
  confirmExportLocalDiagnostics,
  confirmUploadNousDiagnostics,
  dismissSendDiagnostics
} from '@/store/send-diagnostics'

const SUPPORT_LINKS = [
  { key: 'github', url: 'https://github.com/NousResearch/hermes-agent/issues' },
  { key: 'portal', url: 'https://portal.nousresearch.com/help' },
  { key: 'discord', url: 'https://discord.gg/NousResearch' }
] as const

export function SendDiagnosticsHost() {
  const { t } = useI18n()
  const copy = t.sendDiagnostics
  const state = useStore($sendDiagnostics)

  if (!state) {
    return null
  }

  const busy = state.phase === 'exporting' || state.phase === 'uploading'
  const localDone = state.phase === 'done' && state.destination === 'local'

  return (
    <Dialog onOpenChange={open => (!open ? dismissSendDiagnostics() : undefined)} open>
      <DialogContent className="max-w-[30rem]">
        {state.phase === 'consent' || state.phase === 'exporting' || state.phase === 'uploading' ? (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <Lock className="size-4 text-(--ui-text-tertiary)" />
                {copy.title}
              </DialogTitle>
              <DialogDescription className="whitespace-pre-line text-left">{copy.privacyNotice}</DialogDescription>
            </DialogHeader>
            <DialogFooter className="flex-col gap-2 sm:flex-col sm:space-x-0">
              <div className="flex w-full flex-wrap justify-end gap-2">
                <Button disabled={busy} onClick={dismissSendDiagnostics} variant="ghost">
                  {copy.cancel}
                </Button>
                <Button disabled={busy} onClick={() => void confirmExportLocalDiagnostics()}>
                  {state.phase === 'exporting' ? (
                    <span className="flex items-center gap-1.5">
                      <Loader2Icon className="size-3.5 animate-spin" />
                      {copy.exporting}
                    </span>
                  ) : (
                    copy.exportLocal
                  )}
                </Button>
              </div>
              <Button
                className="self-end"
                disabled={busy}
                onClick={() => void confirmUploadNousDiagnostics()}
                size="sm"
                variant="outline"
              >
                {state.phase === 'uploading' ? (
                  <span className="flex items-center gap-1.5">
                    <Loader2Icon className="size-3.5 animate-spin" />
                    {copy.uploading}
                  </span>
                ) : (
                  copy.uploadNous
                )}
              </Button>
            </DialogFooter>
          </>
        ) : state.phase === 'error' ? (
          <>
            <DialogHeader>
              <DialogTitle>{copy.failedTitle}</DialogTitle>
              <DialogDescription className="text-left">
                {state.error}
                {'\n'}
                {copy.failedHint}
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button onClick={dismissSendDiagnostics} variant="ghost">
                {copy.close}
              </Button>
            </DialogFooter>
          </>
        ) : localDone ? (
          <>
            <DialogHeader>
              <DialogTitle>{copy.doneTitle}</DialogTitle>
              <DialogDescription className="text-left">{copy.doneDescription}</DialogDescription>
            </DialogHeader>
            {state.result?.localPath && (
              <div
                className="flex items-center gap-2 rounded-md border border-(--ui-stroke-tertiary) px-3 py-2"
                data-selectable-text="true"
              >
                <code
                  className="min-w-0 flex-1 truncate font-mono text-[0.78rem] text-(--ui-text-secondary)"
                  title={state.result.localPath}
                >
                  {state.result.localPath}
                </code>
                <CopyButton
                  appearance="inline"
                  className="shrink-0"
                  label={copy.copyPath}
                  text={state.result.localPath}
                />
              </div>
            )}
            <div className="text-[0.8rem] text-(--ui-text-secondary)">{copy.handoffLead}</div>
            <div className="flex flex-wrap gap-1.5">
              {SUPPORT_LINKS.map(link => (
                <Button key={link.key} onClick={() => openExternalLink(link.url)} size="sm" variant="outline">
                  <ExternalLink className="size-3" />
                  {copy.links[link.key]}
                </Button>
              ))}
            </div>
            <DialogFooter>
              <Button onClick={dismissSendDiagnostics} variant="ghost">
                {copy.close}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>{copy.nousDoneTitle}</DialogTitle>
              <DialogDescription className="text-left">{copy.nousDoneDescription}</DialogDescription>
            </DialogHeader>
            {(state.result?.viewUrl || state.result?.uploadId) && (
              <div
                className="flex items-center gap-2 rounded-md border border-(--ui-stroke-tertiary) px-3 py-2"
                data-selectable-text="true"
              >
                {state.result.viewUrl ? (
                  <ExternalLinkAnchor
                    className="min-w-0 flex-1 truncate font-mono text-[0.78rem] text-(--ui-text-secondary)"
                    href={state.result.viewUrl}
                    native
                    title={state.result.viewUrl}
                  >
                    {state.result.viewUrl}
                  </ExternalLinkAnchor>
                ) : (
                  <code className="min-w-0 flex-1 truncate text-[0.78rem] text-(--ui-text-secondary)">
                    {copy.uploadIdFallback(state.result.uploadId ?? '')}
                  </code>
                )}
                <CopyButton
                  appearance="inline"
                  className="shrink-0"
                  label={copy.copyLink}
                  text={state.result.viewUrl ?? state.result.uploadId ?? ''}
                />
              </div>
            )}
            <div className="text-[0.8rem] text-(--ui-text-secondary)">{copy.handoffLead}</div>
            <div className="flex flex-wrap gap-1.5">
              {SUPPORT_LINKS.map(link => (
                <Button key={link.key} onClick={() => openExternalLink(link.url)} size="sm" variant="outline">
                  <ExternalLink className="size-3" />
                  {copy.links[link.key]}
                </Button>
              ))}
            </div>
            <DialogFooter>
              <Button onClick={dismissSendDiagnostics} variant="ghost">
                {copy.close}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
