// Git ops backing the coding rail + Codex-style review pane. Built on `simple-git`
// (a maintained wrapper around the system git binary — same git the rest of the
// app shells to, no native build) so we read structured status()/diffSummary()
// results instead of hand-parsing porcelain. Reads degrade to null/empty on a
// non-repo / remote backend; mutations reject so the renderer can toast.

import fs from 'node:fs/promises'
import path from 'node:path'

import { simpleGit } from 'simple-git'

import {
  executeGh,
  executeGit,
  gitExecutionPolicy,
  rethrowGitPolicyError,
  simpleGitTransport
} from './git-execution-policy'
import { resolveRequestedPathForIpc } from './hardening'

const COMMIT_CONTEXT_DIFF_MAX_CHARS = 120_000
const COMMIT_CONTEXT_UNTRACKED_MAX = 80
const HISTORY_LIMIT_DEFAULT = 50
const HISTORY_LIMIT_MAX = 100
const REVIEW_FILE_CAP = 2_000
const UNTRACKED_LINE_COUNT_CONCURRENCY = 16
const UNTRACKED_LINE_COUNT_MAX_BYTES = 1024 * 1024

// GUI-launched Electron apps on macOS inherit only a minimal PATH (no
// /opt/homebrew/bin or /usr/local/bin), so `gh` — and the `git` gh shells out
// to — aren't found. Augment PATH with the resolved gh dir + the common
// package-manager bins so gh runs the same way it does in a terminal.
function ghEnv(ghBin) {
  const extra = [ghBin ? path.dirname(ghBin) : '', '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin'].filter(
    dir => dir && dir !== '.'
  )

  return { ...process.env, PATH: [...extra, process.env.PATH].filter(Boolean).join(path.delimiter) }
}

// Run the `gh` CLI in a repo. Resolves { ok, stdout, stderr } so callers branch on
// availability/auth without a throw. gh missing/unauthed → ok:false.
async function runGh(args, cwd, ghBin): Promise<{ ok: boolean; stdout: string; stderr: string }> {
  const result = await executeGh(cwd, ghBin, args, ghEnv(ghBin))

  return { ok: result.exitCode === 0, stdout: result.stdout, stderr: result.stderr }
}

async function gitFor(cwd, gitBin, timeout = 30) {
  const policy = await gitExecutionPolicy(cwd, gitBin)
  const transport = simpleGitTransport(cwd, policy, timeout)

  // `gitBin` is resolved inside the Electron main process from known install
  // locations or PATH — never renderer/user input. simple-git's custom-binary
  // validation rejects paths containing spaces (the default Windows install is
  // `C:\Program Files\Git\cmd\git.exe`), which silently broke the Review pane.
  // For spaced paths, opt into simple-git's trusted-binary escape hatch instead
  // of falling back to PATH (often absent in GUI-launched apps, and PATH lookup
  // could resolve a repo-local git.exe).
  const git = simpleGit({
    baseDir: cwd,
    binary: transport.binary,
    errors: transport.errors,
    maxConcurrentProcesses: 4,
    trimmed: false,
    // These flags let simple-git carry the owner's disabling overrides. Values
    // and config paths come from the validated policy, not repository settings.
    unsafe: {
      allowUnsafeConfigPaths: true,
      allowUnsafeConfigEnvCount: true,
      allowUnsafeAskPass: true,
      allowUnsafeEditor: true,
      allowUnsafeFsMonitor: true,
      allowUnsafeHooksPath: true,
      allowUnsafePager: true,
      allowUnsafeSshCommand: true,
      allowUnsafeCredentialHelper: true,
      allowUnsafeDiffExternal: true,
      allowUnsafeFilter: true,
      allowUnsafeCustomBinary: true
    }
  })

  git.env(transport.environment)

  return git
}

async function protectedDiffArgs(git, cwd: string, gitBin: string, args: string[]): Promise<string[]> {
  const current = await gitExecutionPolicy(cwd, gitBin, ['diff', ...args])

  // The transport rediscovers policy for the final generated argv. Keep its
  // request nonce paired with the instance's public error handler.
  return current.argv.slice(1)
}

// simple-git reports renames as `old => new` (and `dir/{old => new}/f`); resolve
// to the NEW path so the row addresses the real file for diff/stage.
function resolveRenamePath(raw) {
  const path = String(raw || '').trim()

  if (!path.includes(' => ')) {
    return path
  }

  const brace = path.match(/^(.*)\{(.*) => (.*)\}(.*)$/)

  if (brace) {
    const [, prefix, , to, suffix] = brace

    return `${prefix}${to}${suffix}`.replace(/\/{2,}/g, '/')
  }

  return path.split(' => ').pop().trim()
}

