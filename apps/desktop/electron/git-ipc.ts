// IPC surface for git-driven features: worktree management ("Start work"),
// the composer coding rail's repo status, the Codex-style review pane, and
// repo-first project discovery. Extracted from main.ts; the git/gh binary
// resolvers stay injected because main.ts also uses them for self-update and
// plugin installs.
import { ipcMain } from 'electron'

import { configureGitPolicyRuntime, type GitPolicyRuntime } from './git-execution-policy'
import {
  branchCreate,
  branchDelete,
  branchRename,
  gitFetch,
  gitPull,
  listStashes,
  listTags,
  stashApply,
  stashCreate,
  stashDrop,
  tagCreate,
  tagDelete
} from './git-ref-ops'
import { scanGitRepos } from './git-repo-scan'
import {
  fileDiffVsHead,
  repoStatus,
  reviewCommit,
  reviewCommitContext,
  reviewCreatePr,
  reviewDiff,
  reviewFetchPrComment,
  reviewHistory,
  reviewHistoryDiff,
  reviewList,
  reviewPrList,
  reviewPush,
  reviewRevert,
  reviewRevParse,
  reviewShipInfo,
  reviewStage,
  reviewUnstage
} from './git-review-ops'
import {
  addWorktree,
  listBaseBranches,
  listBranches,
  listWorktrees,
  removeWorktree,
  switchBranch
} from './git-worktree-ops'

export interface GitIpcDeps {
  resolveGitBinary: () => string
  resolveGhBinary: () => string | null
  resolveGitPolicyRuntime: () => GitPolicyRuntime | null
}

