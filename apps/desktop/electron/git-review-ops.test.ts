import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import { createRequire } from 'node:module'
import os from 'node:os'
import path from 'node:path'

import { afterEach, test } from 'vitest'

import { GitPolicyError, rethrowGitPolicyError } from './git-execution-policy'
import type * as ReviewOpsModule from './git-review-ops'
import {
  gitFor,
  repoStatus,
  resolveRenamePath,
  REVIEW_FILE_CAP,
  reviewHistory,
  reviewHistoryDiff,
  reviewList
} from './git-review-ops'
import { gitBinary } from './git-test-runtime'

// Pure contracts evaluate the current source with an explicit dependency table.
// They never invoke Git/GH, discover policy, or resolve a real repository.
let pureReviewSource: string
function mockReview(overrides: Record<string, unknown> = {}) {
  const root = process.env.S06_OWNER_ROOT || (fs.existsSync('electron/git-review-ops.ts')
    ? path.resolve('../..') : process.cwd())
  if (!pureReviewSource) {
    const requireTest = createRequire(path.join(process.env.S06_DESKTOP_DEPS || path.join(root, 'apps/desktop'), 'package.json'))
    const esbuild = requireTest('esbuild')
    try {
      pureReviewSource = esbuild.transformSync(fs.readFileSync(path.join(root, 'apps/desktop/electron/git-review-ops.ts'), 'utf8'),
        {loader: 'ts', format: 'cjs', target: 'node24'}).code
    } finally { esbuild.stop() }
  }
  const cwd = path.join(root, 'tmp', 'pure-selected-repo')
  const git = {
    env() {},
    status: async () => ({files: [], tracking: null, current: null}),
    diffSummary: async () => ({files: []}),
    ...overrides.git as object
  }
  const policy = {
    rethrowGitPolicyError,
    gitExecutionPolicy: async (_cwd, _binary, args = []) => ({argv: args}),
    simpleGitTransport: () => ({binary: 'mock-git', environment: {}}),
    executeGit: () => { throw new Error('Unexpected executeGit in pure contract') },
    executeGh: () => { throw new Error('Unexpected executeGh in pure contract') },
    ...overrides.policy as object
  }
  const calls: unknown[][] = []
  const dependencies = {
    'node:fs/promises': {}, 'node:path': path,
    'simple-git': options => { calls.push([options]); return git },
    './hardening': {resolveRequestedPathForIpc: () => cwd},
    './git-execution-policy': policy
  }
  const module = {exports: {}} as {exports: typeof ReviewOpsModule}
  new Function('require', 'module', 'exports', pureReviewSource)(name => {
    if (!(name in dependencies)) {throw new Error(`Unexpected pure dependency: ${name}`)}
    return dependencies[name]
  }, module, module.exports)
  return {ops: module.exports, cwd, calls}
}

function reviewGate<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return {promise, resolve, reject}
}

test.each([true, false])('pure S06 review: policy refusal cached=%s waits for status sibling', async cached => {
  const status = reviewGate<{files: never[]}>()
  const refusal = new GitPolicyError('diff refused')
  const {ops} = mockReview({git: {status: () => status.promise}, policy: {
    gitExecutionPolicy: async (_cwd, _binary, args = []) => {
      if (args[0] === 'diff' && args.includes('--cached') === cached) {throw refusal}
      return {argv: args}
    }
  }})
  let settled = false
  const result = ops.reviewList('renderer-repo', 'uncommitted', null, 'selected-git')
    .then(value => ({value}), error => ({error})).finally(() => { settled = true })
  try {
    await new Promise<void>(resolve => setImmediate(resolve))
    assert.equal(settled, false, 'review returned while status was still owned')
  } finally { status.resolve({files: []}) }
  assert.equal((await result as {error: unknown}).error, refusal)
})

test('pure S06 review: a first diff refusal still starts and drains the other diff', async () => {
  const diff = reviewGate<{files: never[]}>()
  const refusal = new GitPolicyError('cached diff refused')
  let otherStarted = false
  const {ops} = mockReview({git: {diffSummary: () => { otherStarted = true; return diff.promise }}, policy: {
    gitExecutionPolicy: async (_cwd, _binary, args = []) => {
      if (args.includes('--cached')) {throw refusal}
      return {argv: args}
    }
  }})
  let settled = false
  const result = ops.reviewList('renderer-repo', 'uncommitted', null, 'selected-git')
    .then(value => ({value}), error => ({error})).finally(() => { settled = true })
  try {
    await new Promise<void>(resolve => setImmediate(resolve))
    assert.equal(otherStarted, true)
    assert.equal(settled, false)
  } finally { diff.resolve({files: []}) }
  assert.equal((await result as {error: unknown}).error, refusal)
})