// DiffResult.files → Map<path, {added, removed}> (binary files carry no line
// delta).
function countsByPath(summary) {
  const map = new Map()

  for (const file of summary.files) {
    map.set(resolveRenamePath(file.file), {
      added: file.binary ? 0 : file.insertions,
      removed: file.binary ? 0 : file.deletions
    })
  }

  return map
}

// Untracked files don't appear in diffSummary(); count insertions from disk so
// the review tree can show +N for new files (matches an all-add diff view).
// Insertions = line count: newline bytes, plus one for a final unterminated
// line. Binary (NUL byte) → 0, mirroring git numstat's "-".
async function untrackedInsertions(cwd, relPath) {
  try {
    const fullPath = path.join(cwd, relPath)
    const stat = await fs.stat(fullPath)

    if (!stat.isFile() || stat.size > UNTRACKED_LINE_COUNT_MAX_BYTES) {
      return 0
    }

    const buf = await fs.readFile(fullPath)

    if (buf.includes(0)) {
      return 0
    }

    let lines = 0

    for (const byte of buf) {
      if (byte === 10) {
        lines++
      }
    }

    return buf.length > 0 && buf[buf.length - 1] !== 10 ? lines + 1 : lines
  } catch (error) {
    rethrowGitPolicyError(error)

    return 0
  }
}

function capText(text, maxChars, label = 'truncated') {
  const value = String(text || '')

  if (value.length <= maxChars) {
    return value
  }

  return `${value.slice(0, maxChars)}\n# ${label}: ${value.length - maxChars} chars omitted\n`
}

async function fillUntrackedCounts(cwd, files) {
  const pending = files.filter(file => file.status === '?' && file.added === 0 && file.removed === 0)

  for (let i = 0; i < pending.length; i += UNTRACKED_LINE_COUNT_CONCURRENCY) {
    await Promise.all(
      pending.slice(i, i + UNTRACKED_LINE_COUNT_CONCURRENCY).map(async file => {
        file.added = await untrackedInsertions(cwd, file.path)
      })
    )
  }
}

// Resolve the base ref for "all branch changes": merge-base with the remote
// default branch (origin/HEAD), falling back to common trunk names.
async function branchBase(git) {
  const candidates = []

  try {
    const head = (await git.revparse(['--abbrev-ref', 'origin/HEAD'])).trim()

    if (head) {
      candidates.push(head)
    }
  } catch (error) {
    rethrowGitPolicyError(error)
    // No origin/HEAD configured.
  }

  candidates.push('origin/main', 'origin/master', 'main', 'master')

  for (const ref of candidates) {
    try {
      const base = (await git.raw(['merge-base', 'HEAD', ref])).trim()

      if (base) {
        return base
      }
    } catch (error) {
      rethrowGitPolicyError(error)
      // Ref doesn't exist; try the next candidate.
    }
  }

  return null
}

