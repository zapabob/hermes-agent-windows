import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import { createRequire } from 'node:module'
import os from 'node:os'
import path from 'node:path'

import { test } from 'vitest'

import { GitPolicyError, rethrowGitPolicyError } from './git-execution-policy'
import { gitBinary } from './git-test-runtime'
import type * as WorktreeOpsModule from './git-worktree-ops'
import {
  addWorktree,
  ensureGitRepo,
  listBaseBranches,
  listBranches,
  parseWorktrees,
  sanitizeBranch,
  switchBranch
} from './git-worktree-ops'

// Current-source pure contracts: only the explicitly supplied owner fake can
// receive a Git request. No policy process, real repository or Git is used.
let pureWorktreeSource: string
function mockWorktree(executeGitChecked: (cwd: string, binary: string, args: string[]) => Promise<string>) {
  const root = process.env.S06_OWNER_ROOT || (fs.existsSync('electron/git-worktree-ops.ts')
    ? path.resolve('../..') : process.cwd())
  if (!pureWorktreeSource) {
    const requireTest = createRequire(path.join(process.env.S06_DESKTOP_DEPS || path.join(root, 'apps/desktop'), 'package.json'))
    const esbuild = requireTest('esbuild')
    try {
      pureWorktreeSource = esbuild.transformSync(fs.readFileSync(path.join(root, 'apps/desktop/electron/git-worktree-ops.ts'), 'utf8'),
        {loader: 'ts', format: 'cjs', target: 'node24'}).code
    } finally { esbuild.stop() }
  }
  const cwd = path.join(root, 'tmp', 'pure-selected-repo')
  const dependencies = {
    'node:fs': {}, 'node:path': path,
    './hardening': {resolveRequestedPathForIpc: () => cwd},
    './git-execution-policy': {executeGitChecked, rethrowGitPolicyError}
  }
  const module = {exports: {}} as {exports: typeof WorktreeOpsModule}
  new Function('require', 'module', 'exports', pureWorktreeSource)(name => {
    if (!(name in dependencies)) {throw new Error(`Unexpected pure dependency: ${name}`)}
    return dependencies[name]
  }, module, module.exports)
  return {ops: module.exports, cwd}
}

function worktreeGate() {
  let resolve!: (value: string) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<string>((yes, no) => { resolve = yes; reject = no })
  return {promise, resolve, reject}
}

test.each(['refs/heads', 'refs/remotes'])('pure S06 worktree: failure in %s waits for the other owner request', async failed => {
  const sibling = worktreeGate()
  const failure = failed === 'refs/heads' ? new Error('ordinary local failure') : new GitPolicyError('remote refused')
  let calls = 0
  const {ops} = mockWorktree(async (_cwd, _binary, args) => {
    calls++
    return args.at(-1) === failed ? Promise.reject(failure) : sibling.promise
  })
  let settled = false
  const result = ops.listBranches('renderer-repo', 'selected-git')
    .then(value => ({value}), error => ({error})).finally(() => { settled = true })
  try {
    await new Promise<void>(resolve => setImmediate(resolve))
    assert.equal(calls, 2)
    assert.equal(settled, false, 'branch list returned while the other request remained owned')
  } finally { sibling.resolve('') }
  if (failure instanceof GitPolicyError) {assert.equal((await result as {error: unknown}).error, failure)}
  else {assert.deepEqual((await result as {value: unknown}).value, [])}
})

test('pure S06 worktree: later policy refusal is not hidden by an earlier ordinary failure', async () => {
  const remote = worktreeGate()
  const refusal = new GitPolicyError('remote authority refused')
  const {ops} = mockWorktree(async (_cwd, _binary, args) => {
    return args.at(-1) === 'refs/heads' ? Promise.reject(new Error('local failed')) : remote.promise
  })
  const result = ops.listBranches('renderer-repo', 'selected-git').then(value => ({value}), error => ({error}))
  await new Promise<void>(resolve => setImmediate(resolve))
  remote.reject(refusal)
  assert.equal((await result as {error: unknown}).error, refusal)
})

