import { atom } from 'nanostores'

import type { HermesGitBranch, HermesGitStash, HermesGitTag } from '@/global'
import { desktopGit } from '@/lib/desktop-git'

import { refreshRepoStatus } from './coding-status'
import { $reviewContextVersion, $reviewOpen, $reviewScopeCwd, refreshReviewHistory, reviewRepoCwd } from './review'
import { $busy, $currentCwd } from './session'
import { $workspaceChangeTick } from './workspace-events'

// State for the SCM rail inside the review pane: the repo's branches, tags and
// stashes plus the branch/tag/stash CRUD and fetch/pull mutations. Git is the
// source of truth (via the Electron bridge or the remote REST mirror); the
// store is a bounded cache that re-probes on the same structural edges as the
// review pane (open/close, cwd move, tool-turn settle, window focus).
//
// Scope follows the review pane's repo (`reviewRepoCwd`): the active session's
// cwd, or a tile worktree when the pane is pinned to one. Mutations re-sync
// the lists, the rail's +/- badge, and (for ref moves that can change HEAD or
// add commits) the pane's history list.

export const $scmBranches = atom<HermesGitBranch[]>([])
export const $scmBranchesLoading = atom(false)
export const $scmTags = atom<HermesGitTag[]>([])
export const $scmTagsLoading = atom(false)
export const $scmStashes = atom<HermesGitStash[]>([])
export const $scmStashesLoading = atom(false)

// Which mutation is in flight; the SCM panels disable their action buttons
// while non-null so the git ops can't double-fire.
export type ScmBusyKind = 'branch' | 'fetch' | 'pull' | 'push' | 'stash' | 'tag'

export const $scmBusy = atom<null | ScmBusyKind>(null)

type ScmBridge = NonNullable<NonNullable<Window['hermesDesktop']>['git']>

const SCM_REFRESH_DEBOUNCE_MS = 100

let scmRefreshSeq = 0
let scmRefreshTimer: ReturnType<typeof setTimeout> | null = null

function scmCtx(): { cwd: string; git: ScmBridge } | null {
  const cwd = reviewRepoCwd()
  const git = desktopGit()

  return cwd && git ? { cwd, git } : null
}

// ── Reads ────────────────────────────────────────────────────────────────────

export async function refreshScmRefs(): Promise<void> {
  const ctx = scmCtx()
  const seq = (scmRefreshSeq += 1)

  if (!$reviewOpen.get() || !ctx) {
    $scmBranches.set([])
    $scmTags.set([])
    $scmStashes.set([])

    if (seq === scmRefreshSeq) {
      $scmBranchesLoading.set(false)
      $scmTagsLoading.set(false)
      $scmStashesLoading.set(false)
    }

    return
  }

  const { cwd, git } = ctx

  $scmBranchesLoading.set(true)
  $scmTagsLoading.set(true)
  $scmStashesLoading.set(true)

  try {
    const [branches, tags, stashes] = await Promise.all([git.branchList(cwd), git.tagList(cwd), git.stashList(cwd)])

    // Ignore a result that resolved after the cwd moved on.
    if (seq !== scmRefreshSeq || reviewRepoCwd() !== cwd) {
      return
    }

    $scmBranches.set(branches)
    $scmTags.set(tags)
    $scmStashes.set(stashes)
  } catch {
    if (seq === scmRefreshSeq) {
      $scmBranches.set([])
      $scmTags.set([])
      $scmStashes.set([])
    }
  } finally {
    if (seq === scmRefreshSeq) {
      $scmBranchesLoading.set(false)
      $scmTagsLoading.set(false)
      $scmStashesLoading.set(false)
    }
  }
}

function scheduleScmRefresh(): void {
  if (!$reviewOpen.get()) {
    return
  }

  if (scmRefreshTimer) {
    clearTimeout(scmRefreshTimer)
  }

  scmRefreshTimer = setTimeout(() => {
    scmRefreshTimer = null
    void refreshScmRefs()
  }, SCM_REFRESH_DEBOUNCE_MS)
}

// ── Mutations ────────────────────────────────────────────────────────────────

// Run a git mutation then re-sync the lists, the rail's +/- (HEAD may have
// moved), and the pane's history. A failure is swallowed by the caller's
// notify wrapper.
async function afterMutation(): Promise<void> {
  await refreshScmRefs()
  void refreshRepoStatus(reviewRepoCwd())
  // Branch/tag/stash ops and fetch/pull can move HEAD or add commits. The
  // history refresh is gated on the pane being open, so it's a no-op when not.
  void refreshReviewHistory()
}

// Serialize one mutation behind its busy flag so a panel can't double-fire.
async function runScm<T>(kind: ScmBusyKind, action: () => Promise<T>): Promise<T> {
  $scmBusy.set(kind)

  try {
    return await action()
  } finally {
    $scmBusy.set(null)
  }
}

export async function scmBranchCreate(name: string, base: null | string = null): Promise<void> {
  const ctx = scmCtx()

  if (!ctx?.git.branchCreate) {
    return
  }

  await runScm('branch', async () => {
    await ctx.git.branchCreate?.(ctx.cwd, name, base)
    await afterMutation()
  })
}