// Resolve the repo's default branch NAME ("main" / "master" / …), preferring
// the remote's HEAD, then common local trunk names. Null when none is found
// (e.g. a fresh repo with only a feature branch). Used to offer "branch off the
// trunk" regardless of which branch you're currently on.
async function defaultBranchName(git) {
  try {
    const head = (await git.revparse(['--abbrev-ref', 'origin/HEAD'])).trim()

    // "origin/main" → "main"; skip the bare "origin/HEAD" placeholder.
    if (head && head !== 'origin/HEAD') {
      return head.replace(/^origin\//, '')
    }
  } catch (error) {
    rethrowGitPolicyError(error)
    // No origin/HEAD configured.
  }

  // Prefer a local trunk, then a remote-only one (returns the clean name either
  // way) so "branch off main" works even before main is checked out locally.
  for (const ref of [
    'refs/heads/main',
    'refs/heads/master',
    'refs/remotes/origin/main',
    'refs/remotes/origin/master'
  ]) {
    try {
      await git.raw(['rev-parse', '--verify', '--quiet', ref])

      return ref.replace(/^refs\/(?:heads|remotes\/origin)\//, '')
    } catch (error) {
      rethrowGitPolicyError(error)
      // Ref doesn't exist; try the next candidate.
    }
  }

  return null
}

// A status file's single-letter classification, preferring the staged (index)
// code over the worktree code; untracked wins (simple-git marks both '?').
function statusLetter(file) {
  if (file.index === '?' || file.working_dir === '?') {
    return '?'
  }

  const code = file.index && file.index !== ' ' ? file.index : file.working_dir

  return (code || 'M').toUpperCase()
}

const isStaged = file => Boolean(file.index && file.index !== ' ' && file.index !== '?')

async function reviewList(repoPath, scope, baseRef, gitBin) {
  let cwd

  try {
    cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Review list' })
  } catch (error) {
    rethrowGitPolicyError(error)

    return { files: [], base: null }
  }

  const git = await gitFor(cwd, gitBin)

  try {
    if (scope === 'branch' || scope === 'lastTurn') {
      const base = scope === 'branch' ? await branchBase(git) : baseRef

      if (!base) {
        return { files: [], base: null }
      }

      const range = scope === 'branch' ? `${base}...HEAD` : base
      const summary = await git.diffSummary(await protectedDiffArgs(git, cwd, gitBin, [range]))

      const files = summary.files.slice(0, REVIEW_FILE_CAP).map(file => ({
        path: resolveRenamePath(file.file),
        added: 'insertions' in file ? file.insertions : 0,
        removed: 'deletions' in file ? file.deletions : 0,
        status: 'M',
        staged: false
      }))

      // "Last turn" also surfaces files created since the baseline (untracked).
      if (scope === 'lastTurn' && files.length < REVIEW_FILE_CAP) {
        // Keep untracked directories compact. A recursive status can produce
        // hundreds of thousands of rows for browser profiles, generated
        // artifacts, or dependency trees before the response reaches the
        // renderer.
        const status = await git.status(['--untracked-files=normal'])
        const knownPaths = new Set(files.map(file => file.path))

        for (const path of status.not_added) {
          if (files.length >= REVIEW_FILE_CAP) {
            break
          }

          if (!knownPaths.has(path)) {
            files.push({ path, added: 0, removed: 0, status: '?', staged: false })
            knownPaths.add(path)
          }
        }
      }

      files.sort((a, b) => a.path.localeCompare(b.path))
      await fillUntrackedCounts(cwd, files)

      return { files, base }
    }

    // Default: uncommitted (staged + unstaged + untracked), one row per path.
    const results = await Promise.allSettled([
      // `normal` reports an untracked directory as one row instead of walking
      // every descendant. The result is also capped before per-file stat/read
      // work and before crossing the Electron IPC boundary.
      (async () => git.status(['--untracked-files=normal']))(),
      (async () => git.diffSummary(await protectedDiffArgs(git, cwd, gitBin, ['--cached'])))(),
      (async () => git.diffSummary(await protectedDiffArgs(git, cwd, gitBin, [])))()
    ])

    // Drain every owner request before reporting failure. A policy refusal must
    // not be hidden by an earlier ordinary Git error and its empty-read fallback.
    for (const result of results) {
      if (result.status === 'rejected') {
        rethrowGitPolicyError(result.reason)
      }
    }

    const [status, staged, unstaged] = results.map(result => {
      if (result.status === 'rejected') {
        throw result.reason
      }

      return result.value
    })

    const stagedCounts = countsByPath(staged)
    const unstagedCounts = countsByPath(unstaged)

    const files = status.files.slice(0, REVIEW_FILE_CAP).map(file => {
      const filePath = resolveRenamePath(file.path)
      const sc = stagedCounts.get(filePath) || { added: 0, removed: 0 }
      const uc = unstagedCounts.get(filePath) || { added: 0, removed: 0 }

      return {
        path: filePath,
        added: sc.added + uc.added,
        removed: sc.removed + uc.removed,
        status: statusLetter(file),
        staged: isStaged(file)
      }
    })

    files.sort((a, b) => a.path.localeCompare(b.path))
    await fillUntrackedCounts(cwd, files)

    return { files, base: null }
  } catch (error) {
    rethrowGitPolicyError(error)

    return { files: [], base: null }
  }
}

async function reviewDiff(repoPath, filePath, scope, baseRef, staged, gitBin) {
  let cwd

  try {
    cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Review diff' })
  } catch (error) {
    rethrowGitPolicyError(error)

    return ''
  }

  const git = await gitFor(cwd, gitBin)

  const safe = async args =>
    git.diff(await protectedDiffArgs(git, cwd, gitBin, args)).catch(error => {
      rethrowGitPolicyError(error)

      return ''
    })

  if (scope === 'branch') {
    const base = await branchBase(git)

    return base ? safe([`${base}...HEAD`, '--', filePath]) : ''
  }

  if (scope === 'lastTurn') {
    return baseRef ? safe([baseRef, '--', filePath]) : ''
  }

  if (staged) {
    return safe(['--cached', '--', filePath])
  }

  const worktree = await safe(['--', filePath])

  if (worktree.trim()) {
    return worktree
  }

  // Untracked file: no worktree diff exists, so synthesize an all-add diff via
  // --no-index (exits non-zero by design when files differ, so go around
  // simple-git's reject-on-nonzero with the shared execution owner).
  const result = await executeGit(cwd, gitBin, ['diff', '--no-index', '--', '/dev/null', filePath], 32 * 1024 * 1024)

  return result.exitCode === 0 || result.exitCode === 1 ? result.stdout : ''
}

// The history surface is deliberately read-only. Keep the renderer from
// supplying an arbitrary revision expression: the UI obtains ids from
// reviewHistory(), and accepting only hexadecimal object ids also prevents a
// leading dash from ever being interpreted as a git option.
function isCommitId(value) {
  return /^[0-9a-f]{7,64}$/i.test(String(value || ''))
}

function historyLimit(value) {
  const parsed = Number(value)

  if (!Number.isFinite(parsed)) {
    return HISTORY_LIMIT_DEFAULT
  }

  return Math.max(1, Math.min(HISTORY_LIMIT_MAX, Math.trunc(parsed)))
}

// Use ASCII control separators that cannot occur in normal one-line commit
// subjects. This avoids locale-sensitive column parsing while keeping author
// names and messages intact.
function parseHistory(raw) {
  return String(raw || '')
    .split('\x1e')
    .filter(Boolean)
    .flatMap(rawRecord => {
      // Git appends a physical line ending after each format record. Strip only
      // that separator so the next SHA remains valid without changing commit
      // subject whitespace.
      const record = rawRecord.replace(/^[\r\n]+/, '')
      const [sha, shortSha, parents, author, authoredAt, subject] = record.split('\x1f')

      if (!isCommitId(sha) || !shortSha || !authoredAt) {
        return []
      }

      return [
        {
          author: author || '',
          authoredAt,
          parents: (parents || '').split(' ').filter(isCommitId),
          sha,
          shortSha,
          subject: subject || ''
        }
      ]
    })
}

async function reviewHistory(repoPath, limit, gitBin) {
  let cwd

  try {
    cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Review history' })
  } catch (error) {
    rethrowGitPolicyError(error)

    return []
  }

  try {
    const raw = await (
      await gitFor(cwd, gitBin)
    ).raw([
      'log',
      `--max-count=${historyLimit(limit)}`,
      '--date=iso-strict',
      '--format=%H%x1f%h%x1f%P%x1f%an%x1f%aI%x1f%s%x1e'
    ])

    return parseHistory(raw)
  } catch (error) {
    rethrowGitPolicyError(error)

    return []
  }
}

async function reviewHistoryDiff(repoPath, sha, gitBin) {
  if (!isCommitId(sha)) {
    return ''
  }

  let cwd

  try {
    cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Review history diff' })
  } catch (error) {
    rethrowGitPolicyError(error)

    return ''
  }

  const args = ['show', '--format=', '--find-renames', '--find-copies', sha, '--']
  const policy = await gitExecutionPolicy(cwd, gitBin, args)

  return (await gitFor(cwd, gitBin)).raw(policy.argv).catch(error => {
    rethrowGitPolicyError(error)

    return ''
  })
}

// Working-tree-vs-HEAD diff for ONE file — the "what changed since the last
// commit" view used by the file preview. Unlike reviewDiff this never synthesizes
// a full-add for a clean tracked file (so a pristine file shows no diff); it only
// all-adds a genuinely untracked file.
async function fileDiffVsHead(repoPath, filePath, gitBin) {
  let cwd

  try {
    cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'File diff' })
  } catch (error) {
    rethrowGitPolicyError(error)

    return ''
  }

  const git = await gitFor(cwd, gitBin)

  const head = await git.diff(await protectedDiffArgs(git, cwd, gitBin, ['HEAD', '--', filePath])).catch(error => {
    rethrowGitPolicyError(error)

    return ''
  })

  if (head.trim()) {
    return head
  }

  // No tracked changes vs HEAD. Only synthesize an all-add diff for a file git
  // doesn't know yet; a clean tracked file must return empty.
  const status = await git.raw(['status', '--porcelain', '--', filePath]).catch(error => {
    rethrowGitPolicyError(error)

    return ''
  })

  if (!status.trim().startsWith('??')) {
    return ''
  }

  const result = await executeGit(cwd, gitBin, ['diff', '--no-index', '--', '/dev/null', filePath], 32 * 1024 * 1024)

  return result.exitCode === 0 || result.exitCode === 1 ? result.stdout : ''
}