test('pure S06 worktree: success retains SHAs, selected repo and remote deduplication', async () => {
  const requests: [string, string, string[]][] = []
  const sep = String.fromCharCode(31)
  const mainSha = 'a'.repeat(40)
  const remoteSha = 'b'.repeat(40)
  const {ops, cwd} = mockWorktree(async (repo, binary, args) => {
    requests.push([repo, binary, args])
    if (args[0] === 'for-each-ref') {return args.at(-1) === 'refs/heads'
      ? `main${sep}${mainSha}\n` : `origin/HEAD${sep}${mainSha}\norigin/main${sep}${mainSha}\norigin/feature${sep}${remoteSha}\n`}
    if (args[0] === 'worktree') {return `worktree ${repo}\nbranch refs/heads/main\n`}
    if (args[0] === 'symbolic-ref') {return 'origin/main\n'}
    throw new Error(`Unexpected fake Git argv: ${args.join(' ')}`)
  })
  assert.deepEqual(await ops.listBranches('renderer-repo', 'selected-git'), [
    {name: 'main', checkedOut: true, isDefault: true, isRemote: false, worktreePath: cwd, sha: mainSha},
    {name: 'origin/feature', checkedOut: false, isDefault: false, isRemote: true, worktreePath: null, sha: remoteSha}
  ])
  assert.equal(requests.length, 4)
  for (const request of requests) {assert.deepEqual(request.slice(0, 2), [cwd, 'selected-git'])}
  assert.deepEqual(requests.slice(0, 2).map(request => request[2]), [
    ['for-each-ref', `--format=%(refname:short)${sep}%(objectname)`, '--sort=-committerdate', 'refs/heads'],
    ['for-each-ref', `--format=%(refname:short)${sep}%(objectname)`, '--sort=-committerdate', 'refs/remotes']
  ])
})

function assertSameDirectory(actual: string, expected: string) {
  const actualStat = fs.statSync(actual, { bigint: true })
  const expectedStat = fs.statSync(expected, { bigint: true })

  assert.equal(actualStat.dev, expectedStat.dev)
  assert.equal(actualStat.ino, expectedStat.ino)
}

test('sanitizeBranch: spaces → hyphens, forbidden chars dropped, edges trimmed', () => {
  assert.equal(sanitizeBranch('beach vibes'), 'beach-vibes')
  assert.equal(sanitizeBranch('feat/cool thing'), 'feat/cool-thing')
  assert.equal(sanitizeBranch('  wip~^:? '), 'wip')
  assert.equal(sanitizeBranch('///'), '')
})

test('parseWorktrees: main checkout + linked worktree', () => {
  const out = [
    'worktree /repo',
    'HEAD abc123',
    'branch refs/heads/main',
    '',
    'worktree /repo/.worktrees/feat',
    'HEAD def456',
    'branch refs/heads/hermes/feat',
    ''
  ].join('\n')

  const trees = parseWorktrees(out)

  assert.equal(trees.length, 2)
  assert.equal(trees[0].path, '/repo')
  assert.equal(trees[0].branch, 'main')
  assert.equal(trees[1].path, '/repo/.worktrees/feat')
  assert.equal(trees[1].branch, 'hermes/feat')
})

test('parseWorktrees: detached + locked flags', () => {
  const out = ['worktree /repo/wt', 'HEAD abc', 'detached', 'locked reason', ''].join('\n')
  const trees = parseWorktrees(out)

  assert.equal(trees.length, 1)
  assert.equal(trees[0].detached, true)
  assert.equal(trees[0].locked, true)
  assert.equal(trees[0].branch, null)
})

test('parseWorktrees: empty input', () => {
  assert.deepEqual(parseWorktrees(''), [])
})

