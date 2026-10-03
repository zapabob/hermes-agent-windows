import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { HermesGitCommit, HermesReviewFile, HermesReviewShipInfo } from '@/global'

import {
  $reviewCommitDefault,
  $reviewCommitMsgBusy,
  $reviewDiff,
  $reviewDiffLoading,
  $reviewFiles,
  $reviewHistory,
  $reviewHistoryDiff,
  $reviewHistoryDiffLoading,
  $reviewHistoryLoading,
  $reviewIsRepo,
  $reviewLoading,
  $reviewMaxChurn,
  $reviewOpen,
  $reviewRevertTarget,
  $reviewScopeCwd,
  $reviewScopeTarget,
  $reviewSelectedPath,
  $reviewShipBusy,
  $reviewShipInfo,
  $reviewTreeMode,
  $reviewView,
  cancelRevert,
  clearReviewCommitSelection,
  clearReviewSelection,
  closeReview,
  commitChanges,
  confirmRevert,
  createOrOpenPr,
  generateCommitMessage,
  openReview,
  pushChanges,
  refreshReview,
  refreshReviewHistory,
  refreshShipInfo,
  requestRevert,
  revealReview,
  revertReviewFile,
  selectReviewCommit,
  selectReviewFile,
  setReviewView,
  stageReviewFile,
  toggleReview,
  toggleReviewTreeMode,
  unstageReviewFile
} from './review'
import { $currentCwd, $selectedStoredSessionId, $workspaceCwdOwner } from './session'

// requestOneShot is the only cross-module dependency that must be faked (it
// reaches the gateway); everything else routes through window.hermesDesktop.git,
// which we stub per-test like the sibling coding-status.test.ts does.
const requestOneShot = vi.fn(async (_args: unknown) => 'generated message')
vi.mock('@/lib/oneshot', () => ({ requestOneShot: (args: unknown) => requestOneShot(args) }))
// refreshRepoStatus is a fire-and-forget side effect of mutations; stub it so it
// doesn't try to hit the (absent) probe and log. repoStatusForCwd is read when a
// new PR binds its session to the branch it came from — no probe here, so no
// branch either.
vi.mock('./coding-status', () => ({ refreshRepoStatus: vi.fn(), repoStatusForCwd: () => ({ get: () => null }) }))

function file(path: string, over: Partial<HermesReviewFile> = {}): HermesReviewFile {
  return { path, status: 'modified', staged: false, added: 1, removed: 0, ...over } as HermesReviewFile
}

type ReviewStub = Record<string, ReturnType<typeof vi.fn>>

// Install a review bridge on window.hermesDesktop. Any op not supplied defaults
// to a resolved no-op so a test only declares what it exercises.
function stubReview(over: ReviewStub = {}) {
  const review: ReviewStub = {
    list: vi.fn(async () => ({ files: [] })),
    diff: vi.fn(async () => ''),
    history: vi.fn(async () => []),
    historyDiff: vi.fn(async () => ''),
    stage: vi.fn(async () => undefined),
    unstage: vi.fn(async () => undefined),
    revert: vi.fn(async () => undefined),
    commit: vi.fn(async () => undefined),
    commitContext: vi.fn(async () => ({ diff: 'd', recent: 'r' })),
    push: vi.fn(async () => undefined),
    shipInfo: vi.fn(async () => ({ ghReady: false, pr: null })),
    createPr: vi.fn(async () => ({ url: 'https://example.com/pr/1' })),
    ...over
  }

  ;(window as unknown as { hermesDesktop?: unknown }).hermesDesktop = {
    git: { review },
    openExternal: vi.fn()
  }

  return review
}