async function reviewStage(repoPath, filePath, gitBin) {
  const cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Review stage' })

  await (await gitFor(cwd, gitBin)).raw(filePath ? ['add', '--', filePath] : ['add', '-A'])

  return { ok: true }
}

async function reviewUnstage(repoPath, filePath, gitBin) {
  const cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Review unstage' })

  await (await gitFor(cwd, gitBin)).raw(filePath ? ['reset', '-q', 'HEAD', '--', filePath] : ['reset', '-q', 'HEAD'])

  return { ok: true }
}

// Discard changes back to the committed state. Destructive — the renderer
// confirms first. Restores tracked files and removes untracked ones.
async function reviewRevert(repoPath, filePath, gitBin) {
  const cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Review revert' })
  const git = await gitFor(cwd, gitBin)

  if (filePath) {
    await git.raw(['checkout', 'HEAD', '--', filePath]).catch(error => {
      rethrowGitPolicyError(error)

      return undefined
    })
    await git.raw(['clean', '-fd', '--', filePath]).catch(error => {
      rethrowGitPolicyError(error)

      return undefined
    })
  } else {
    await git.raw(['checkout', 'HEAD', '--', '.']).catch(error => {
      rethrowGitPolicyError(error)

      return undefined
    })
    await git.raw(['clean', '-fd']).catch(error => {
      rethrowGitPolicyError(error)

      return undefined
    })
  }

  return { ok: true }
}

