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
  passiveGitArgs,
  passiveGitEnvironment,
  resolvePassiveUpdateRemote
} from './update-remote'

test('canonicalGitHubRemote normalizes SSH and HTTPS forms to the same value', () => {
  assert.equal(canonicalGitHubRemote('git@github.com:NousResearch/hermes-agent.git'), OFFICIAL_REPO_CANONICAL)
  assert.equal(canonicalGitHubRemote('git@github.com:NousResearch/hermes-agent'), OFFICIAL_REPO_CANONICAL)
  assert.equal(canonicalGitHubRemote('ssh://git@github.com/NousResearch/hermes-agent.git'), OFFICIAL_REPO_CANONICAL)
  assert.equal(canonicalGitHubRemote('https://github.com/NousResearch/hermes-agent.git'), OFFICIAL_REPO_CANONICAL)
  // Case-insensitive: an uppercased owner still canonicalizes to the same repo.
  assert.equal(canonicalGitHubRemote('git@github.com:nousresearch/hermes-agent.git'), OFFICIAL_REPO_CANONICAL)
  assert.equal(canonicalGitHubRemote('bob@github.com:NousResearch/hermes-agent.git'), OFFICIAL_REPO_CANONICAL)
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
  [
    'fork scp-style SSH',
    'git@github.com:zapabob/hermes-agent-windows.git',
    'https://github.com/zapabob/hermes-agent-windows.git'
  ],
  [
    'fork ssh URL',
    'ssh://git@github.com/zapabob/hermes-agent-windows.git',
    'https://github.com/zapabob/hermes-agent-windows.git'
  ],
  ['official HTTPS', OFFICIAL_REPO_HTTPS_URL, OFFICIAL_REPO_HTTPS_URL],
  [
    'fork HTTPS',
    'https://github.com/zapabob/hermes-agent-windows.git',
    'https://github.com/zapabob/hermes-agent-windows.git'
  ],
  [
    'custom GitHub SSH username',
    'bob@github.com:zapabob/hermes-agent-windows.git',
    'https://github.com/zapabob/hermes-agent-windows.git'
  ],
  ['scp alias', 'work-github:zapabob/hermes-agent-windows.git', null],
  ['remote helper', 'ext::credential-wrapper %S repo', null],
  ['local path', 'C:\\repos\\hermes-agent', null],
  ['non-GitHub SSH', 'git@gitlab.com:example/hermes-agent.git', null],
  ['HTTPS embedded token', 'https://user:token@github.com/zapabob/hermes-agent-windows.git', null],
  ['HTTP embedded username', 'http://user@github.com/zapabob/hermes-agent-windows.git', null],
  ['encoded HTTPS userinfo', 'https://%75ser:%74oken@github.com/zapabob/hermes-agent-windows.git', null],
  ['empty HTTPS username delimiter', 'https://@github.com/zapabob/hermes-agent-windows.git', null],
  ['empty HTTPS username and password', 'https://:@github.com/zapabob/hermes-agent-windows.git', null],
  ['missing origin', '', null]
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

test('main process passive update check never fetches origin or enables credential UI', () => {
  const mainSource = fs.readFileSync(new URL('./main.ts', import.meta.url), 'utf8').replace(/\r\n/g, '\n')
  const checkStart = mainSource.indexOf('async function checkUpdates()')
  const checkEnd = mainSource.indexOf('\nasync function ', checkStart)
  const passiveCheck = mainSource.slice(checkStart, checkEnd)

  assert.notEqual(checkStart, -1, 'checkUpdates must exist')
  assert.notEqual(checkEnd, -1, 'checkUpdates boundary must exist')
  assert.match(passiveCheck, /const passiveRemote = resolvePassiveUpdateRemote\(originUrl\)/)
  assert.match(passiveCheck, /noCredentialUI: true/)
  assert.match(passiveCheck, /passiveGitArgs\(\['ls-remote'/)
  assert.match(passiveCheck, /getPassiveGitIsolation\(\)\.cwd/)
  assert.doesNotMatch(passiveCheck, /runGit\(\['fetch'/)
  assert.doesNotMatch(passiveCheck, /'origin', branch/)
  assert.doesNotMatch(passiveCheck, /cwd: os\.tmpdir\(\)/)
})

test('origin discovery for passive probes ignores repository and credential environment poisoning', () => {
  const mainSource = fs.readFileSync(new URL('./main.ts', import.meta.url), 'utf8').replace(/\r\n/g, '\n')
  const start = mainSource.indexOf('async function getOriginUrl(updateRoot)')
  const end = mainSource.indexOf('\n}', start) + 2
  const helper = mainSource.slice(start, end)

  assert.notEqual(start, -1)
  assert.match(helper, /passiveGitArgs\(\['remote', 'get-url', 'origin'\]\)/)
  assert.match(helper, /noCredentialUI: true/)
  assert.match(helper, /cwd: updateRoot/)
})

test('main-process title fetching uses only the guarded renderer transport', () => {
  const mainSource = fs.readFileSync(new URL('./main.ts', import.meta.url), 'utf8').replace(/\r\n/g, '\n')
  const start = mainSource.indexOf('function fetchLinkTitle(rawUrl)')
  const end = mainSource.indexOf('\n}\n\n// ─── Favicon resolution', start) + 2
  const fetcher = mainSource.slice(start, end)

  assert.notEqual(start, -1)
  assert.match(fetcher, /!linkTitleTransportAllowsRemoteFetch\(\)/)
  assert.doesNotMatch(fetcher, /fetchHtmlTitleWithCurl/)
  assert.ok(
    fetcher.indexOf('!linkTitleTransportAllowsRemoteFetch()') < fetcher.indexOf('fetchHtmlTitleWithRenderer(url)')
  )
})

test('no-credential Git mode suppresses helpers, GCM, askpass, and repository inheritance', () => {
  assert.deepEqual(passiveGitArgs(['ls-remote', 'https://example.invalid/repo.git']), [
    '-c',
    'credential.helper=',
    '-c',
    'core.askPass=',
    '-c',
    'core.fsmonitor=false',
    '-c',
    'core.untrackedCache=false',
    '-c',
    'http.proxy=',
    '-c',
    'https.proxy=',
    'ls-remote',
    'https://example.invalid/repo.git'
  ])
  assert.deepEqual(
    passiveGitEnvironment(
      {
        KEEP: 'yes',
        Path: 'C:\\Windows\\System32',
        HOME: 'C:\\credential-home',
        USERPROFILE: 'C:\\credential-profile',
        CURL_HOME: 'C:\\credential-curl',
        https_proxy: 'http://user:secret@proxy.invalid:8080',
        GCM_INTERACTIVE: 'Full',
        Git_Dir: 'C:\\poisoned.git',
        git_work_tree: 'C:\\poisoned',
        Git_Common_Dir: 'C:\\poisoned-common',
        git_object_directory: 'C:\\poisoned-objects',
        Git_Alternate_Object_Directories: 'C:\\poisoned-alt',
        Git_Ssh: 'credential-wrapper.exe',
        git_ssh_command: 'credential-wrapper.exe --token secret'
      },
      'NUL',
      'C:\\isolated\\home',
      'C:\\isolated\\cwd'
    ),
    {
      Path: 'C:\\Windows\\System32',
      GIT_TERMINAL_PROMPT: '0',
      GCM_INTERACTIVE: 'Never',
      GIT_ASKPASS: '',
      SSH_ASKPASS: '',
      SSH_ASKPASS_REQUIRE: 'never',
      GIT_ALLOW_PROTOCOL: 'https:http',
      GIT_CONFIG_NOSYSTEM: '1',
      GIT_CONFIG_SYSTEM: 'NUL',
      GIT_CONFIG_GLOBAL: 'NUL',
      GIT_CONFIG_COUNT: '0',
      GIT_CONFIG_PARAMETERS: '',
      GIT_DISCOVERY_ACROSS_FILESYSTEM: '0',
      GIT_CEILING_DIRECTORIES: 'C:\\isolated\\cwd',
      HOME: 'C:\\isolated\\home',
      USERPROFILE: 'C:\\isolated\\home',
      CURL_HOME: 'C:\\isolated\\home',
      NETRC: 'NUL',
      HTTP_PROXY: '',
      HTTPS_PROXY: '',
      ALL_PROXY: '',
      NO_PROXY: ''
    }
  )
})