export async function scmBranchRename(name: string, newName: string): Promise<void> {
  const ctx = scmCtx()

  if (!ctx?.git.branchRename) {
    return
  }

  await runScm('branch', async () => {
    await ctx.git.branchRename?.(ctx.cwd, name, newName)
    await afterMutation()
  })
}

export async function scmBranchDelete(name: string, force = false): Promise<void> {
  const ctx = scmCtx()

  if (!ctx?.git.branchDelete) {
    return
  }

  await runScm('branch', async () => {
    await ctx.git.branchDelete?.(ctx.cwd, name, force)
    await afterMutation()
  })
}

export async function scmTagCreate(name: string, target: null | string = null): Promise<void> {
  const ctx = scmCtx()

  if (!ctx?.git.tagCreate) {
    return
  }

  await runScm('tag', async () => {
    await ctx.git.tagCreate?.(ctx.cwd, name, target)
    await afterMutation()
  })
}

export async function scmTagDelete(name: string): Promise<void> {
  const ctx = scmCtx()

  if (!ctx?.git.tagDelete) {
    return
  }

  await runScm('tag', async () => {
    await ctx.git.tagDelete?.(ctx.cwd, name)
    await afterMutation()
  })
}

export async function scmStashCreate(message: null | string = null, includeUntracked = false): Promise<void> {
  const ctx = scmCtx()

  if (!ctx?.git.stashCreate) {
    return
  }

  await runScm('stash', async () => {
    await ctx.git.stashCreate?.(ctx.cwd, message, includeUntracked)
    await afterMutation()
  })
}

export async function scmStashApply(index: number): Promise<void> {
  const ctx = scmCtx()

  if (!ctx?.git.stashApply) {
    return
  }

  await runScm('stash', async () => {
    await ctx.git.stashApply?.(ctx.cwd, index)
    await afterMutation()
  })
}

export async function scmStashDrop(index: number): Promise<void> {
  const ctx = scmCtx()

  if (!ctx?.git.stashDrop) {
    return
  }

  await runScm('stash', async () => {
    await ctx.git.stashDrop?.(ctx.cwd, index)
    await afterMutation()
  })
}

export async function scmFetch(remote: null | string = null): Promise<void> {
  const ctx = scmCtx()

  if (!ctx?.git.fetch) {
    return
  }

  await runScm('fetch', async () => {
    await ctx.git.fetch?.(ctx.cwd, remote)
    await afterMutation()
  })
}

export async function scmPull(rebase = false): Promise<void> {
  const ctx = scmCtx()

  if (!ctx?.git.pull) {
    return
  }

  await runScm('pull', async () => {
    await ctx.git.pull?.(ctx.cwd, rebase)
    await afterMutation()
  })
}

export async function scmBranchSwitch(name: string): Promise<void> {
  const ctx = scmCtx()

  if (!ctx?.git.branchSwitch) {
    return
  }

  await runScm('branch', async () => {
    await ctx.git.branchSwitch?.(ctx.cwd, name)
    await afterMutation()
  })
}

export async function scmPush(): Promise<void> {
  const ctx = scmCtx()

  if (!ctx?.git.review.push) {
    return
  }

  await runScm('push', async () => {
    await ctx.git.review.push?.(ctx.cwd)
    await afterMutation()
  })
}

// ── Triggers (module-scope, mirror review.ts) ────────────────────────────────

// A file-mutating tool finished → refresh the lists.
$workspaceChangeTick.subscribe(() => {
  if ($reviewOpen.get()) {
    scheduleScmRefresh()
  }
})

// Turn settled → final refresh.
let prevBusy = $busy.get()

$busy.subscribe(busy => {
  if (prevBusy && !busy && $reviewOpen.get()) {
    scheduleScmRefresh()
  }

  prevBusy = busy
})

// The pane's repo moved under it (session cwd change, or a scoped re-home).
// Drop the stale lists up front so the panels fall straight to their loading
// skeleton instead of blipping the previous repo's refs into the new one.
function onScmRepoMoved(): void {
  if ($reviewOpen.get()) {
    $scmBranches.set([])
    $scmTags.set([])
    $scmStashes.set([])
    $scmBranchesLoading.set(true)
    $scmTagsLoading.set(true)
    $scmStashesLoading.set(true)
    scheduleScmRefresh()
  }
}

$reviewContextVersion.listen(onScmRepoMoved)

$currentCwd.subscribe(() => {
  if (!$reviewScopeCwd.get()) {
    onScmRepoMoved()
  }
})

let prevScopeCwd = $reviewScopeCwd.get()

$reviewScopeCwd.subscribe(scope => {
  if (scope !== prevScopeCwd) {
    prevScopeCwd = scope
    onScmRepoMoved()
  }
})

// An outside terminal may have changed the tree while we were away.
if (typeof window !== 'undefined') {
  window.addEventListener('focus', () => {
    if ($reviewOpen.get()) {
      scheduleScmRefresh()
    }
  })
}