// Resolve a ref to a commit sha (captures the turn baseline for "Last turn").
async function reviewRevParse(repoPath, ref, gitBin) {
  let cwd

  try {
    cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Review rev-parse' })
  } catch (error) {
    rethrowGitPolicyError(error)

    return null
  }

  try {
    return (await (await gitFor(cwd, gitBin)).revparse([ref || 'HEAD'])).trim() || null
  } catch (error) {
    rethrowGitPolicyError(error)

    return null
  }
}

// Commit the working tree. Mirrors VS Code: if nothing is staged, stage
// everything first ("commit all"), then commit. Optionally push afterward,
// setting upstream on the first push.
async function reviewCommit(repoPath, message, push, gitBin) {
  const cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Review commit' })
  const git = await gitFor(cwd, gitBin)
  const status = await git.status()

  if (status.staged.length === 0) {
    await git.raw(['add', '-A'])
  }

  await git.commit(message)

  if (push) {
    const fresh = await git.status()

    if (fresh.tracking) {
      await git.push()
    } else if (fresh.current) {
      await git.raw(['push', '-u', 'origin', fresh.current])
    }
  }

  return { ok: true }
}

// Gather the context the model needs to draft a commit message: the diff of
// what *will* be committed (staged when anything is staged, else everything
// vs HEAD — mirroring reviewCommit's "stage all when nothing staged" rule),
// the names of untracked files (which carry no diff), and recent commit
// subjects for style. Diff is capped so the payload stays bounded. Reads only.
async function reviewCommitContext(repoPath, gitBin) {
  let cwd

  try {
    cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Review commit context' })
  } catch (error) {
    rethrowGitPolicyError(error)

    return { diff: '', recent: '' }
  }

  const git = await gitFor(cwd, gitBin)

  const safe = async args =>
    git.diff(await protectedDiffArgs(git, cwd, gitBin, args)).catch(error => {
      rethrowGitPolicyError(error)

      return ''
    })

  let status

  try {
    status = await git.status()
  } catch (error) {
    rethrowGitPolicyError(error)

    return { diff: '', recent: '' }
  }

  // What will land: staged changes if any, otherwise all tracked changes vs HEAD.
  let diff = capText(
    status.staged.length > 0 ? await safe(['--cached']) : await safe(['HEAD']),
    COMMIT_CONTEXT_DIFF_MAX_CHARS,
    'diff truncated for commit-message generation'
  )

  // Untracked files have no diff — list them so new files aren't invisible.
  const untracked = status.not_added || []

  if (untracked.length > 0) {
    const visible = untracked.slice(0, COMMIT_CONTEXT_UNTRACKED_MAX)
    const omitted = untracked.length - visible.length

    const note =
      `\n# New (untracked) files:\n${visible.map(p => `#   ${p}`).join('\n')}\n` +
      (omitted > 0 ? `#   ... ${omitted} more omitted\n` : '')

    diff = diff ? `${diff}${note}` : note
  }

  const recent = await git.raw(['log', '-n', '10', '--pretty=format:%s']).catch(error => {
    rethrowGitPolicyError(error)

    return ''
  })

  return { diff: diff || '', recent: String(recent || '').trim() }
}

