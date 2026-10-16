// Test-only binding to the actual source owner and native Git/Python executables.
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { configureGitPolicyRuntime } from './git-execution-policy'

/** Isolate native fixture setup and transport from machine Git configuration. */
export function isolateNativeGitConfig(): () => void {
  const isConfigKey = (key: string) => /^GIT_CONFIG(?:$|_)/i.test(key)
  const previous = Object.entries(process.env).filter(([key]) => isConfigKey(key))

  for (const key of Object.keys(process.env)) {
    if (isConfigKey(key)) {
      delete process.env[key]
    }
  }

  // Git for Windows accepts NUL, not Node's Win32 device namespace path.
  const emptyConfig = process.platform === 'win32' ? 'NUL' : os.devNull
  process.env.GIT_CONFIG_GLOBAL = emptyConfig
  process.env.GIT_CONFIG_SYSTEM = emptyConfig
  process.env.GIT_CONFIG_NOSYSTEM = '1'

  return () => {
    for (const key of Object.keys(process.env)) {
      if (isConfigKey(key)) {
        delete process.env[key]
      }
    }

    for (const [key, value] of previous) {
      if (value !== undefined) {
        process.env[key] = value
      }
    }
  }
}

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