test('pure S06 review: synchronous status failure cannot abandon diff siblings', async () => {
  let diffs = 0
  const {ops} = mockReview({git: {
    status: () => { throw new Error('status unavailable') },
    diffSummary: async () => { diffs++; return {files: []} }
  }})
  assert.deepEqual(await ops.reviewList('renderer-repo', 'uncommitted', null, 'selected-git'), {files: [], base: null})
  assert.equal(diffs, 2)
})

test('pure S06 review: later typed refusal takes precedence over an ordinary status error', async () => {
  const status = reviewGate<never>()
  const diff = reviewGate<never>()
  const refusal = new GitPolicyError('late diff refused')
  const {ops} = mockReview({git: {status: () => status.promise,
    diffSummary: args => args.includes('--cached') ? diff.promise : Promise.resolve({files: []})}})
  const result = ops.reviewList('renderer-repo', 'uncommitted', null, 'selected-git')
    .then(value => ({value}), error => ({error}))
  await new Promise<void>(resolve => setImmediate(resolve))
  status.reject(new Error('ordinary status error'))
  await new Promise<void>(resolve => setImmediate(resolve))
  diff.reject(refusal)
  assert.equal((await result as {error: unknown}).error, refusal)
})

test('pure S06 review: success retains selected cwd, executable and staged counts', async () => {
  const policyCalls: unknown[][] = []
  const {ops, cwd, calls} = mockReview({git: {
    status: async () => ({files: [{path: 'tracked.ts', index: 'M', working_dir: ' ' }]}),
    diffSummary: async args => ({files: args.includes('--cached')
      ? [{file: 'tracked.ts', insertions: 3, deletions: 2, binary: false}] : []})
  }, policy: {gitExecutionPolicy: async (...args) => { policyCalls.push(args); return {argv: args[2] || []} }}})
  const result = await ops.reviewList('renderer-repo', 'uncommitted', null, 'selected-git')
  assert.equal(result.files[0].added, 3)
  assert.equal(result.files[0].removed, 2)
  assert.equal((calls[0][0] as {baseDir: string}).baseDir, cwd)
  assert.equal(policyCalls.length, 3)
  for (const args of policyCalls) {assert.deepEqual(args.slice(0, 2), [cwd, 'selected-git'])}
})

test('pure S06 review: ordinary diff failure retains empty read fallback', async () => {
  const {ops} = mockReview({git: {diffSummary: async () => { throw new Error('not a repo') }}})
  assert.deepEqual(await ops.reviewList('renderer-repo', 'uncommitted', null, 'selected-git'), {files: [], base: null})
})

test.each([
  {stderr: '  GraphQL: Resource not accessible by integration\n', stdout: 'ignored', reason: 'Resource not accessible by integration'},
  {stderr: ' ', stdout: '  no commits between main and feature\n', reason: 'no commits between main and feature'},
  {stderr: '', stdout: '', reason: 'gh pr create failed'}
])('pure S06 GH: PR create retains concrete failure $reason', async ({stderr, stdout, reason}) => {
  const {ops} = mockReview({policy: {executeGh: async () => ({exitCode: 1, stdout, stderr})}})
  await assert.rejects(() => ops.reviewCreatePr('renderer-repo', 'selected-git', 'selected-gh'),
    error => error instanceof Error && error.message.includes(reason) && !error.message.includes('ignored'))
})

test('pure S06 GH: successful PR preserves last output URL and exact request authority', async () => {
  const requests: unknown[][] = []
  const {ops, cwd} = mockReview({policy: {executeGh: async (...args) => {
    requests.push(args); return {exitCode: 0, stdout: 'notice\nhttps://github.example/repo/pull/7\n', stderr: 'warning'}
  }}})
  assert.deepEqual(await ops.reviewCreatePr('renderer-repo', 'selected-git', 'selected-gh'),
    {url: 'https://github.example/repo/pull/7'})
  assert.deepEqual(requests[0].slice(0, 3), [cwd, 'selected-gh', ['pr', 'create', '--fill']])
})

test('pure S06 GH: a typed push refusal prevents PR creation', async () => {
  const refusal = new GitPolicyError('push refused')
  let ghCalls = 0
  const {ops} = mockReview({git: {status: async () => { throw refusal }}, policy: {
    executeGh: async () => { ghCalls++; return {exitCode: 0, stdout: '', stderr: ''} }
  }})
  await assert.rejects(() => ops.reviewCreatePr('renderer-repo', 'selected-git', 'selected-gh'), error => error === refusal)
  assert.equal(ghCalls, 0)
})

const tempDirs: string[] = []

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    fs.rmSync(dir, { force: true, recursive: true })
  }
})

function makeRepo() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-desktop-git-status-'))

  tempDirs.push(dir)
  execFileSync(gitBinary, ['init', '-q'], { cwd: dir })
  execFileSync(gitBinary, ['config', 'user.email', 'hermes-test@example.com'], { cwd: dir })
  execFileSync(gitBinary, ['config', 'user.name', 'Hermes Test'], { cwd: dir })
  fs.writeFileSync(path.join(dir, 'tracked.txt'), 'tracked\n')
  execFileSync(gitBinary, ['add', 'tracked.txt'], { cwd: dir })
  execFileSync(gitBinary, ['commit', '-qm', 'initial'], { cwd: dir })

  return dir
}