async function reviewPush(repoPath, gitBin) {
  const cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Review push' })
  const git = await gitFor(cwd, gitBin)
  const status = await git.status()

  if (status.tracking) {
    await git.push()
  } else if (status.current) {
    await git.raw(['push', '-u', 'origin', status.current])
  }

  return { ok: true }
}

// gh availability + auth + whether this branch already has a PR. Reads only;
// drives the PR button's enabled/label state. `ghReady` is false when gh is
// missing OR not authenticated — either way the PR action can't run.
async function reviewShipInfo(repoPath, ghBin) {
  let cwd

  try {
    cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Review ship info' })
  } catch (error) {
    rethrowGitPolicyError(error)

    return { ghReady: false, pr: null }
  }

  const auth = await runGh(['auth', 'status'], cwd, ghBin)

  if (!auth.ok) {
    return { ghReady: false, pr: null }
  }

  const view = await runGh(['pr', 'view', '--json', 'url,state,number'], cwd, ghBin)

  if (!view.ok) {
    // gh exits non-zero when no PR exists for the branch — that's not an error.
    return { ghReady: true, pr: null }
  }

  try {
    const pr = JSON.parse(view.stdout)

    return { ghReady: true, pr: pr && pr.url ? { url: pr.url, state: pr.state, number: pr.number } : null }
  } catch (error) {
    rethrowGitPolicyError(error)

    return { ghReady: true, pr: null }
  }
}

// GraphQL asks per branch, so the answer can't be crowded out the way a
// `gh pr list` page can. Aliases let one request carry many branches; 50 keeps
// the document well inside GitHub's node budget.
const PR_QUERY_BRANCH_CHUNK = 50
const PR_QUERY_BRANCH_CAP = 300

const PR_NODE_FIELDS = 'number state isDraft isCrossRepository title url headRefName'

function prQueryFor(owner, name, branches, numbers) {
  const fields = [
    ...branches.map(
      (branch, i) =>
        `b${i}: pullRequests(headRefName: ${JSON.stringify(branch)}, first: 5, ` +
        `orderBy: {field: CREATED_AT, direction: DESC}) ` +
        `{ nodes { ${PR_NODE_FIELDS} } }`
    ),
    // A PR recovered from a transcript is known by number, and asking for it
    // directly also tells us its branch — so it lands in the same by-branch map
    // as everything else.
    ...numbers.map((number, i) => `n${i}: pullRequest(number: ${number}) { ${PR_NODE_FIELDS} }`)
  ].join('\n')

  return `query { repository(owner: ${JSON.stringify(owner)}, name: ${JSON.stringify(name)}) {\n${fields}\n} }`
}

const prPayload = pr => ({
  branch: String(pr.headRefName),
  draft: Boolean(pr.isDraft),
  number: Number(pr.number) || 0,
  state: String(pr.state || '').toLowerCase(),
  title: String(pr.title || ''),
  url: String(pr.url || '')
})