test('ensureGitRepo: inits a plain dir with a root commit so worktrees branch', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-wt-'))
  const git = (...args) => execFileSync(gitBinary, args, { cwd: dir }).toString().trim()

  try {
    await ensureGitRepo(gitBinary, dir)
    assert.match(git('rev-parse', '--verify', 'HEAD'), /^[0-9a-f]{7,}$/)

    // The whole point: a worktree can now branch off the seeded root commit.
    execFileSync(gitBinary, ['worktree', 'add', '-b', 'wt', path.join(dir, '.worktrees', 'wt')], { cwd: dir })
    assert.ok(fs.existsSync(path.join(dir, '.worktrees', 'wt')))

    // Idempotent: an already-committed repo gets no extra commit.
    await ensureGitRepo(gitBinary, dir)
    assert.equal(git('rev-list', '--count', 'HEAD'), '1')
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('switchBranch: switches a normal checkout branch', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-switch-'))
  const git = (...args) => execFileSync(gitBinary, args, { cwd: dir }).toString().trim()

  try {
    await ensureGitRepo(gitBinary, dir)
    execFileSync(gitBinary, ['branch', 'feature'], { cwd: dir })

    await switchBranch(dir, 'feature', gitBinary)

    assert.equal(git('branch', '--show-current'), 'feature')
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('listBranches: lists locals and flags the checked-out branch', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-branches-'))

  try {
    await ensureGitRepo(gitBinary, dir)
    const current = execFileSync(gitBinary, ['branch', '--show-current'], { cwd: dir }).toString().trim()
    execFileSync(gitBinary, ['branch', 'feature'], { cwd: dir })

    const branches = await listBranches(dir, gitBinary)
    const names = branches.map(b => b.name).sort()

    assert.deepEqual(names, [current, 'feature'].sort())
    // The repo's own checkout is flagged; the unused branch is convertible.
    assert.equal(branches.find(b => b.name === current).checkedOut, true)
    assert.equal(branches.find(b => b.name === current).isDefault, true)
    assertSameDirectory(branches.find(b => b.name === current).worktreePath, dir)
    assert.equal(branches.find(b => b.name === 'feature').checkedOut, false)
    assert.equal(branches.find(b => b.name === 'feature').isDefault, false)
    assert.equal(branches.find(b => b.name === 'feature').worktreePath, null)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('listBranches: flags a free default branch as default, not checked out', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-branches-default-'))
  const git = (...args) => execFileSync(gitBinary, args, { cwd: dir }).toString().trim()

  try {
    await ensureGitRepo(gitBinary, dir)
    const trunk = git('branch', '--show-current')
    execFileSync(gitBinary, ['switch', '-c', 'rawr'], { cwd: dir })

    const branches = await listBranches(dir, gitBinary)
    const defaultBranch = branches.find(b => b.name === trunk)

    assert.equal(defaultBranch.checkedOut, false)
    assert.equal(defaultBranch.isDefault, true)
    assert.equal(defaultBranch.worktreePath, null)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('listBranches: a branch claimed by a worktree is flagged checked out', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-branches-wt-'))

  try {
    await ensureGitRepo(gitBinary, dir)
    execFileSync(gitBinary, ['branch', 'feature'], { cwd: dir })
    // addWorktree converts the existing "feature" branch into a worktree.
    const result = await addWorktree(dir, { existingBranch: 'feature' }, gitBinary)

    assert.equal(result.branch, 'feature')
    assert.ok(fs.existsSync(result.path))

    const branches = await listBranches(dir, gitBinary)

    assert.equal(branches.find(b => b.name === 'feature').checkedOut, true)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('listBranches: empty on a non-repo path', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-nonrepo-'))

  try {
    assert.deepEqual(await listBranches(dir, gitBinary), [])
  } finally {
    await fs.promises.rm(dir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 })
  }
})

test('addWorktree: existingBranch checks the branch out without a new branch', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-convert-'))
  const git = (...args) => execFileSync(gitBinary, args, { cwd: dir }).toString().trim()

  try {
    await ensureGitRepo(gitBinary, dir)
    execFileSync(gitBinary, ['branch', 'cool/feature'], { cwd: dir })

    const before = git('branch', '--list').split('\n').length
    const result = await addWorktree(dir, { existingBranch: 'cool/feature' }, gitBinary)

    // No new branch was created — only the existing one is checked out.
    assert.equal(git('branch', '--list').split('\n').length, before)
    assert.equal(result.branch, 'cool/feature')
    // Dir is named off the branch slug, nested under the main repo's .worktrees.
    assert.match(result.path, /[/\\]\.worktrees[/\\]cool-feature/)
    assert.equal(
      execFileSync(gitBinary, ['branch', '--show-current'], { cwd: result.path }).toString().trim(),
      'cool/feature'
    )
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('addWorktree: existing default branch switches the main checkout, not .worktrees/main', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-convert-default-'))
  const git = (...args) => execFileSync(gitBinary, args, { cwd: dir }).toString().trim()

  try {
    await ensureGitRepo(gitBinary, dir)
    const trunk = git('branch', '--show-current')
    execFileSync(gitBinary, ['switch', '-c', 'rawr'], { cwd: dir })

    const result = await addWorktree(dir, { existingBranch: trunk }, gitBinary)

    assert.equal(result.branch, trunk)
    assertSameDirectory(result.path, dir)
    assert.equal(git('branch', '--show-current'), trunk)
    assert.equal(fs.existsSync(path.join(dir, '.worktrees', trunk)), false)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('listBaseBranches: lists local branches and flags the default', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-base-branches-'))
  const git = (...args) => execFileSync(gitBinary, args, { cwd: dir }).toString().trim()

  try {
    await ensureGitRepo(gitBinary, dir)
    const trunk = git('branch', '--show-current')
    execFileSync(gitBinary, ['branch', 'feature'], { cwd: dir })

    const branches = await listBaseBranches(dir, gitBinary)
    const names = branches.map(b => b.name).sort()

    assert.deepEqual(names, [trunk, 'feature'].sort())
    // No remote → all local.
    assert.equal(
      branches.every(b => !b.isRemote),
      true
    )
    // The trunk is flagged as the default.
    assert.equal(branches.find(b => b.name === trunk).isDefault, true)
    assert.equal(branches.find(b => b.name === 'feature').isDefault, false)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('listBaseBranches: empty on a non-repo path', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-base-nonrepo-'))

  try {
    assert.deepEqual(await listBaseBranches(dir, gitBinary), [])
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('addWorktree: base param branches off a specified local branch', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-base-add-'))
  const git = (...args) => execFileSync(gitBinary, args, { cwd: dir }).toString().trim()

  try {
    await ensureGitRepo(gitBinary, dir)
    execFileSync(gitBinary, ['branch', 'staging'], { cwd: dir })

    const result = await addWorktree(
      dir,
      { base: 'staging', branch: 'new-from-staging', name: 'new-from-staging' },
      gitBinary
    )

    assert.equal(result.branch, 'new-from-staging')
    assert.equal(git('-C', result.path, 'merge-base', 'HEAD', 'staging').length > 0, true)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('addWorktree: base origin/main does not set up upstream tracking', async () => {
  // Two repos: a bare "remote" and a clone, so origin/main resolves as a
  // remote-tracking ref — the condition that triggers auto-tracking.
  const remoteDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-remote-'))
  const cloneDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-clone-'))
  const git = (...args) => execFileSync(gitBinary, args, { cwd: cloneDir }).toString().trim()

  try {
    // Seed the remote with a commit on main. Inline identity so it works
    // on CI runners with no global git config.
    execFileSync(gitBinary, ['init', '-b', 'main', remoteDir])
    execFileSync(gitBinary, [
      '-C',
      remoteDir,
      '-c',
      'user.email=hermes@localhost',
      '-c',
      'user.name=Hermes',
      'commit',
      '--allow-empty',
      '-m',
      'root'
    ])

    // Clone so origin/main exists as a remote-tracking ref.
    execFileSync(gitBinary, ['clone', remoteDir, cloneDir])

    const result = await addWorktree(
      cloneDir,
      { base: 'origin/main', branch: 'feature-branch', name: 'feature-branch' },
      gitBinary
    )

    assert.equal(result.branch, 'feature-branch')

    // The new branch must NOT have an upstream — like `git checkout origin/main
    // && git checkout -b feature-branch`, not `git worktree add -b … origin/main`.
    let hasUpstream = true

    try {
      execFileSync(gitBinary, ['-C', result.path, 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'])
    } catch {
      hasUpstream = false
    }

    assert.equal(hasUpstream, false)
  } finally {
    fs.rmSync(remoteDir, { recursive: true, force: true })
    fs.rmSync(cloneDir, { recursive: true, force: true })
  }
})

// A pair of repos: a bare "remote" with `main` and the extra branches in
// `branches`, plus a clone of it. Returns both paths. The caller must remove
// them.
function seedRemoteAndClone(label, branches) {
  const remoteDir = fs.mkdtempSync(path.join(os.tmpdir(), `hermes-${label}-remote-`))
  const cloneDir = fs.mkdtempSync(path.join(os.tmpdir(), `hermes-${label}-clone-`))

  const remoteGit = (...args) =>
    execFileSync(gitBinary, ['-C', remoteDir, ...args])
      .toString()
      .trim()

  execFileSync(gitBinary, ['init', '-b', 'main', remoteDir])
  remoteGit('-c', 'user.email=hermes@localhost', '-c', 'user.name=Hermes', 'commit', '--allow-empty', '-m', 'root')

  for (const branch of branches) {
    remoteGit('branch', branch)
  }

  execFileSync(gitBinary, ['clone', remoteDir, cloneDir])

  return { cloneDir, remoteDir }
}

test('listBranches: offers remote branches that have no local counterpart', async () => {
  const { cloneDir, remoteDir } = seedRemoteAndClone('branches-remote', ['teammate-work'])

  try {
    const branches = await listBranches(cloneDir, gitBinary)
    const byName = new Map(branches.map(b => [b.name, b]))

    // The teammate's branch is only on the remote. The list therefore offers it
    // by its remote-tracking name, with a flag that lets the UI say "track
    // remote".
    const remoteOnly = byName.get('origin/teammate-work')

    assert.ok(remoteOnly)
    assert.equal(remoteOnly.isRemote, true)
    assert.equal(remoteOnly.checkedOut, false)
    assert.equal(remoteOnly.isDefault, false)
    assert.equal(remoteOnly.worktreePath, null)

    // `main` is checked out locally, so it shows once as a local branch.
    // "origin/main" is a duplicate of a branch that is already in the list.
    assert.equal(byName.get('main').isRemote, false)
    assert.equal(byName.has('origin/main'), false)

    // "origin/HEAD" is an alias for the default branch of the remote. It is not
    // a branch.
    assert.equal(
      branches.some(b => b.name.endsWith('/HEAD')),
      false
    )
  } finally {
    fs.rmSync(remoteDir, { recursive: true, force: true })
    fs.rmSync(cloneDir, { recursive: true, force: true })
  }
})

test('addWorktree: a remote branch becomes a local branch tracking it', async () => {
  const { cloneDir, remoteDir } = seedRemoteAndClone('convert-remote', ['teammate-work'])

  try {
    const result = await addWorktree(cloneDir, { existingBranch: 'origin/teammate-work' }, gitBinary)

    const inTree = (...args) =>
      execFileSync(gitBinary, ['-C', result.path, ...args])
        .toString()
        .trim()

    // The worktree is on a local branch that has the name of the remote one. It
    // is not on a detached HEAD, which is the result of a checkout of
    // "origin/teammate-work".
    assert.equal(result.branch, 'teammate-work')
    assert.equal(inTree('branch', '--show-current'), 'teammate-work')
    assert.match(result.path, /[/\\]\.worktrees[/\\]teammate-work/)

    // The branch tracks the remote branch, so push and pull work with no more
    // setup.
    assert.equal(inTree('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'), 'origin/teammate-work')
  } finally {
    fs.rmSync(remoteDir, { recursive: true, force: true })
    fs.rmSync(cloneDir, { recursive: true, force: true })
  }
})

test('addWorktree: a remote default branch gets its own worktree, not a home switch', async () => {
  const { cloneDir, remoteDir } = seedRemoteAndClone('convert-remote-default', [])

  const git = (...args) =>
    execFileSync(gitBinary, ['-C', cloneDir, ...args])
      .toString()
      .trim()

  try {
    // Move the main checkout off `main`, which makes "origin/main" convertible.
    // The local `main` is then free, but the request names the remote-tracking
    // ref.
    git('switch', '-c', 'rawr')
    git('branch', '-D', 'main')

    const result = await addWorktree(cloneDir, { existingBranch: 'origin/main' }, gitBinary)

    // "switch home" applies to a local default branch. A remote ref always gets
    // a new worktree, so the main checkout stays where the user put it.
    assert.equal(result.branch, 'main')
    assert.notEqual(fs.realpathSync(result.path), fs.realpathSync(cloneDir))
    assert.equal(git('branch', '--show-current'), 'rawr')
  } finally {
    fs.rmSync(remoteDir, { recursive: true, force: true })
    fs.rmSync(cloneDir, { recursive: true, force: true })
  }
})

test('switchBranch: non-repo dir short-circuits instead of throwing', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-sw-'))

  try {
    // A plain folder pinned as a project (no .git): its lane label is the
    // folder basename, not a branch — switching must no-op, not error, so
    // callers like "+" new session can proceed with a plain session.
    const result = await switchBranch(dir, '国创大赛', gitBinary)

    assert.deepEqual(result, { branch: null })
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('switchBranch: repo dir still validates the branch name and switches', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-sw-'))

  try {
    execFileSync(gitBinary, ['init', '-b', 'main'], { cwd: dir })
    execFileSync(gitBinary, ['config', 'user.email', 't@example.com'], { cwd: dir })
    execFileSync(gitBinary, ['config', 'user.name', 'test'], { cwd: dir })
    execFileSync(gitBinary, ['commit', '--allow-empty', '-m', 'root'], { cwd: dir })

    // Existing behaviour preserved: an illegal branch name still errors.
    await assert.rejects(() => switchBranch(dir, '///', gitBinary), /Branch name is required/)

    // And switching to a real branch still works.
    const result = await switchBranch(dir, 'main', gitBinary)
    assert.deepEqual(result, { branch: 'main' })
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})