beforeEach(() => {
  requestOneShot.mockClear()
  requestOneShot.mockResolvedValue('generated message')
  // Reset stores touched across tests.
  $reviewOpen.set(false)
  $reviewFiles.set([])
  $reviewLoading.set(false)
  $reviewIsRepo.set(true)
  $reviewDiff.set(null)
  $reviewDiffLoading.set(false)
  $reviewHistory.set([])
  $reviewHistoryLoading.set(false)
  $reviewHistoryDiff.set(null)
  $reviewHistoryDiffLoading.set(false)
  $reviewView.set('changes')
  $reviewSelectedPath.set(null)
  $reviewShipInfo.set({ ghReady: false, pr: null })
  $reviewShipBusy.set(false)
  $reviewCommitMsgBusy.set(false)
  $reviewRevertTarget.set(undefined)
  $reviewScopeCwd.set(null)
  $reviewScopeTarget.set('main')
  $selectedStoredSessionId.set(null)
  $workspaceCwdOwner.set(null)
  $currentCwd.set('/repo')
})

describe('selected conversation repository authority', () => {
  it('refuses writes while the remembered cwd belongs to another conversation', async () => {
    const review = stubReview()
    $selectedStoredSessionId.set('conversation-a')
    $workspaceCwdOwner.set('conversation-a')
    $currentCwd.set('/repo-a')
    $selectedStoredSessionId.set('conversation-b')

    await commitChanges('message', { push: true })
    await pushChanges()
    await stageReviewFile('file.ts')
    await unstageReviewFile('file.ts')
    await revertReviewFile('file.ts')
    await createOrOpenPr()

    for (const name of ['commit', 'push', 'stage', 'unstage', 'revert', 'createPr']) {
      expect(review[name]).not.toHaveBeenCalled()
    }
  })

  it('commits to the selected conversation repository after its cwd is resolved', async () => {
    const review = stubReview()
    $selectedStoredSessionId.set('conversation-b')
    $currentCwd.set('/repo-b')
    $workspaceCwdOwner.set('conversation-b')

    await commitChanges('message', { push: true })

    expect(review.commit).toHaveBeenCalledWith('/repo-b', 'message', true)
  })

  it('preserves an explicitly selected tile repository during main conversation changes', async () => {
    const review = stubReview()
    openReview('/tile-repo', 'tile:one')
    $selectedStoredSessionId.set('unresolved-main')
    await commitChanges('tile message')
    expect(review.commit).toHaveBeenCalledWith('/tile-repo', 'tile message', false)
  })

  it('does not retarget a tile with an unresolved cwd to the main repository', async () => {
    const review = stubReview()
    openReview(null, 'tile:one')
    await commitChanges('message')
    expect(review.commit).not.toHaveBeenCalled()
  })

  it('clears stale files and pending revert when conversation authority changes', () => {
    stubReview()
    $reviewOpen.set(true)
    $reviewFiles.set([file('old.ts')])
    requestRevert('old.ts')
    $selectedStoredSessionId.set('conversation-b')
    expect($reviewFiles.get()).toEqual([])
    expect($reviewRevertTarget.get()).toBeUndefined()
  })

  it('drops a commit message generated for a previous repository', async () => {
    let resolve!: (value: string) => void
    requestOneShot.mockReturnValueOnce(
      new Promise<string>(done => {
        resolve = done
      })
    )
    stubReview()
    const pending = generateCommitMessage()
    await Promise.resolve()
    $currentCwd.set('/repo-b')
    resolve('message for repo-a')
    expect(await pending).toBe('')
  })

  it('clears a previous repository PR before the new probe completes', () => {
    stubReview({ shipInfo: vi.fn(() => new Promise(() => {})) })
    $reviewOpen.set(true)
    $reviewShipInfo.set({ ghReady: true, pr: { url: 'https://example.test/old' } } as HermesReviewShipInfo)
    $currentCwd.set('/repo-b')
    expect($reviewShipInfo.get().pr).toBeNull()
  })
})

afterEach(() => {
  delete (window as unknown as { hermesDesktop?: unknown }).hermesDesktop
})

