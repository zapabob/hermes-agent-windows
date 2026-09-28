import { describe, expect, it } from 'vitest'

import { stripInheritedDesktopOverrides } from './app-env'

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
    // Windows env names are case-insensitive, so a lower-cased copy would
    // still reach the app.
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
