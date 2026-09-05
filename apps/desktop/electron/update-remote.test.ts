/**
 * Tests for electron/update-remote.ts — the remote policy that keeps passive
 * update checks off every SSH credential boundary.
 *
 * Run with: node --test electron/update-remote.test.ts
 * (Wired into npm test:desktop:platforms in package.json.)
 *
 * Why this matters: a background `git fetch origin` authenticates over SSH
 * and can ask a FIDO2/passkey-backed key for an unexplained hardware touch.
 * Passive checks must use anonymous HTTPS for GitHub origins, including forks,
 * and refuse SSH transports that cannot be translated safely. Explicit update
 * operations retain the user's configured transport.
 */

import assert from 'node:assert/strict'
import fs from 'node:fs'

import { test } from 'vitest'

import {
  canonicalGitHubRemote,
  isOfficialSshRemote,
  isSshRemote,
  OFFICIAL_REPO_CANONICAL,
  OFFICIAL_REPO_HTTPS_URL,
  resolvePassiveUpdateRemote
} from './update-remote'

test('canonicalGitHubRemote normalizes SSH and HTTPS forms to the same value', () => {
  assert.equal(canonicalGitHubRemote('git@github.com:NousResearch/hermes-agent.git'), OFFICIAL_REPO_CANONICAL)
  assert.equal(canonicalGitHubRemote('git@github.com:NousResearch/hermes-agent'), OFFICIAL_REPO_CANONICAL)
  assert.equal(canonicalGitHubRemote('ssh://git@github.com/NousResearch/hermes-agent.git'), OFFICIAL_REPO_CANONICAL)
  assert.equal(canonicalGitHubRemote('https://github.com/NousResearch/hermes-agent.git'), OFFICIAL_REPO_CANONICAL)
  // Case-insensitive: an uppercased owner still canonicalizes to the same repo.
  assert.equal(canonicalGitHubRemote('git@github.com:nousresearch/hermes-agent.git'), OFFICIAL_REPO_CANONICAL)
  // Trailing slashes are stripped.
  assert.equal(canonicalGitHubRemote('https://github.com/NousResearch/hermes-agent/'), OFFICIAL_REPO_CANONICAL)
})

test('canonicalGitHubRemote is empty for falsy input', () => {
  assert.equal(canonicalGitHubRemote(''), '')
  assert.equal(canonicalGitHubRemote(null), '')
  assert.equal(canonicalGitHubRemote(undefined), '')
})

test('isSshRemote detects scp-like and ssh:// forms only', () => {
  assert.equal(isSshRemote('git@github.com:NousResearch/hermes-agent.git'), true)
  assert.equal(isSshRemote('ssh://git@github.com/NousResearch/hermes-agent.git'), true)
  assert.equal(isSshRemote('https://github.com/NousResearch/hermes-agent.git'), false)
  assert.equal(isSshRemote(''), false)
  assert.equal(isSshRemote(null), false)
})

test('isOfficialSshRemote is true only for the official repo over SSH', () => {
  assert.equal(isOfficialSshRemote('git@github.com:NousResearch/hermes-agent.git'), true)
  assert.equal(isOfficialSshRemote('git@github.com:NousResearch/hermes-agent'), true)
  assert.equal(isOfficialSshRemote('ssh://git@github.com/NousResearch/hermes-agent.git'), true)
  // Case-insensitive owner/repo match.
  assert.equal(isOfficialSshRemote('git@github.com:nousresearch/hermes-agent.git'), true)
})

test('isOfficialSshRemote does NOT match forks, other hosts, or HTTPS', () => {
  // A fork over SSH belongs to the user — fetching it is their own remote,
  // not the official upstream, so the SSH-avoidance swap must not apply.
  assert.equal(isOfficialSshRemote('git@github.com:someuser/hermes-agent.git'), false)
  // Same repo name on a different host is not the official repo.
  assert.equal(isOfficialSshRemote('git@gitlab.com:NousResearch/hermes-agent.git'), false)
  // HTTPS to the official repo never prompts for SSH/FIDO2, so it keeps the
  // normal fetch path — must not be flagged as an official SSH remote.
  assert.equal(isOfficialSshRemote('https://github.com/NousResearch/hermes-agent.git'), false)
  assert.equal(isOfficialSshRemote(''), false)
  assert.equal(isOfficialSshRemote(null), false)
})

test('OFFICIAL_REPO_HTTPS_URL canonicalizes to OFFICIAL_REPO_CANONICAL', () => {
  // Invariant: the URL we substitute in must be the same repo we detect.
  assert.equal(canonicalGitHubRemote(OFFICIAL_REPO_HTTPS_URL), OFFICIAL_REPO_CANONICAL)
})

test.each([
  ['official scp-style SSH', 'git@github.com:NousResearch/hermes-agent.git', OFFICIAL_REPO_HTTPS_URL],
  ['official ssh URL', 'ssh://git@github.com/NousResearch/hermes-agent.git', OFFICIAL_REPO_HTTPS_URL],
  ['fork scp-style SSH', 'git@github.com:zapabob/hermes-agent-windows.git', 'https://github.com/zapabob/hermes-agent-windows.git'],
  ['fork ssh URL', 'ssh://git@github.com/zapabob/hermes-agent-windows.git', 'https://github.com/zapabob/hermes-agent-windows.git'],
  ['official HTTPS', OFFICIAL_REPO_HTTPS_URL, 'origin'],
  ['fork HTTPS', 'https://github.com/zapabob/hermes-agent-windows.git', 'origin'],
  ['non-GitHub SSH', 'git@gitlab.com:example/hermes-agent.git', null],
  ['missing origin', '', 'origin']
])('passive update remote: %s', (_label, originUrl, expected) => {
  assert.equal(resolvePassiveUpdateRemote(originUrl), expected)
})

test('passive update planning never returns an SSH transport', () => {
  for (const originUrl of [
    'git@github.com:NousResearch/hermes-agent.git',
    'ssh://git@github.com/NousResearch/hermes-agent.git',
    'git@github.com:zapabob/hermes-agent-windows.git',
    'git@gitlab.com:example/hermes-agent.git'
  ]) {
    const remote = resolvePassiveUpdateRemote(originUrl)

    assert.equal(remote === null || !isSshRemote(remote), true)
  }
})

test('main process cannot reach git fetch from the passive SSH branch', () => {
  const mainSource = fs.readFileSync(new URL('./main.ts', import.meta.url), 'utf8').replace(/\r\n/g, '\n')
  const checkStart = mainSource.indexOf('async function checkUpdates()')
  const fetchBoundary = mainSource.indexOf('// Self-heal abandoned git lock files', checkStart)
  const sshBranch = mainSource.slice(checkStart, fetchBoundary)

  assert.notEqual(checkStart, -1, 'checkUpdates must exist')
  assert.notEqual(fetchBoundary, -1, 'non-SSH fetch boundary must exist')
  assert.match(sshBranch, /const passiveRemote = resolvePassiveUpdateRemote\(originUrl\)/)
  assert.match(sshBranch, /if \(isSshRemote\(originUrl\)\)/)
  assert.match(sshBranch, /runGit\(\['-c', 'credential\.helper=', 'ls-remote', passiveRemote/)
  assert.match(sshBranch, /error: 'passive-ssh-check-disabled'/)
  assert.doesNotMatch(sshBranch, /runGit\(\['fetch'/)

  const nonSshBranch = mainSource.slice(fetchBoundary, mainSource.indexOf('\nasync function ', fetchBoundary))

  assert.match(nonSshBranch, /runGit\(\['fetch', '--quiet', 'origin', branch\]/)
})