describe('refreshReview', () => {
  it('is a no-op that clears state when the pane is closed', async () => {
    const review = stubReview()
    $reviewOpen.set(false)
    $reviewFiles.set([file('a.ts')])

    await refreshReview()

    expect(review.list).not.toHaveBeenCalled()
    expect($reviewFiles.get()).toEqual([])
    expect($reviewLoading.get()).toBe(false)
  })

  it('flags not-a-repo (and clears loading) when there is no bridge/cwd', async () => {
    delete (window as unknown as { hermesDesktop?: unknown }).hermesDesktop
    $reviewOpen.set(true)
    $reviewLoading.set(true)

    await refreshReview()

    expect($reviewIsRepo.get()).toBe(false)
    expect($reviewLoading.get()).toBe(false)
  })

  it('populates the changed-file list from the bridge', async () => {
    stubReview({ list: vi.fn(async () => ({ files: [file('a.ts'), file('b.ts')] })) })
    $reviewOpen.set(true)

    await refreshReview()

    expect($reviewFiles.get().map(f => f.path)).toEqual(['a.ts', 'b.ts'])
    expect($reviewIsRepo.get()).toBe(true)
    expect($reviewLoading.get()).toBe(false)
  })

  it('filters excluded paths (node_modules et al.) out of the list', async () => {
    stubReview({ list: vi.fn(async () => ({ files: [file('src/a.ts'), file('node_modules/x/index.js')] })) })
    $reviewOpen.set(true)

    await refreshReview()

    expect($reviewFiles.get().map(f => f.path)).toEqual(['src/a.ts'])
  })

  it('drops a selection whose file vanished from the new list', async () => {
    stubReview({ list: vi.fn(async () => ({ files: [file('kept.ts')] })) })
    $reviewOpen.set(true)
    $reviewSelectedPath.set('gone.ts')
    $reviewDiff.set('old diff')

    await refreshReview()

    expect($reviewSelectedPath.get()).toBeNull()
    expect($reviewDiff.get()).toBeNull()
  })

  it('clears the list but keeps isRepo true when the bridge throws', async () => {
    stubReview({
      list: vi.fn(async () => {
        throw new Error('git failed')
      })
    })
    $reviewOpen.set(true)
    $reviewFiles.set([file('stale.ts')])

    await refreshReview()

    expect($reviewFiles.get()).toEqual([])
    expect($reviewIsRepo.get()).toBe(true)
    expect($reviewLoading.get()).toBe(false)
  })
})

describe('$reviewMaxChurn', () => {
  it('is the largest added+removed across files', () => {
    $reviewFiles.set([file('a', { added: 3, removed: 2 }), file('b', { added: 10, removed: 1 }), file('c')])
    expect($reviewMaxChurn.get()).toBe(11)
  })

  it('is 0 for an empty list', () => {
    $reviewFiles.set([])
    expect($reviewMaxChurn.get()).toBe(0)
  })
})

describe('selectReviewFile / clearReviewSelection', () => {
  it('sets the selected path and fetches its diff', async () => {
    const review = stubReview({ diff: vi.fn(async () => 'the diff') })

    await selectReviewFile(file('a.ts'))

    expect($reviewSelectedPath.get()).toBe('a.ts')
    expect($reviewDiff.get()).toBe('the diff')
    expect($reviewDiffLoading.get()).toBe(false)
    expect(review.diff).toHaveBeenCalledWith('/repo', 'a.ts', 'uncommitted', null, false)
  })

  it('coerces a falsy diff to empty string (not null)', async () => {
    stubReview({ diff: vi.fn(async () => '') })

    await selectReviewFile(file('a.ts'))

    expect($reviewDiff.get()).toBe('')
  })

  it('sets diff null when there is no bridge', async () => {
    delete (window as unknown as { hermesDesktop?: unknown }).hermesDesktop

    await selectReviewFile(file('a.ts'))

    expect($reviewSelectedPath.get()).toBe('a.ts')
    expect($reviewDiff.get()).toBeNull()
  })

  it('clears path, diff and loading', () => {
    $reviewSelectedPath.set('a.ts')
    $reviewDiff.set('x')
    $reviewDiffLoading.set(true)

    clearReviewSelection()

    expect($reviewSelectedPath.get()).toBeNull()
    expect($reviewDiff.get()).toBeNull()
    expect($reviewDiffLoading.get()).toBe(false)
  })
})