test('resolveRenamePath: plain path is unchanged', () => {
  assert.equal(resolveRenamePath('src/a.ts'), 'src/a.ts')
})

test('gitFor accepts the main-owned native Git executable', async () => {
  await assert.doesNotReject(() => gitFor(process.cwd(), gitBinary))
})

test('gitFor runs git through a spaced binary path', async () => {
  if (process.platform !== 'win32') {
    return
  }

  const gitBin = path.join(process.env.ProgramFiles || String.raw`C:\Program Files`, 'Git', 'cmd', 'git.exe')

  if (!fs.existsSync(gitBin)) {
    return
  }

  const repo = makeRepo()

  fs.writeFileSync(path.join(repo, 'changed.txt'), 'review me\n')

  const status = await (await gitFor(repo, gitBin)).status()

  assert.equal(status.not_added.includes('changed.txt'), true)
})

test('resolveRenamePath: simple rename resolves to the new path', () => {
  assert.equal(resolveRenamePath('old.ts => new.ts'), 'new.ts')
})

test('resolveRenamePath: brace rename resolves to the new path', () => {
  assert.equal(resolveRenamePath('src/{old => new}/file.ts'), 'src/new/file.ts')
})

test('resolveRenamePath: brace rename collapsing a segment', () => {
  assert.equal(resolveRenamePath('src/{lib => }/file.ts'), 'src/file.ts')
})

test('repoStatus reports an untracked directory without recursively listing its contents', async () => {
  const dir = makeRepo()
  const nested = path.join(dir, 'generated', 'deep')

  fs.mkdirSync(nested, { recursive: true })
  fs.writeFileSync(path.join(nested, 'large-output.txt'), 'generated\n')

  const status = await repoStatus(dir, gitBinary)

  assert.ok(status)
  assert.equal(status.untracked, 1)
  assert.equal(status.changed, 1)
  assert.deepEqual(
    status.files.map(file => file.path),
    ['generated/']
  )
})

test('reviewList reports an untracked directory without recursively listing its contents', async () => {
  const dir = makeRepo()
  const nested = path.join(dir, 'browser-profile', 'Default', 'Cache')

  fs.mkdirSync(nested, { recursive: true })

  for (let i = 0; i < 20; i++) {
    fs.writeFileSync(path.join(nested, `cache-${i}.bin`), 'generated\n')
  }

  const result = await reviewList(dir, 'uncommitted', null, gitBinary)

  assert.deepEqual(
    result.files.map(file => file.path),
    ['browser-profile/']
  )
})

test('reviewList caps the file payload returned to the renderer', async () => {
  const dir = makeRepo()

  for (let i = 0; i < REVIEW_FILE_CAP + 10; i++) {
    fs.writeFileSync(path.join(dir, `untracked-${String(i).padStart(4, '0')}.txt`), 'generated\n')
  }

  const result = await reviewList(dir, 'uncommitted', null, gitBinary)

  assert.equal(result.files.length, REVIEW_FILE_CAP)
}, 30_000)

test('reviewHistory returns bounded, newest-first commit metadata', async () => {
  const dir = makeRepo()

  fs.writeFileSync(path.join(dir, 'history.txt'), 'second\n')
  execFileSync(gitBinary, ['add', 'history.txt'], { cwd: dir })
  execFileSync(gitBinary, ['commit', '-qm', 'add history fixture'], { cwd: dir })

  const commits = await reviewHistory(dir, 2, gitBinary)

  assert.equal(commits.length, 2)
  assert.equal(commits[0].subject, 'add history fixture')
  assert.equal(commits[1].subject, 'initial')
  assert.match(commits[0].sha, /^[0-9a-f]{40}$/)
  assert.match(commits[0].shortSha, /^[0-9a-f]{7,}$/)
  assert.equal(commits[0].parents.length, 1)
  assert.equal(Boolean(Date.parse(commits[0].authoredAt)), true)
})

test('reviewHistoryDiff returns one selected commit and rejects revision expressions', async () => {
  const dir = makeRepo()

  fs.writeFileSync(path.join(dir, 'history.txt'), 'second\n')
  execFileSync(gitBinary, ['add', 'history.txt'], { cwd: dir })
  execFileSync(gitBinary, ['commit', '-qm', 'add history fixture'], { cwd: dir })

  const [commit] = await reviewHistory(dir, 1, gitBinary)
  const diff = await reviewHistoryDiff(dir, commit.sha, gitBinary)

  assert.match(diff, /\+second/)
  await assert.doesNotMatch(await reviewHistoryDiff(dir, 'HEAD~1', gitBinary), /./)
})
