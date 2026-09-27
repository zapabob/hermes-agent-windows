import assert from 'node:assert/strict'
import path from 'node:path'

import { test } from 'vitest'

import { type GitCandidateFs, windowsGitCandidates } from './git-binary-candidates'

const localAppData = path.join('C:', 'Users', 'alice', 'AppData', 'Local')
const programFiles = path.join('C:', 'Program Files')
const programFilesX86 = path.join('C:', 'Program Files (x86)')

const ugitGit = (version: string): string =>
  path.join(localAppData, 'UGit', `app-${version}`, 'resources', 'app', 'git', 'cmd', 'git.exe')

function fakeFs(entries: string[] | null, files: string[]): GitCandidateFs {
  return {
    existsSync: candidate => files.includes(candidate),
    readdirSync: dir => {
      assert.equal(dir, path.join(localAppData, 'UGit'))

      if (entries === null) {
        throw new Error('ENOENT')
      }

      return entries
    }
  }
}

const env = { localAppData, programFiles, programFilesX86 }

test('a GUI-launched Windows desktop resolves UGit without a PATH entry', () => {
  const bundled = ugitGit('5.50.1')
  const fs = fakeFs(['app-5.50.1'], [bundled])

  assert.equal(windowsGitCandidates(env, fs).find(fs.existsSync), bundled)
})

test('PortableGit keeps precedence and UGit versions are numeric newest-first', () => {
  const portable = path.join(localAppData, 'hermes', 'git', 'cmd', 'git.exe')
  const fs = fakeFs(['app-9.0.0', 'app-10.0.0'], [portable, ugitGit('9.0.0'), ugitGit('10.0.0')])
  const candidates = windowsGitCandidates(env, fs)

  assert.deepEqual(candidates.slice(0, 4), [
    portable,
    path.join(localAppData, 'hermes', 'git', 'bin', 'git.exe'),
    ugitGit('10.0.0'),
    ugitGit('9.0.0')
  ])
  assert.equal(candidates.find(fs.existsSync), portable)
})

test('missing or incomplete UGit installs leave the existing Git locations available', () => {
  const systemGit = path.join(programFiles, 'Git', 'cmd', 'git.exe')

  for (const entries of [null, ['app-5.50.1', 'Update.exe']]) {
    const fs = fakeFs(entries, [systemGit])
    const candidates = windowsGitCandidates(env, fs)

    assert.equal(candidates.find(fs.existsSync), systemGit)
    assert.equal(candidates.includes(ugitGit('5.50.1')), false)
  }
})
