import type {
  HermesGitBaseBranch,
  HermesGitBranch,
  HermesGitCommit,
  HermesGitStash,
  HermesGitTag,
  HermesGitWorktree,
  HermesRepoPullRequests,
  HermesRepoStatus,
  HermesReviewList,
  HermesReviewShipInfo
} from '@/global'
import { hermesApi } from '@/hermes'

import { desktopFsProfile, isDesktopFsRemoteMode } from './desktop-fs'

// Remote-aware git facade. Locally the desktop runs git through Electron
// (window.hermesDesktop.git); on a remote gateway that's the wrong filesystem,
// so we mirror the same surface over the dashboard REST API (/api/git/*) — the
// coding rail, worktree lanes, review pane, and branch ops then act on the
// BACKEND repo where sessions actually run. Mirrors desktop-fs.ts.

type GitBridge = NonNullable<NonNullable<Window['hermesDesktop']>['git']>

function desktopApi<T>(path: string, body?: Record<string, unknown>): Promise<T> {
  const desktop = window.hermesDesktop

  if (!desktop) {
    throw new Error('Hermes Desktop bridge is unavailable')
  }

  return hermesApi<T>(
    body ? { body, method: 'POST', path, profile: desktopFsProfile() } : { path, profile: desktopFsProfile() }
  )
}

function gitGet<T>(route: string, params: Record<string, boolean | null | number | string | undefined>): Promise<T> {
  const query = new URLSearchParams()

  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined) {
      query.set(key, String(value))
    }
  }

  return desktopApi<T>(`/api/git/${route}?${query.toString()}`)
}

function gitPost<T>(route: string, body: Record<string, unknown>): Promise<T> {
  return desktopApi<T>(`/api/git/${route}`, body)
}

const remoteGit: GitBridge = {
  worktreeList: async repoPath =>
    (await gitGet<{ worktrees: HermesGitWorktree[] }>('worktrees', { path: repoPath })).worktrees,

  worktreeAdd: (repoPath, options) => gitPost('worktree/add', { path: repoPath, ...options }),

  worktreeRemove: (repoPath, worktreePath, options) =>
    gitPost('worktree/remove', { force: options?.force ?? false, path: repoPath, worktreePath }),

  branchSwitch: (repoPath, branch) => gitPost('branch/switch', { branch, path: repoPath }),

  branchList: async repoPath =>
    (await gitGet<{ branches: HermesGitBranch[] }>('branches', { path: repoPath })).branches,

  baseBranchList: async repoPath =>
    (await gitGet<{ branches: HermesGitBaseBranch[] }>('base-branches', { path: repoPath })).branches,

  repoStatus: repoPath => gitGet<HermesRepoStatus | null>('status', { path: repoPath }),

  tagList: async repoPath => (await gitGet<{ tags: HermesGitTag[] }>('tags', { path: repoPath })).tags,

  stashList: async repoPath => (await gitGet<{ stashes: HermesGitStash[] }>('stashes', { path: repoPath })).stashes,

  branchCreate: (repoPath, name, base) => gitPost('branch/create', { base: base ?? null, name, path: repoPath }),

  branchRename: (repoPath, name, newName) => gitPost('branch/rename', { name, newName, path: repoPath }),

  branchDelete: (repoPath, name, force) => gitPost('branch/delete', { force: force ?? false, name, path: repoPath }),

  tagCreate: (repoPath, name, target) => gitPost('tag/create', { name, path: repoPath, target: target ?? null }),

  tagDelete: (repoPath, name) => gitPost('tag/delete', { name, path: repoPath }),

  stashCreate: (repoPath, message, includeUntracked) =>
    gitPost('stash/create', { includeUntracked: includeUntracked ?? false, message: message ?? null, path: repoPath }),

  stashApply: (repoPath, index) => gitPost('stash/apply', { index, path: repoPath }),

  stashDrop: (repoPath, index) => gitPost('stash/drop', { index, path: repoPath }),

  fetch: (repoPath, remote) => gitPost('fetch', { path: repoPath, remote: remote ?? null }),

  pull: (repoPath, rebase) => gitPost('pull', { path: repoPath, rebase: rebase ?? false }),

  fileDiff: async (repoPath, filePath) =>
    (await gitGet<{ diff: string }>('file-diff', { file: filePath, path: repoPath })).diff,

  review: {
    list: (repoPath, scope, baseRef) =>
      gitGet<HermesReviewList>('review/list', { base: baseRef, path: repoPath, scope }),

    diff: async (repoPath, filePath, scope, baseRef, staged) =>
      (await gitGet<{ diff: string }>('review/diff', { base: baseRef, file: filePath, path: repoPath, scope, staged }))
        .diff,

    history: async (repoPath, limit) =>
      (await gitGet<{ commits: HermesGitCommit[] }>('review/history', { limit, path: repoPath })).commits,

    historyDiff: async (repoPath, sha) =>
      (await gitGet<{ diff: string }>('review/history-diff', { path: repoPath, sha })).diff,

    stage: (repoPath, filePath) => gitPost('review/stage', { file: filePath || null, path: repoPath }),

    unstage: (repoPath, filePath) => gitPost('review/unstage', { file: filePath || null, path: repoPath }),

    revert: (repoPath, filePath) => gitPost('review/revert', { file: filePath || null, path: repoPath }),

    revParse: async (repoPath, ref) =>
      (await gitGet<{ sha: null | string }>('review/rev-parse', { path: repoPath, ref })).sha,

    commit: (repoPath, message, push) => gitPost('review/commit', { message, path: repoPath, push }),

    commitContext: repoPath => gitGet('review/commit-context', { path: repoPath }),

    push: repoPath => gitPost('review/push', { path: repoPath }),

    shipInfo: repoPath => gitGet<HermesReviewShipInfo>('review/ship-info', { path: repoPath }),

    prList: (repoPath, branches, numbers) =>
      gitPost<HermesRepoPullRequests>('review/pr-list', { branches, numbers: numbers ?? [], path: repoPath }),

    // Remote gateways have no PR-comment route yet; resolve to null so the
    // paste degrades to a plain URL instead of throwing mid-paste.
    fetchPrComment: async () => null,

    createPr: repoPath => gitPost('review/create-pr', { path: repoPath })
  },

  // Repo discovery is a local-disk crawl; on a remote gateway the backend
  // already merges session-derived repos, so this is a no-op.
  scanRepos: async () => []
}

export function desktopGit(): GitBridge | undefined {
  if (typeof window === 'undefined') {
    return undefined
  }

  // Browser-hosted Desktop has no Electron git IPC; route through the same
  // REST facade remote gateways use so worktrees/review hit the serving backend.
  const browserHost =
    typeof document !== 'undefined' && document.documentElement.dataset.hermesDesktopHost === 'browser'

  return isDesktopFsRemoteMode() || browserHost ? remoteGit : window.hermesDesktop?.git
}
