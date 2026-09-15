import { useStore } from '@nanostores/react'
import type { FormEvent, ReactNode } from 'react'
import { useEffect, useRef, useState } from 'react'

import { ActionStatus } from '@/components/ui/action-status'
import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Tip } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n'
import { desktopGit } from '@/lib/desktop-git'
import { AlertTriangle } from '@/lib/icons'
import { cn } from '@/lib/utils'
import { notifyError } from '@/store/notifications'
import {
  $scmBranches,
  $scmBranchesLoading,
  $scmBusy,
  $scmStashes,
  $scmStashesLoading,
  $scmTags,
  $scmTagsLoading,
  scmBranchCreate,
  scmBranchDelete,
  scmBranchRename,
  scmBranchSwitch,
  scmFetch,
  scmPull,
  scmPush,
  scmStashApply,
  scmStashCreate,
  scmStashDrop,
  scmTagCreate,
  scmTagDelete
} from '@/store/scm-refs'

function skeleton(loading: boolean, empty: boolean) {
  if (!loading || !empty) {
    return null
  }

  return (
    <div className="space-y-1 px-2.5 py-1.5" data-slot="tree-skeleton">
      <div className="h-3 w-3/4 animate-pulse rounded bg-(--ui-bg-tertiary)" />
      <div className="h-3 w-1/2 animate-pulse rounded bg-(--ui-bg-tertiary)" />
    </div>
  )
}

function formatScmTime(value: string): string {
  const timestamp = Date.parse(value)

  if (Number.isNaN(timestamp)) {
    return value
  }

  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(timestamp)
}

interface ScmNameDialogProps {
  open: boolean
  onClose: () => void
  // Does the work. Throw to surface an inline error and keep the dialog open.
  onSubmit: (value: string) => Promise<void>
  title: ReactNode
  description?: ReactNode
  label: string
  placeholder?: string
  initialValue?: string
  /** Allow an empty value (the stash dialog's optional message). */
  optional?: boolean
  submitLabel: string
}