// A GitHub review-comment / issue-comment URL, as pasted from the browser.
// Captures owner, repo, PR number, and the comment kind + id. Review threads
// deep-link as `#discussion_r<id>`; conversation-tab comments as
// `#issuecomment-<id>`.
const PR_COMMENT_URL_RE =
  /^https:\/\/github\.com\/([^/\s]+)\/([^/\s]+)\/pull\/(\d+)(?:\/[^#\s]*)?#(discussion_r|issuecomment-)(\d+)$/

function parsePrCommentUrl(url) {
  const match = PR_COMMENT_URL_RE.exec(String(url || '').trim())

  if (!match) {
    return null
  }

  const [, owner, repo, prNumber, kind, id] = match

  return { id, kind: kind === 'discussion_r' ? 'review' : 'issue', owner, prNumber: Number(prNumber), repo }
}

// Resolve a pasted PR comment URL into the structured context the composer
// attaches: author, body, and — for review comments — the file, line range,
// and the diff hunk the comment anchors to. Reads only; any failure (gh
// missing, unauthenticated, private repo, deleted comment) yields null and the
// paste falls back to being a plain URL.
async function reviewFetchPrComment(repoPath, ghBin, url) {
  const parsed = parsePrCommentUrl(url)

  if (!parsed) {
    return null
  }

  let cwd

  try {
    cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Review comment fetch' })
  } catch (error) {
    rethrowGitPolicyError(error)

    return null
  }

  const endpoint =
    parsed.kind === 'review'
      ? `repos/${parsed.owner}/${parsed.repo}/pulls/comments/${parsed.id}`
      : `repos/${parsed.owner}/${parsed.repo}/issues/comments/${parsed.id}`

  const res = await runGh(['api', endpoint], cwd, ghBin)

  if (!res.ok) {
    return null
  }

  try {
    const data = JSON.parse(res.stdout)

    return {
      author: String(data?.user?.login || ''),
      body: String(data?.body || ''),
      diffHunk: parsed.kind === 'review' ? String(data?.diff_hunk || '') : '',
      kind: parsed.kind,
      // `line` is the comment's anchor in the current diff; null once the code
      // moved on (outdated comment) — `original_line` still says where it was.
      line: data?.line ?? data?.original_line ?? null,
      path: parsed.kind === 'review' ? String(data?.path || '') : '',
      prNumber: parsed.prNumber,
      startLine: data?.start_line ?? data?.original_start_line ?? null,
      url: String(data?.html_url || url)
    }
  } catch (error) {
    rethrowGitPolicyError(error)

    return null
  }
}

// The PR for each of the given branches, keyed by branch. Asks GitHub about the
// branches we actually have sessions on rather than listing the repo's newest
// PRs and hoping ours are in the page — on a busy repo they are not. One
// GraphQL request per 50 branches; reads only.
async function reviewPrList(repoPath, ghBin, branches, numbers) {
  let cwd

  try {
    cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Review PR list' })
  } catch (error) {
    rethrowGitPolicyError(error)

    return { ghReady: false, prs: [] }
  }

  const wanted = [...new Set((branches || []).filter(Boolean).map(String))].slice(0, PR_QUERY_BRANCH_CAP)
  const byNumber = [...new Set((numbers || []).map(Number).filter(Boolean))].slice(0, PR_QUERY_BRANCH_CAP)

  if (wanted.length === 0 && byNumber.length === 0) {
    return { ghReady: false, prs: [] }
  }

  const repo = await runGh(['repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner'], cwd, ghBin)
  const [owner, name] = repo.stdout.trim().split('/')

  if (!repo.ok || !owner || !name) {
    // gh missing, unauthenticated, or no GitHub remote — all "nothing to badge".
    return { ghReady: false, prs: [] }
  }

  const prs = []
  const chunks = []

  for (let start = 0; start < wanted.length; start += PR_QUERY_BRANCH_CHUNK) {
    chunks.push([wanted.slice(start, start + PR_QUERY_BRANCH_CHUNK), []])
  }

  for (let start = 0; start < byNumber.length; start += PR_QUERY_BRANCH_CHUNK) {
    chunks.push([[], byNumber.slice(start, start + PR_QUERY_BRANCH_CHUNK)])
  }

  for (const [branchChunk, numberChunk] of chunks) {
    const query = prQueryFor(owner, name, branchChunk, numberChunk)
    const res = await runGh(['api', 'graphql', '-f', `query=${query}`], cwd, ghBin)

    if (!res.ok) {
      continue
    }

    try {
      const repository = JSON.parse(res.stdout)?.data?.repository ?? {}

      for (const key of Object.keys(repository)) {
        // Asked for by number, so it's ours by construction — a fork PR can't
        // be recovered from our own transcript. Asked for by branch, it has to
        // prove it: fork PRs share our branch namespace, and a contributor's
        // `main` is how a session on trunk ends up badged with a stranger's PR.
        const pr = key.startsWith('n')
          ? repository[key]
          : (repository[key]?.nodes ?? []).find(node => node && !node.isCrossRepository)

        if (pr?.headRefName) {
          prs.push(prPayload(pr))
        }
      }
    } catch (error) {
      rethrowGitPolicyError(error)
      // A malformed chunk drops its branches; the rest still resolve.
    }
  }

  return { ghReady: true, prs }
}

// Create a PR for the current branch (pushing first so gh has a remote ref),
// letting gh fill title/body from the commits. Returns the new PR url.
async function reviewCreatePr(repoPath, gitBin, ghBin) {
  const cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Review create PR' })

  await reviewPush(repoPath, gitBin).catch(error => {
    rethrowGitPolicyError(error)

    return undefined
  })

  const created = await runGh(['pr', 'create', '--fill'], cwd, ghBin)

  if (!created.ok) {
    throw new Error(
      created.stderr.trim() || created.stdout.trim() || 'gh pr create failed (is gh installed and authenticated?)'
    )
  }

  const url = created.stdout.trim().split('\n').filter(Boolean).pop() || ''

  return { url }
}

// Compact working-tree status for the composer coding rail: branch, ahead/behind,
// per-state change counts, +/- vs HEAD, and a capped changed-file list.
async function repoStatus(repoPath, gitBin) {
  let cwd

  try {
    cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Repo status' })
  } catch (error) {
    rethrowGitPolicyError(error)

    return null
  }

  // Session cwds can point at a deleted worktree for a moment (or forever in a
  // stale row). simple-git throws at construction time on a missing baseDir, so
  // fail soft and hide the coding rail instead of spamming IPC handler errors.
  try {
    const stat = await fs.stat(cwd)

    if (!stat.isDirectory()) {
      return null
    }
  } catch (error) {
    rethrowGitPolicyError(error)

    return null
  }

  let git

  try {
    git = await gitFor(cwd, gitBin)
  } catch (error) {
    rethrowGitPolicyError(error)

    return null
  }

  let status

  try {
    // The coding rail needs compact change truth, not every generated file.
    // `simple-git` defaults bare `-u` to recursive `all`, which can make a
    // generated workspace consume gigabytes before the 200-row UI cap is
    // applied. `normal` reports each untracked directory as one entry.
    status = await git.status(['--untracked-files=normal'])
  } catch (error) {
    rethrowGitPolicyError(error)

    // Not a repo / git unavailable / remote backend.
    return null
  }

  const detached = typeof status.detached === 'boolean' ? status.detached : !status.current

  const files = status.files.map(file => ({
    path: file.path,
    staged: isStaged(file),
    unstaged: Boolean(file.working_dir && file.working_dir !== ' ' && file.working_dir !== '?'),
    untracked: file.index === '?' || file.working_dir === '?',
    conflicted: file.index === 'U' || file.working_dir === 'U'
  }))

  const result = {
    branch: detached ? null : status.current || null,
    defaultBranch: await defaultBranchName(git),
    detached,
    ahead: status.ahead || 0,
    behind: status.behind || 0,
    staged: files.filter(f => f.staged).length,
    unstaged: files.filter(f => f.unstaged).length,
    untracked: status.not_added.length,
    conflicted: status.conflicted.length,
    changed: files.length,
    added: 0,
    removed: 0,
    files: files.slice(0, 200)
  }

  // +/- vs HEAD (staged + unstaged tracked changes). No HEAD yet → leave 0.
  try {
    const summary = await git.diffSummary(await protectedDiffArgs(git, cwd, gitBin, ['HEAD']))
    result.added = summary.insertions
    result.removed = summary.deletions
  } catch (error) {
    rethrowGitPolicyError(error)
    // No commits yet.
  }

  // `git diff HEAD` ignores untracked files, so a turn that only creates new
  // files (the common case — a fresh module) showed +0 in the rail while the
  // review pane counted them. Fold top-level untracked file insertions into
  // `added`; directories reported by the compact `normal` scan intentionally
  // remain at zero rather than recursively walking their contents.
  try {
    const untracked = status.not_added.slice(0, 500)

    for (let i = 0; i < untracked.length; i += UNTRACKED_LINE_COUNT_CONCURRENCY) {
      const batch = await Promise.all(
        untracked.slice(i, i + UNTRACKED_LINE_COUNT_CONCURRENCY).map(path => untrackedInsertions(cwd, path))
      )

      result.added += batch.reduce((sum, n) => sum + n, 0)
    }
  } catch (error) {
    rethrowGitPolicyError(error)
    // Best-effort: a probe failure just leaves untracked lines uncounted.
  }

  return result
}

export {
  branchBase,
  fileDiffVsHead,
  gitFor,
  repoStatus,
  resolveRenamePath,
  REVIEW_FILE_CAP,
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
}