const commit = (over: Partial<HermesGitCommit> = {}): HermesGitCommit => ({
  author: 'Hermes Test',
  authoredAt: '2026-08-10T12:00:00+00:00',
  parents: ['0123456789abcdef0123456789abcdef01234567'],
  sha: '1234567890abcdef1234567890abcdef12345678',
  shortSha: '1234567',
  subject: 'add history view',
  ...over
})

describe('review history', () => {
  it('loads bounded history only while the pane is open', async () => {
    const review = stubReview({ history: vi.fn(async () => [commit()]) })
    $reviewOpen.set(true)

    await refreshReviewHistory()

    expect(review.history).toHaveBeenCalledWith('/repo', 50)
    expect($reviewHistory.get()).toEqual([commit()])
    expect($reviewHistoryLoading.get()).toBe(false)
  })

  it('does not call history while closed and clears stale results', async () => {
    const review = stubReview()
    $reviewHistory.set([commit()])

    await refreshReviewHistory()

    expect(review.history).not.toHaveBeenCalled()
    expect($reviewHistory.get()).toEqual([])
  })

  it('selects one commit and fetches only its diff', async () => {
    const selected = commit()
    const review = stubReview({ historyDiff: vi.fn(async () => 'commit diff') })

    await selectReviewCommit(selected)

    expect(review.historyDiff).toHaveBeenCalledWith('/repo', selected.sha)
    expect($reviewHistoryDiff.get()).toBe('commit diff')
    expect($reviewHistoryDiffLoading.get()).toBe(false)

    clearReviewCommitSelection()
    expect($reviewHistoryDiff.get()).toBeNull()
  })

  it('switching to history refreshes it without replacing the change list', async () => {
    const review = stubReview({ history: vi.fn(async () => [commit()]) })
    $reviewOpen.set(true)
    $reviewFiles.set([file('unchanged.ts')])

    setReviewView('history')
    await Promise.resolve()
    await Promise.resolve()

    expect(review.history).toHaveBeenCalledWith('/repo', 50)
    expect($reviewFiles.get()).toEqual([file('unchanged.ts')])
  })
})

describe('view state', () => {
  it('toggleReviewTreeMode flips list <-> tree', () => {
    $reviewTreeMode.set('tree')
    toggleReviewTreeMode()
    expect($reviewTreeMode.get()).toBe('list')
    toggleReviewTreeMode()
    expect($reviewTreeMode.get()).toBe('tree')
  })

  it('openReview opens the pane and kicks off a refresh', async () => {
    const review = stubReview()
    openReview()
    expect($reviewOpen.get()).toBe(true)
    expect($reviewScopeCwd.get()).toBeNull()
    // openReview fires refreshReview + refreshShipInfo without awaiting.
    await Promise.resolve()
    await Promise.resolve()
    expect(review.list).toHaveBeenCalledWith('/repo', 'uncommitted', null)
  })

  it('openReview pins the pane to a tile worktree when scoped', async () => {
    const review = stubReview({
      list: vi.fn(async () => ({ files: [file('tile.ts')] }))
    })

    openReview('/tile-worktree')
    expect($reviewOpen.get()).toBe(true)
    expect($reviewScopeCwd.get()).toBe('/tile-worktree')
    await Promise.resolve()
    await Promise.resolve()
    expect(review.list).toHaveBeenCalledWith('/tile-worktree', 'uncommitted', null)
  })

  it('openReview remembers the tile composer that owns the scoped worktree', () => {
    stubReview()

    openReview('/tile-worktree', 'tile:project-b')

    expect($reviewScopeCwd.get()).toBe('/tile-worktree')
    expect($reviewScopeTarget.get()).toBe('tile:project-b')
  })

  it('revealReview re-homes the origin when the repo stays the same', () => {
    stubReview()
    openReview('/tile-worktree', 'tile:project-a')

    revealReview('/tile-worktree', 'tile:project-b')

    expect($reviewScopeTarget.get()).toBe('tile:project-b')
  })

  it('narrow toggle re-homes the origin before showing the overlay', () => {
    const originalMatchMedia = window.matchMedia

    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn(() => ({ matches: true }))
    })

    try {
      stubReview()
      openReview('/project-a', 'tile:project-a')

      toggleReview('/project-b', 'tile:project-b')

      expect($reviewScopeCwd.get()).toBe('/project-b')
      expect($reviewScopeTarget.get()).toBe('tile:project-b')
    } finally {
      Object.defineProperty(window, 'matchMedia', { configurable: true, value: originalMatchMedia })
    }
  })

  it('closeReview closes the pane, clears selection, and drops scope', () => {
    stubReview()
    $reviewOpen.set(true)
    $reviewScopeCwd.set('/tile-worktree')
    $reviewSelectedPath.set('a.ts')
    $reviewDiff.set('x')

    closeReview()

    expect($reviewOpen.get()).toBe(false)
    expect($reviewScopeCwd.get()).toBeNull()
    expect($reviewScopeTarget.get()).toBe('main')
    expect($reviewSelectedPath.get()).toBeNull()
    expect($reviewDiff.get()).toBeNull()
  })

  it('scoped pane ignores main-pane cwd changes', async () => {
    const review = stubReview({
      list: vi.fn(async (cwd: string) => ({ files: [file(cwd === '/tile' ? 'tile.ts' : 'main.ts')] }))
    })

    openReview('/tile')
    await Promise.resolve()
    await Promise.resolve()
    review.list.mockClear()

    // Main session hops repos; the pane is still pinned to the tile.
    $currentCwd.set('/somewhere-else')
    await Promise.resolve()
    await Promise.resolve()

    expect($reviewScopeCwd.get()).toBe('/tile')
    expect(review.list).not.toHaveBeenCalled()
  })
})