// Shared name/message input dialog for branch create/rename, tag create and
// stash create. Owns the pending → done → close beat and inline error, so
// callers pass only an async onSubmit that does the work.
function ScmNameDialog({
  open,
  onClose,
  onSubmit,
  title,
  description,
  label,
  placeholder,
  initialValue = '',
  optional = false,
  submitLabel
}: ScmNameDialogProps) {
  const { t } = useI18n()
  const [value, setValue] = useState(initialValue)
  const [status, setStatus] = useState<'done' | 'idle' | 'saving'>('idle')
  const [error, setError] = useState<null | string>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  const trimmed = value.trim()
  const invalid = !optional && trimmed === ''
  const busy = status === 'saving' || status === 'done'

  useEffect(() => {
    if (open) {
      setValue(initialValue)
      setStatus('idle')
      setError(null)
    }
  }, [initialValue, open])

  // Close after a brief "done" flash. Timer must clear on unmount or the
  // callback races vitest teardown (ReferenceError: window is not defined).
  useEffect(() => {
    if (status !== 'done') {
      return
    }

    const id = window.setTimeout(() => {
      onCloseRef.current()
    }, 600)

    return () => {
      window.clearTimeout(id)
    }
  }, [status])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (invalid || busy) {
      return
    }

    setStatus('saving')
    setError(null)

    try {
      await onSubmit(trimmed)
      setStatus('done')
    } catch (err) {
      setStatus('idle')
      setError(err instanceof Error ? err.message : t.errors.genericFailure)
    }
  }

  return (
    <Dialog onOpenChange={value => !value && !busy && onClose()} open={open}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description ? <DialogDescription>{description}</DialogDescription> : null}
        </DialogHeader>

        <form className="grid gap-4" onSubmit={handleSubmit}>
          <Field htmlFor="scm-ref-name" label={label} optional={optional}>
            <Input
              autoFocus
              disabled={busy}
              id="scm-ref-name"
              onChange={event => setValue(event.target.value)}
              placeholder={placeholder}
              value={value}
            />
          </Field>

          {error && (
            <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <DialogFooter>
            <Button disabled={busy} onClick={onClose} type="button" variant="ghost">
              {t.common.cancel}
            </Button>
            <Button disabled={busy || invalid} type="submit">
              <ActionStatus busy={t.common.loading} done={t.common.done} idle={submitLabel} state={status} />
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

interface BranchDialogState {
  initialName?: string
  mode: 'create' | 'rename'
  sourceName?: string
}

interface DeleteTarget {
  index?: number
  kind: 'branch' | 'stash' | 'tag'
  name: string
}

function ScmActionButton({
  busy,
  icon,
  label,
  onClick
}: {
  busy: boolean
  icon: string
  label: string
  onClick: () => void
}) {
  return (
    <Tip label={label}>
      <Button aria-label={label} className="size-5" disabled={busy} onClick={onClick} size="icon-xs" variant="ghost">
        <Codicon name={icon} size="0.75rem" />
      </Button>
    </Tip>
  )
}

function ScmSection({
  action,
  count,
  label,
  children
}: {
  action?: ReactNode
  count: number
  label: string
  children: ReactNode
}) {
  return (
    <section>
      <header className="flex items-center gap-1.5 px-2.5 pb-1 pt-2.5">
        <span className="text-[0.64rem] font-semibold uppercase tracking-wide text-(--ui-text-tertiary)">{label}</span>
        <span className="rounded-full bg-(--ui-bg-tertiary) px-1.5 text-[0.58rem] text-(--ui-text-tertiary)">
          {count}
        </span>
        {action ? <span className="ml-auto flex items-center">{action}</span> : null}
      </header>
      {children}
    </section>
  )
}

function ScmRow({
  actions,
  name,
  title,
  meta
}: {
  actions?: ReactNode
  name: string
  title?: string
  meta?: ReactNode
}) {
  return (
    <div className="group/row flex min-w-0 items-center gap-2 px-2.5 py-1.5">
      <span className="min-w-0 flex-1 truncate text-[0.72rem] text-(--ui-text-primary)" title={title ?? name}>
        {name}
      </span>
      {meta}
      {actions ? (
        <span className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover/row:opacity-100">
          {actions}
        </span>
      ) : null}
    </div>
  )
}

const META_TIME = 'shrink-0 font-mono text-[0.58rem] text-(--ui-text-tertiary)'
const META_PILL = 'shrink-0 rounded-full bg-(--ui-bg-tertiary) px-1.5 py-px text-[0.58rem] text-(--ui-text-secondary)'

/** The review pane's SCM rail: the repo's branches, tags and stashes, read
 *  from the git bridge via the scm-refs store, with create / rename / delete /
 *  fetch / pull actions. Actions no-op on old Electron shells without the git
 *  bridge, so they stay off the rail there. */
export function ReviewScmRail() {
  const { t } = useI18n()
  const c = t.statusStack.coding
  const branches = useStore($scmBranches)
  const branchesLoading = useStore($scmBranchesLoading)
  const tags = useStore($scmTags)
  const tagsLoading = useStore($scmTagsLoading)
  const stashes = useStore($scmStashes)
  const stashesLoading = useStore($scmStashesLoading)
  const busy = useStore($scmBusy)
  const canMutate = desktopGit() != null

  const [branchDialog, setBranchDialog] = useState<null | BranchDialogState>(null)
  const [tagDialogOpen, setTagDialogOpen] = useState(false)
  const [stashDialogOpen, setStashDialogOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<null | DeleteTarget>(null)

  const localBranches = branches.filter(b => !b.isRemote)
  const remoteBranches = branches.filter(b => b.isRemote)
  const remoteGroups = new Map<string, typeof remoteBranches>()

  for (const branch of remoteBranches) {
    const remote = branch.name.split('/')[0]

    if (!remoteGroups.has(remote)) {
      remoteGroups.set(remote, [])
    }

    remoteGroups.get(remote)!.push(branch)
  }

  const sortedRemotes = Array.from(remoteGroups.keys()).sort()

  const deleteConfirmation = deleteTarget
    ? ((): { description: string; title: string } => {
        switch (deleteTarget.kind) {
          case 'branch':
            return { description: c.deleteBranchConfirm(deleteTarget.name), title: c.deleteBranch }

          case 'tag':
            return { description: c.deleteTagConfirm(deleteTarget.name), title: c.deleteTag }

          default:
            return { description: c.dropStashConfirm(deleteTarget.name), title: c.dropStash }
        }
      })()
    : undefined

  function BranchGroupHeader({ label, count }: { label: string; count: number }) {
    return (
      <div className="px-2.5 pt-1.5 pb-0.5">
        <span className="text-[0.58rem] font-semibold uppercase tracking-wide text-(--ui-text-quaternary)">
          {label}
        </span>
        <span className="ml-1 rounded-full bg-(--ui-bg-tertiary) px-1.5 text-[0.55rem] text-(--ui-text-tertiary)">
          {count}
        </span>
      </div>
    )
  }

  async function confirmDelete(): Promise<void> {
    switch (deleteTarget?.kind) {
      case 'branch':
        await scmBranchDelete(deleteTarget.name)

        break

      case 'tag':
        await scmTagDelete(deleteTarget.name)

        break

      case 'stash':
        await scmStashDrop(deleteTarget.index ?? 0)

        break

      default:
        break
    }
  }

  return (
    <div aria-label={c.scm} className="min-h-0 flex-1 overflow-auto py-1" role="region">
      {canMutate && (
        <div className="flex items-center gap-1 px-2.5 pb-1 pt-1">
          <Tip label={c.fetch}>
            <Button
              aria-label={c.fetch}
              className="size-5"
              disabled={busy != null}
              onClick={() => void scmFetch().catch(err => notifyError(err, c.fetch))}
              size="icon-xs"
              variant="ghost"
            >
              <Codicon name="download" size="0.8125rem" spinning={busy === 'fetch'} />
            </Button>
          </Tip>
          <Tip label={c.pull}>
            <Button
              aria-label={c.pull}
              className="size-5"
              disabled={busy != null}
              onClick={() => void scmPull().catch(err => notifyError(err, c.pull))}
              size="icon-xs"
              variant="ghost"
            >
              <Codicon name="arrow-down" size="0.8125rem" spinning={busy === 'pull'} />
            </Button>
          </Tip>
          <Tip label={c.push ?? 'Push'}>
            <Button
              aria-label={c.push ?? 'Push'}
              className="size-5"
              disabled={busy != null}
              onClick={() => void scmPush().catch(err => notifyError(err, c.push ?? 'Push'))}
              size="icon-xs"
              variant="ghost"
            >
              <Codicon name="arrow-up" size="0.8125rem" spinning={busy === 'push'} />
            </Button>
          </Tip>
        </div>
      )}

      <ScmSection
        action={
          canMutate ? (
            <ScmActionButton
              busy={busy != null}
              icon="add"
              label={c.createBranch}
              onClick={() => setBranchDialog({ mode: 'create' })}
            />
          ) : undefined
        }
        count={branches.length}
        label={c.branches}
      >
        {skeleton(branchesLoading, branches.length === 0)}
        {!branchesLoading &&
          (branches.length === 0 ? (
            <p className="px-2.5 py-1 text-[0.66rem] text-(--ui-text-tertiary)">{c.noBranches}</p>
          ) : (
            <>
              <BranchGroupHeader count={localBranches.length} label={c.local ?? 'Local'} />
              {localBranches.map(branch => (
                <ScmRow
                  actions={
                    canMutate ? (
                      <>
                        {!branch.checkedOut && (
                          <ScmActionButton
                            busy={busy != null}
                            icon="check"
                            label={c.checkoutBranch ?? 'Switch to branch'}
                            onClick={() =>
                              void scmBranchSwitch(branch.name).catch(err =>
                                notifyError(err, c.checkoutBranch ?? 'Switch to branch')
                              )
                            }
                          />
                        )}
                        <ScmActionButton
                          busy={busy != null}
                          icon="edit"
                          label={c.renameBranch}
                          onClick={() =>
                            setBranchDialog({ initialName: branch.name, mode: 'rename', sourceName: branch.name })
                          }
                        />
                        <ScmActionButton
                          busy={busy != null}
                          icon="trash"
                          label={c.deleteBranch}
                          onClick={() => setDeleteTarget({ kind: 'branch', name: branch.name })}
                        />
                      </>
                    ) : undefined
                  }
                  key={branch.name}
                  meta={
                    branch.checkedOut ? (
                      <span className={META_PILL} title={c.checkedOut}>
                        {c.checkedOut}
                      </span>
                    ) : undefined
                  }
                  name={branch.name}
                />
              ))}
              {sortedRemotes.map(remote => {
                const group = remoteGroups.get(remote)!

                return (
                  <>
                    <BranchGroupHeader count={group.length} key={remote} label={remote} />
                    {group.map(branch => (
                      <ScmRow
                        key={branch.name}
                        meta={
                          branch.checkedOut ? (
                            <span className={META_PILL} title={c.checkedOut}>
                              {c.checkedOut}
                            </span>
                          ) : undefined
                        }
                        name={branch.name}
                      />
                    ))}
                  </>
                )
              })}
            </>
          ))}
      </ScmSection>

      <ScmSection
        action={
          canMutate ? (
            <ScmActionButton
              busy={busy != null}
              icon="add"
              label={c.createTag}
              onClick={() => setTagDialogOpen(true)}
            />
          ) : undefined
        }
        count={tags.length}
        label={c.tags}
      >
        {skeleton(tagsLoading, tags.length === 0)}
        {!tagsLoading &&
          (tags.length === 0 ? (
            <p className="px-2.5 py-1 text-[0.66rem] text-(--ui-text-tertiary)">{c.noTags}</p>
          ) : (
            tags.map(tag => (
              <ScmRow
                actions={
                  canMutate ? (
                    <ScmActionButton
                      busy={busy != null}
                      icon="trash"
                      label={c.deleteTag}
                      onClick={() => setDeleteTarget({ kind: 'tag', name: tag.name })}
                    />
                  ) : undefined
                }
                key={tag.name}
                meta={
                  <>
                    <span className="shrink-0 font-mono text-[0.58rem] text-(--ui-text-secondary)">{tag.shortSha}</span>
                    <time className={META_TIME} dateTime={tag.date}>
                      {formatScmTime(tag.date)}
                    </time>
                  </>
                }
                name={tag.name}
              />
            ))
          ))}
      </ScmSection>

      <ScmSection
        action={
          canMutate ? (
            <ScmActionButton
              busy={busy != null}
              icon="add"
              label={c.stashChanges}
              onClick={() => setStashDialogOpen(true)}
            />
          ) : undefined
        }
        count={stashes.length}
        label={c.stashes}
      >
        {skeleton(stashesLoading, stashes.length === 0)}
        {!stashesLoading &&
          (stashes.length === 0 ? (
            <p className="px-2.5 py-1 text-[0.66rem] text-(--ui-text-tertiary)">{c.noStashes}</p>
          ) : (
            stashes.map(stashEntry => (
              <ScmRow
                actions={
                  canMutate ? (
                    <>
                      <ScmActionButton
                        busy={busy != null}
                        icon="arrow-down"
                        label={c.applyStash}
                        onClick={() =>
                          void scmStashApply(stashEntry.index).catch(err => notifyError(err, c.applyStash))
                        }
                      />
                      <ScmActionButton
                        busy={busy != null}
                        icon="trash"
                        label={c.dropStash}
                        onClick={() => setDeleteTarget({ index: stashEntry.index, kind: 'stash', name: stashEntry.id })}
                      />
                    </>
                  ) : undefined
                }
                key={stashEntry.id}
                meta={
                  <>
                    <span className={cn('truncate text-[0.62rem] text-(--ui-text-secondary)')}>
                      {stashEntry.message}
                    </span>
                    <time className={META_TIME} dateTime={stashEntry.date}>
                      {formatScmTime(stashEntry.date)}
                    </time>
                  </>
                }
                name={stashEntry.id}
              />
            ))
          ))}
      </ScmSection>

      <ScmNameDialog
        description={
          branchDialog?.mode === 'rename' ? c.renameBranchDesc(branchDialog.sourceName ?? '') : c.createBranchDesc
        }
        initialValue={branchDialog?.initialName ?? ''}
        label={c.branchName}
        onClose={() => setBranchDialog(null)}
        onSubmit={name =>
          branchDialog?.mode === 'rename' ? scmBranchRename(branchDialog.sourceName ?? '', name) : scmBranchCreate(name)
        }
        open={branchDialog != null}
        submitLabel={branchDialog?.mode === 'rename' ? c.renameBranch : c.createBranch}
        title={branchDialog?.mode === 'rename' ? c.renameBranch : c.createBranch}
      />

      <ScmNameDialog
        description={c.createTagDesc}
        label={c.tagName}
        onClose={() => setTagDialogOpen(false)}
        onSubmit={name => scmTagCreate(name)}
        open={tagDialogOpen}
        submitLabel={c.createTag}
        title={c.createTag}
      />

      <ScmNameDialog
        description={c.stashChangesDesc}
        label={c.stashMessage}
        onClose={() => setStashDialogOpen(false)}
        onSubmit={message => scmStashCreate(message || null)}
        open={stashDialogOpen}
        optional
        placeholder={c.stashMessagePlaceholder}
        submitLabel={c.stashChanges}
        title={c.stashChanges}
      />

      <ConfirmDialog
        confirmLabel={deleteConfirmation?.title}
        description={deleteConfirmation?.description}
        destructive
        onClose={() => setDeleteTarget(null)}
        onConfirm={confirmDelete}
        open={deleteTarget != null}
        title={deleteConfirmation?.title}
      />
    </div>
  )
}
