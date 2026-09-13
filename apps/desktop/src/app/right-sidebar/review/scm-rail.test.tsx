import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { HermesGitBranch, HermesGitStash, HermesGitTag } from '@/global'
import { I18nProvider } from '@/i18n'
import { $reviewOpen, $reviewScopeCwd } from '@/store/review'
import {
  $scmBranches,
  $scmBranchesLoading,
  $scmBusy,
  $scmStashes,
  $scmStashesLoading,
  $scmTags,
  $scmTagsLoading
} from '@/store/scm-refs'
import { $currentCwd } from '@/store/session'

import { ReviewScmRail } from './scm-rail'

// refreshRepoStatus is a fire-and-forget side effect of mutations; stub it so
// it doesn't try to hit the (absent) probe and log.
vi.mock('@/store/coding-status', () => ({ refreshRepoStatus: vi.fn(), repoStatusForCwd: () => ({ get: () => null }) }))

const tag = (over: Partial<HermesGitTag> = {}): HermesGitTag => ({
  name: 'v1.0',
  sha: '1234567890abcdef1234567890abcdef12345678',
  shortSha: '1234567',
  date: '2026-08-10T12:00:00+00:00',
  subject: 'release',
  ...over
})

const stash = (over: Partial<HermesGitStash> = {}): HermesGitStash => ({
  index: 0,
  id: 'stash@{0}',
  sha: '1234567890abcdef1234567890abcdef12345678',
  shortSha: '1234567',
  date: '2026-08-10T12:00:00+00:00',
  message: 'On main: wip',
  ...over
})

const branch = (over: Partial<HermesGitBranch> = {}): HermesGitBranch => ({
  name: 'feature',
  checkedOut: false,
  isDefault: false,
  isRemote: false,
  worktreePath: null,
  sha: '1234567890abcdef1234567890abcdef12345678',
  ...over
})

type GitStub = Record<string, ReturnType<typeof vi.fn>>

// Install a git bridge on window.hermesDesktop. Any op not supplied defaults
// to a resolved no-op so a test only declares what it exercises.
function stubGit(over: GitStub = {}) {
  const git: GitStub = {
    tagList: vi.fn(async () => []),
    stashList: vi.fn(async () => []),
    branchList: vi.fn(async () => []),
    branchCreate: vi.fn(async () => ({ ok: true })),
    branchRename: vi.fn(async () => ({ ok: true })),
    branchDelete: vi.fn(async () => ({ ok: true })),
    tagCreate: vi.fn(async () => ({ ok: true })),
    tagDelete: vi.fn(async () => ({ ok: true })),
    stashCreate: vi.fn(async () => ({ ok: true })),
    stashApply: vi.fn(async () => ({ ok: true })),
    stashDrop: vi.fn(async () => ({ ok: true })),
    fetch: vi.fn(async () => ({ ok: true })),
    pull: vi.fn(async () => ({ ok: true })),
    ...over
  }

  ;(window as unknown as { hermesDesktop?: unknown }).hermesDesktop = {
    git,
    openExternal: vi.fn()
  }

  return git
}

function renderRail() {
  return render(
    <I18nProvider configClient={null} initialLocale="en">
      <ReviewScmRail />
    </I18nProvider>
  )
}

function renderRailWithContainer() {
  return renderRail().container
}

