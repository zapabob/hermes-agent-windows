import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'

import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { buildAppEnv, type SandboxPaths, stripInheritedDesktopOverrides } from './app-env'

const REPO_ROOT = path.resolve(import.meta.dirname, '..', '..', '..')
const FAKE_PRIMARY = path.join(os.tmpdir(), 'not-the-sandbox', 'primary-checkout')

function valuesFor(env: Record<string, string>, name: string): string[] {
  return Object.entries(env)
    .filter(([key]) => key.toUpperCase() === name)
    .map(([, value]) => value)
}

describe('stripInheritedDesktopOverrides', () => {
  it('drops a runner HERMES_DESKTOP_CWD so the sandbox never opens the real checkout', () => {
    const env = stripInheritedDesktopOverrides({
      HERMES_DESKTOP_CWD: 'C:\\Users\\dev\\hermes-agent',
      PATH: '/usr/bin'
    })

    expect(env).not.toHaveProperty('HERMES_DESKTOP_CWD')
    expect(env.PATH).toBe('/usr/bin')
  })

  it('drops every inherited desktop override, whatever its casing', () => {
    const env = stripInheritedDesktopOverrides({
      HERMES_DESKTOP_DEV_SERVER: 'http://127.0.0.1:5174',
      HERMES_DESKTOP_HERMES_ROOT: '/home/dev/hermes-agent',
      hermes_desktop_startup_x_url: 'https://example.invalid'
    })

    expect(Object.keys(env)).toEqual([])
  })

  it('keeps non-desktop Hermes settings and leaves the input untouched', () => {
    const input = { HERMES_HOME: '/tmp/sandbox/hermes-home', HERMES_DESKTOP_CWD: '/real' }
    const env = stripInheritedDesktopOverrides(input)

    expect(env).toEqual({ HERMES_HOME: '/tmp/sandbox/hermes-home' })
    expect(input.HERMES_DESKTOP_CWD).toBe('/real')
  })
})

describe('buildAppEnv with a hostile inherited environment', () => {
  let root: string
  let sandbox: SandboxPaths

  // Everything a developer workstation can leak into the runner: the real
  // checkout as cwd/root under several casings, a real HERMES_HOME, a dev
  // server, and a credential.
  const hostile = (): Record<string, string> => ({
    PATH: '/usr/bin',
    HERMES_DESKTOP_CWD: FAKE_PRIMARY,
    hermes_desktop_cwd: FAKE_PRIMARY,
    Hermes_Desktop_Hermes_Root: FAKE_PRIMARY,
    HERMES_DESKTOP_HERMES_ROOT: FAKE_PRIMARY,
    HERMES_DESKTOP_USER_DATA_DIR: path.join(FAKE_PRIMARY, 'user-data'),
    hermes_desktop_user_data_dir: path.join(FAKE_PRIMARY, 'user-data'),
    HERMES_DESKTOP_DEV_SERVER: 'http://127.0.0.1:5174',
    HERMES_DESKTOP_APP_NAME: 'Hermes',
    HERMES_HOME: path.join(FAKE_PRIMARY, '.hermes'),
    hermes_home: path.join(FAKE_PRIMARY, '.hermes'),
    OPENROUTER_API_KEY: 'sk-or-not-a-real-key'
  })

  beforeEach(() => {
    root = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-e2e-app-env-'))
    sandbox = { hermesHome: path.join(root, 'hermes-home'), userDataDir: path.join(root, 'electron-user-data') }
  })

  afterEach(() => {
    fs.rmSync(root, { recursive: true, force: true })
  })

  it('resolves cwd, root, HERMES_HOME and userData to sandbox values only', () => {
    const env = buildAppEnv(sandbox, {}, hostile())

    // No casing of HERMES_DESKTOP_CWD survives, so the app falls back to its
    // own launch directory instead of the developer's checkout.
    expect(valuesFor(env, 'HERMES_DESKTOP_CWD')).toEqual([])
    expect(valuesFor(env, 'HERMES_DESKTOP_HERMES_ROOT')).toEqual([REPO_ROOT])
    expect(valuesFor(env, 'HERMES_HOME')).toEqual([sandbox.hermesHome])
    expect(valuesFor(env, 'HERMES_DESKTOP_USER_DATA_DIR')).toEqual([sandbox.userDataDir])
    expect(valuesFor(env, 'HERMES_DESKTOP_DEV_SERVER')).toEqual([])
    expect(env.HERMES_DESKTOP_APP_NAME).toMatch(/^HermesE2E-\d+$/)
    expect(env).not.toHaveProperty('OPENROUTER_API_KEY')
    expect(env.PATH).toBe('/usr/bin')

    for (const value of Object.values(env)) {
      expect(value.startsWith(FAKE_PRIMARY)).toBe(false)
    }
  })

  it('still honours explicit fixture overrides', () => {
    const workspace = path.join(root, 'workspace')

    const env = buildAppEnv(
      sandbox,
      {
        HERMES_DESKTOP_CWD: workspace,
        HERMES_DESKTOP_BOOT_FAKE: '1',
        HERMES_DESKTOP_SKIP_QUIT_CONFIRM: '0'
      },
      hostile()
    )

    expect(valuesFor(env, 'HERMES_DESKTOP_CWD')).toEqual([workspace])
    expect(env.HERMES_DESKTOP_BOOT_FAKE).toBe('1')
    expect(env.HERMES_DESKTOP_SKIP_QUIT_CONFIRM).toBe('0')
    expect(valuesFor(env, 'HERMES_HOME')).toEqual([sandbox.hermesHome])
  })
})
