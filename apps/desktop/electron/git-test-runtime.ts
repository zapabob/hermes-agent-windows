// Test-only binding to the actual source owner and native Git/Python executables.
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

import { configureGitPolicyRuntime } from './git-execution-policy'

function executable(name: string): string {
  for (const directory of (process.env.PATH || '').split(path.delimiter)) {
    const candidate = path.resolve(directory, name + (process.platform === 'win32' ? '.exe' : ''))

    if (fs.existsSync(candidate)) {
      return candidate
    }
  }

  throw new Error(`Native test executable is unavailable: ${name}`)
}

export const gitBinary = process.env.S06_GIT || executable('git')

const python =
  process.env.S06_PYTHON ||
  execFileSync(executable('python'), ['-I', '-c', 'import sys;sys.stdout.write(sys.executable)'], {
    encoding: 'utf8',
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: 5000
  }).trim()

const ownerRoot = path.resolve(process.env.S06_OWNER_ROOT || path.join(import.meta.dirname, '../../..'))
configureGitPolicyRuntime(
  () => ({ command: python, argsPrefix: [], ownerRoot }),
  () => gitBinary
)