describe('mutations', () => {
  it('stageReviewFile forwards the path and re-syncs', async () => {
    const review = stubReview()
    $reviewOpen.set(true) // afterMutation's refreshReview only lists when the pane is open
    await stageReviewFile('a.ts')
    expect(review.stage).toHaveBeenCalledWith('/repo', 'a.ts')
    expect(review.list).toHaveBeenCalled()
  })

  it('unstageReviewFile forwards the path', async () => {
    const review = stubReview()
    await unstageReviewFile('a.ts')
    expect(review.unstage).toHaveBeenCalledWith('/repo', 'a.ts')
  })

  it('revertReviewFile forwards the path', async () => {
    const review = stubReview()
    await revertReviewFile('a.ts')
    expect(review.revert).toHaveBeenCalledWith('/repo', 'a.ts')
  })

  it('stage with null path means "all"', async () => {
    const review = stubReview()
    await stageReviewFile(null)
    expect(review.stage).toHaveBeenCalledWith('/repo', null)
  })
})

describe('revert confirm dialog', () => {
  it('requestRevert opens a target, cancelRevert closes it', () => {
    requestRevert('a.ts')
    expect($reviewRevertTarget.get()).toEqual({ path: 'a.ts' })
    cancelRevert()
    expect($reviewRevertTarget.get()).toBeUndefined()
  })

  it('requestRevert(null) encodes the "revert all" target distinctly from closed', () => {
    requestRevert(null)
    expect($reviewRevertTarget.get()).toEqual({ path: null })
  })

  it('confirmRevert closes the dialog then performs the revert', async () => {
    const review = stubReview()
    requestRevert('a.ts')

    await confirmRevert()

    expect($reviewRevertTarget.get()).toBeUndefined()
    expect(review.revert).toHaveBeenCalledWith('/repo', 'a.ts')
  })

  it('confirmRevert is a no-op when nothing is pending', async () => {
    const review = stubReview()
    $reviewRevertTarget.set(undefined)

    await confirmRevert()

    expect(review.revert).not.toHaveBeenCalled()
  })
})

