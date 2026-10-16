import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { test } from 'vitest'

import { executeGitChecked, GitPolicyError } from './git-execution-policy'
import { gitBinary, isolateNativeGitConfig } from './git-test-runtime'

for (const source of ['GLOBAL', 'SYSTEM']) {
  test(`native Git fixture isolates ${source.toLowerCase()} config without bypassing repository policy`, async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-git-isolation-'))
    const restoreOuter = isolateNativeGitConfig()
    let restoreInner: (() => void) | undefined

    try {
      execFileSync(gitBinary, ['init', '-q', dir], { windowsHide: true })
      const poison = path.join(dir, 'ambient config')
      fs.writeFileSync(poison, '[core]\n  autocrlf=invalid\n', 'utf8')
      process.env[`GIT_CONFIG_${source}`] = poison

      if (source === 'SYSTEM') {
        process.env.GIT_CONFIG_NOSYSTEM = '0'
      }

      const read = () => executeGitChecked(dir, gitBinary, ['rev-parse', '--is-inside-work-tree'])

      await assert.rejects(read, GitPolicyError)
      restoreInner = isolateNativeGitConfig()
      assert.equal((await read()).trim(), 'true')

      // A fresh repository-local rejection must still cross the real transport.
      execFileSync(gitBinary, ['-C', dir, 'config', 'core.autocrlf', 'invalid'], { windowsHide: true })
      await assert.rejects(read, GitPolicyError)
      execFileSync(gitBinary, ['-C', dir, 'config', '--unset', 'core.autocrlf'], { windowsHide: true })
      assert.equal((await read()).trim(), 'true')

      restoreInner()
      restoreInner = undefined
      assert.equal(process.env[`GIT_CONFIG_${source}`], poison)
      await assert.rejects(read, GitPolicyError)
    } finally {
      restoreInner?.()
      restoreOuter()
      fs.rmSync(dir, { recursive: true, force: true })
    }
  })
}