export function registerGitIpc({ resolveGitBinary, resolveGhBinary, resolveGitPolicyRuntime }: GitIpcDeps) {
  configureGitPolicyRuntime(resolveGitPolicyRuntime, resolveGitBinary)
  // Git-driven worktree management ("Start work" flow). Errors surface to the
  // renderer as rejected promises so it can toast a friendly message.
  ipcMain.handle('hermes:git:worktreeList', async (_event, repoPath) => listWorktrees(repoPath, resolveGitBinary()))

  ipcMain.handle('hermes:git:worktreeAdd', async (_event, repoPath, options) =>
    addWorktree(repoPath, options || {}, resolveGitBinary())
  )

  ipcMain.handle('hermes:git:worktreeRemove', async (_event, repoPath, worktreePath, options) =>
    removeWorktree(repoPath, worktreePath, options || {}, resolveGitBinary())
  )

  ipcMain.handle('hermes:git:branchSwitch', async (_event, repoPath, branch) =>
    switchBranch(repoPath, branch, resolveGitBinary())
  )

  ipcMain.handle('hermes:git:branchList', async (_event, repoPath) => listBranches(repoPath, resolveGitBinary()))

  ipcMain.handle('hermes:git:baseBranchList', async (_event, repoPath) =>
    listBaseBranches(repoPath, resolveGitBinary())
  )

  // Compact repo status (branch, ahead/behind, change counts + files) for the
  // composer coding rail. Returns null on a non-repo / remote backend so the rail
  // hides cleanly rather than erroring.
  ipcMain.handle('hermes:git:repoStatus', async (_event, repoPath) => repoStatus(repoPath, resolveGitBinary()))

  // Branch / tag / stash CRUD and fetch/pull for the SCM rail. Reads degrade
  // to empty on a non-repo / remote backend; mutations reject so the renderer
  // can toast the reason.
  ipcMain.handle('hermes:git:tagList', async (_event, repoPath) => listTags(repoPath, resolveGitBinary()))
  ipcMain.handle('hermes:git:stashList', async (_event, repoPath) => listStashes(repoPath, resolveGitBinary()))
  ipcMain.handle('hermes:git:branchCreate', async (_event, repoPath, name, base) =>
    branchCreate(repoPath, name, base, resolveGitBinary())
  )
  ipcMain.handle('hermes:git:branchRename', async (_event, repoPath, name, newName) =>
    branchRename(repoPath, name, newName, resolveGitBinary())
  )
  ipcMain.handle('hermes:git:branchDelete', async (_event, repoPath, name, force) =>
    branchDelete(repoPath, name, force, resolveGitBinary())
  )
  ipcMain.handle('hermes:git:tagCreate', async (_event, repoPath, name, target) =>
    tagCreate(repoPath, name, target, resolveGitBinary())
  )
  ipcMain.handle('hermes:git:tagDelete', async (_event, repoPath, name) =>
    tagDelete(repoPath, name, resolveGitBinary())
  )
  ipcMain.handle('hermes:git:stashCreate', async (_event, repoPath, message, includeUntracked) =>
    stashCreate(repoPath, message, includeUntracked, resolveGitBinary())
  )
  ipcMain.handle('hermes:git:stashApply', async (_event, repoPath, index) =>
    stashApply(repoPath, index, resolveGitBinary())
  )
  ipcMain.handle('hermes:git:stashDrop', async (_event, repoPath, index) =>
    stashDrop(repoPath, index, resolveGitBinary())
  )
  ipcMain.handle('hermes:git:fetch', async (_event, repoPath, remote) => gitFetch(repoPath, remote, resolveGitBinary()))
  ipcMain.handle('hermes:git:pull', async (_event, repoPath, rebase) => gitPull(repoPath, rebase, resolveGitBinary()))

  // Codex-style review pane: list changed files for a scope, fetch one file's
  // unified diff, and stage / unstage / revert. Reads return empty on failure;
  // mutations reject so the renderer can toast.
  ipcMain.handle('hermes:git:review:list', async (_event, repoPath, scope, baseRef) =>
    reviewList(repoPath, scope, baseRef, resolveGitBinary())
  )
  ipcMain.handle('hermes:git:review:diff', async (_event, repoPath, filePath, scope, baseRef, staged) =>
    reviewDiff(repoPath, filePath, scope, baseRef, staged, resolveGitBinary())
  )
  ipcMain.handle('hermes:git:review:history', async (_event, repoPath, limit) =>
    reviewHistory(repoPath, limit, resolveGitBinary())
  )
  ipcMain.handle('hermes:git:review:historyDiff', async (_event, repoPath, sha) =>
    reviewHistoryDiff(repoPath, sha, resolveGitBinary())
  )
  // Working-tree-vs-HEAD diff for one file (the preview's "show the diff" view).
  ipcMain.handle('hermes:git:fileDiff', async (_event, repoPath, filePath) =>
    fileDiffVsHead(repoPath, filePath, resolveGitBinary())
  )
  ipcMain.handle('hermes:git:review:stage', async (_event, repoPath, filePath) =>
    reviewStage(repoPath, filePath ?? null, resolveGitBinary())
  )
  ipcMain.handle('hermes:git:review:unstage', async (_event, repoPath, filePath) =>
    reviewUnstage(repoPath, filePath ?? null, resolveGitBinary())
  )
  ipcMain.handle('hermes:git:review:revert', async (_event, repoPath, filePath) =>
    reviewRevert(repoPath, filePath ?? null, resolveGitBinary())
  )
  ipcMain.handle('hermes:git:review:revParse', async (_event, repoPath, ref) =>
    reviewRevParse(repoPath, ref, resolveGitBinary())
  )
  ipcMain.handle('hermes:git:review:commit', async (_event, repoPath, message, push) =>
    reviewCommit(repoPath, message, Boolean(push), resolveGitBinary())
  )
  ipcMain.handle('hermes:git:review:commitContext', async (_event, repoPath) =>
    reviewCommitContext(repoPath, resolveGitBinary())
  )
  ipcMain.handle('hermes:git:review:push', async (_event, repoPath) => reviewPush(repoPath, resolveGitBinary()))
  ipcMain.handle('hermes:git:review:shipInfo', async (_event, repoPath) => reviewShipInfo(repoPath, resolveGhBinary()))
  ipcMain.handle('hermes:git:review:prList', async (_event, repoPath, branches, numbers) =>
    reviewPrList(repoPath, resolveGhBinary(), branches, numbers)
  )
  ipcMain.handle('hermes:git:review:fetchPrComment', async (_event, repoPath, url) =>
    reviewFetchPrComment(repoPath, resolveGhBinary(), url)
  )
  ipcMain.handle('hermes:git:review:createPr', async (_event, repoPath) =>
    reviewCreatePr(repoPath, resolveGitBinary(), resolveGhBinary())
  )

  // Repo-first project discovery: scan bounded roots for git repos (pure fs walk,
  // no native addon). Never throws to the renderer — failures yield an empty list.
  ipcMain.handle('hermes:git:scanRepos', async (_event, roots, options) => {
    try {
      return await scanGitRepos(roots || [], options || {})
    } catch {
      return []
    }
  })
}