describe('ship flow', () => {
  it('commitChanges commits the trimmed message and toggles the busy flag', async () => {
    const review = stubReview()
    const seen: boolean[] = []
    const unsub = $reviewShipBusy.subscribe(v => seen.push(v))

    await commitChanges('  a message  ', { push: true })

    expect(review.commit).toHaveBeenCalledWith('/repo', 'a message', true)
    expect(seen).toContain(true)
    expect($reviewShipBusy.get()).toBe(false)
    unsub()
  })

  it('commitChanges bails on a blank message', async () => {
    const review = stubReview()
    await commitChanges('   ')
    expect(review.commit).not.toHaveBeenCalled()
  })

  it('pushChanges pushes and refreshes ship info', async () => {
    const review = stubReview()
    await pushChanges()
    expect(review.push).toHaveBeenCalledWith('/repo')
  })

  it('createOrOpenPr opens the existing PR without creating a new one', async () => {
    const review = stubReview()
    $reviewShipInfo.set({ ghReady: true, pr: { url: 'https://example.com/pr/9' } } as HermesReviewShipInfo)

    await createOrOpenPr()

    expect(review.createPr).not.toHaveBeenCalled()
    expect(
      (window.hermesDesktop as unknown as { openExternal: ReturnType<typeof vi.fn> }).openExternal
    ).toHaveBeenCalledWith('https://example.com/pr/9')
  })

  it('createOrOpenPr creates a PR when none exists, then opens it', async () => {
    const review = stubReview({ createPr: vi.fn(async () => ({ url: 'https://example.com/pr/new' })) })
    $reviewShipInfo.set({ ghReady: true, pr: null })

    await createOrOpenPr()

    expect(review.createPr).toHaveBeenCalledWith('/repo')
    expect(
      (window.hermesDesktop as unknown as { openExternal: ReturnType<typeof vi.fn> }).openExternal
    ).toHaveBeenCalledWith('https://example.com/pr/new')
  })
})

describe('refreshShipInfo', () => {
  it('populates ship info from the bridge', async () => {
    const info: HermesReviewShipInfo = {
      ghReady: true,
      pr: { url: 'https://example.com/pr/3' }
    } as HermesReviewShipInfo

    stubReview({ shipInfo: vi.fn(async () => info) })

    await refreshShipInfo()

    expect($reviewShipInfo.get()).toEqual(info)
  })

  it('resets ship info when there is no bridge', async () => {
    delete (window as unknown as { hermesDesktop?: unknown }).hermesDesktop
    $reviewShipInfo.set({ ghReady: true, pr: { url: 'x' } } as HermesReviewShipInfo)

    await refreshShipInfo()

    expect($reviewShipInfo.get()).toEqual({ ghReady: false, pr: null })
  })

  it('resets ship info when the bridge throws', async () => {
    stubReview({
      shipInfo: vi.fn(async () => {
        throw new Error('gh missing')
      })
    })
    $reviewShipInfo.set({ ghReady: true, pr: { url: 'x' } } as HermesReviewShipInfo)

    await refreshShipInfo()

    expect($reviewShipInfo.get()).toEqual({ ghReady: false, pr: null })
  })
})

describe('generateCommitMessage', () => {
  it('returns a one-shot message from the working-tree diff', async () => {
    stubReview()

    const msg = await generateCommitMessage('avoid this')

    expect(msg).toBe('generated message')
    expect(requestOneShot).toHaveBeenCalledWith(
      expect.objectContaining({
        template: 'commit_message',
        variables: expect.objectContaining({ avoid: 'avoid this', diff: 'd', recent_commits: 'r' })
      })
    )
    expect($reviewCommitMsgBusy.get()).toBe(false)
  })

  it('returns empty (no model call) when the diff is blank', async () => {
    stubReview({ commitContext: vi.fn(async () => ({ diff: '   ', recent: '' })) })

    const msg = await generateCommitMessage()

    expect(msg).toBe('')
    expect(requestOneShot).not.toHaveBeenCalled()
  })

  it('returns empty when the bridge lacks commitContext', async () => {
    const review = stubReview()
    delete review.commitContext

    const msg = await generateCommitMessage()

    expect(msg).toBe('')
  })
})

describe('$reviewCommitDefault', () => {
  it('remembers the split-button default action', () => {
    $reviewCommitDefault.set('commitPush')
    expect($reviewCommitDefault.get()).toBe('commitPush')
    $reviewCommitDefault.set('commit')
    expect($reviewCommitDefault.get()).toBe('commit')
  })
})