describe('ReviewScmRail', () => {
  beforeEach(() => {
    $reviewOpen.set(false)
    $reviewScopeCwd.set(null)
    $currentCwd.set('/repo')
    $scmBranches.set([])
    $scmBranchesLoading.set(false)
    $scmTags.set([])
    $scmTagsLoading.set(false)
    $scmStashes.set([])
    $scmStashesLoading.set(false)
    $scmBusy.set(null)
  })

  afterEach(() => {
    cleanup()
    delete (window as unknown as { hermesDesktop?: unknown }).hermesDesktop
  })

  it('renders the empty state for all three sections', () => {
    renderRail()

    expect(screen.getByText('Branches')).toBeTruthy()
    expect(screen.getByText('Tags')).toBeTruthy()
    expect(screen.getByText('Stashes')).toBeTruthy()
    expect(screen.getByText('No branches')).toBeTruthy()
    expect(screen.getByText('No tags')).toBeTruthy()
    expect(screen.getByText('No stashes')).toBeTruthy()
  })

  it('lists branches and marks the checked-out one', () => {
    $scmBranches.set([
      {
        checkedOut: true,
        isDefault: true,
        isRemote: false,
        name: 'main',
        sha: '1234567890abcdef1234567890abcdef12345678',
        worktreePath: ''
      },
      {
        checkedOut: false,
        isDefault: false,
        isRemote: false,
        name: 'feature/scm',
        sha: 'abcdef1234567890abcdef1234567890abcdef12',
        worktreePath: ''
      }
    ])
    renderRail()

    expect(screen.getByText('main')).toBeTruthy()
    expect(screen.getByText('feature/scm')).toBeTruthy()
    expect(screen.getByText('Checked out')).toBeTruthy()
  })

  it('lists tags with short sha and date metadata', () => {
    $scmTags.set([
      { date: '2026-08-14T10:00:00+00:00', name: 'v1.0.0', sha: 'abcdef', shortSha: 'abcdef0', subject: 'release' }
    ])
    const container = renderRailWithContainer()

    const row = screen.getByText('v1.0.0').closest('div')
    expect(row?.textContent).toContain('abcdef0')
    expect(container.querySelector('time')?.getAttribute('dateTime')).toBe('2026-08-14T10:00:00+00:00')
  })

  it('lists stashes with index id and message', () => {
    $scmStashes.set([
      {
        date: '2026-08-14T11:00:00+00:00',
        id: 'stash@{0}',
        index: 0,
        message: 'On main: WIP scm rail',
        sha: '1234567890abcdef',
        shortSha: '1234567'
      }
    ])
    renderRail()

    expect(screen.getByText('stash@{0}')).toBeTruthy()
    expect(screen.getByText('On main: WIP scm rail')).toBeTruthy()
  })

  it('shows a skeleton while a section is loading with no data yet', () => {
    $scmBranchesLoading.set(true)
    const container = renderRailWithContainer()

    expect(screen.queryByText('No branches')).toBeNull()
    expect(container.querySelector('[data-slot="tree-skeleton"]')).toBeTruthy()
  })

  it('fetches and pulls from the toolbar', async () => {
    const git = stubGit()
    renderRail()

    fireEvent.click(screen.getByRole('button', { name: 'Fetch' }))
    await waitFor(() => expect(git.fetch).toHaveBeenCalledWith('/repo', null))

    fireEvent.click(screen.getByRole('button', { name: 'Pull' }))
    await waitFor(() => expect(git.pull).toHaveBeenCalledWith('/repo', false))
  })

  it('creates a branch from the section action', async () => {
    const git = stubGit()
    renderRail()

    fireEvent.click(screen.getByRole('button', { name: 'New branch' }))
    const dialog = screen.getByRole('dialog')
    const input = within(dialog).getByRole('textbox', { name: 'Branch name' })
    fireEvent.change(input, { target: { value: 'feature/x' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'New branch' }))

    await waitFor(() => expect(git.branchCreate).toHaveBeenCalledWith('/repo', 'feature/x', null))
  })

  it('renames a branch from its row', async () => {
    $scmBranches.set([branch({ name: 'feature/scm' })])
    const git = stubGit()
    renderRail()

    fireEvent.click(screen.getByRole('button', { name: 'Rename branch' }))
    const dialog = screen.getByRole('dialog')
    const input = within(dialog).getByRole('textbox', { name: 'Branch name' })
    expect((input as HTMLInputElement).value).toBe('feature/scm')
    fireEvent.change(input, { target: { value: 'feature/renamed' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Rename branch' }))

    await waitFor(() => expect(git.branchRename).toHaveBeenCalledWith('/repo', 'feature/scm', 'feature/renamed'))
  })

  it('deletes a branch from its row after confirming', async () => {
    $scmBranches.set([branch({ name: 'feature/scm' })])
    const git = stubGit()
    renderRail()

    fireEvent.click(screen.getByRole('button', { name: 'Delete branch' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Delete branch feature/scm? This cannot be undone.')).toBeTruthy()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete branch' }))

    await waitFor(() => expect(git.branchDelete).toHaveBeenCalledWith('/repo', 'feature/scm', false))
  })

  it('creates a tag from the section action', async () => {
    const git = stubGit()
    renderRail()

    fireEvent.click(screen.getByRole('button', { name: 'New tag' }))
    const dialog = screen.getByRole('dialog')
    const input = within(dialog).getByRole('textbox', { name: 'Tag name' })
    fireEvent.change(input, { target: { value: 'v2.0' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'New tag' }))

    await waitFor(() => expect(git.tagCreate).toHaveBeenCalledWith('/repo', 'v2.0', null))
  })

  it('clears the post-submit close timer when the rail unmounts', async () => {
    vi.useFakeTimers()

    try {
      const clearSpy = vi.spyOn(window, 'clearTimeout')
      const git = stubGit()
      const { unmount } = renderRail()

      fireEvent.click(screen.getByRole('button', { name: 'New tag' }))
      const dialog = screen.getByRole('dialog')
      fireEvent.change(within(dialog).getByRole('textbox', { name: 'Tag name' }), {
        target: { value: 'v2.1' }
      })
      fireEvent.click(within(dialog).getByRole('button', { name: 'New tag' }))

      // Resolve submit + schedule the 600ms close timer without firing it.
      await act(async () => {
        await Promise.resolve()
        await Promise.resolve()
      })
      expect(git.tagCreate).toHaveBeenCalledWith('/repo', 'v2.1', null)

      clearSpy.mockClear()
      unmount()
      // ScmNameDialog effect cleanup must clearTimeout so vitest teardown
      // cannot fire into a destroyed env (ReferenceError: window is not defined).
      expect(clearSpy).toHaveBeenCalled()

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_000)
      })
    } finally {
      vi.useRealTimers()
    }
  })

  it('deletes a tag from its row after confirming', async () => {
    $scmTags.set([tag({ name: 'v1.0.0' })])
    const git = stubGit()
    renderRail()

    fireEvent.click(screen.getByRole('button', { name: 'Delete tag' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Delete tag v1.0.0? This cannot be undone.')).toBeTruthy()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete tag' }))

    await waitFor(() => expect(git.tagDelete).toHaveBeenCalledWith('/repo', 'v1.0.0'))
  })

  it('stashes changes with an optional message', async () => {
    const git = stubGit()
    renderRail()

    fireEvent.click(screen.getByRole('button', { name: 'Stash changes' }))
    const dialog = screen.getByRole('dialog')
    const input = within(dialog).getByRole('textbox', { name: 'Message' })
    fireEvent.change(input, { target: { value: 'wip rail' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Stash changes' }))

    await waitFor(() => expect(git.stashCreate).toHaveBeenCalledWith('/repo', 'wip rail', false))
  })

  it('applies a stash entry from its row', async () => {
    $scmStashes.set([stash({ index: 0 })])
    const git = stubGit()
    renderRail()

    fireEvent.click(screen.getByRole('button', { name: 'Apply stash' }))

    await waitFor(() => expect(git.stashApply).toHaveBeenCalledWith('/repo', 0))
  })

  it('drops a stash entry from its row after confirming', async () => {
    $scmStashes.set([stash({ id: 'stash@{1}', index: 1 })])
    const git = stubGit()
    renderRail()

    fireEvent.click(screen.getByRole('button', { name: 'Drop stash' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Drop stash@{1}? This cannot be undone.')).toBeTruthy()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Drop stash' }))

    await waitFor(() => expect(git.stashDrop).toHaveBeenCalledWith('/repo', 1))
  })

  it('disables every action while a git op is busy', () => {
    stubGit()
    $scmBranches.set([branch({ name: 'feature/scm' })])
    $scmTags.set([tag({ name: 'v1.0.0' })])
    $scmStashes.set([stash({ index: 0 })])
    $scmBusy.set('branch')
    renderRail()

    const names = [
      'Fetch',
      'Pull',
      'New branch',
      'New tag',
      'Stash changes',
      'Rename branch',
      'Delete branch',
      'Delete tag',
      'Apply stash',
      'Drop stash'
    ]

    const buttons = names.map(name => screen.getByRole('button', { name }))

    expect(buttons.every(button => (button as HTMLButtonElement).disabled)).toBe(true)
  })
})
