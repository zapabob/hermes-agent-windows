import { describe, expect, it } from 'vitest'

import { KEYBIND_ACTIONS } from '@/lib/keybinds/actions'
import {
  COMMAND_PALETTE_DEFAULT_COMBOS,
  commandPaletteDefaultsIncludeCtrlP,
  dangerousPaletteAuthorityAllowed,
  DANGEROUS_PALETTE_ACTION_IDS,
  isDangerousPaletteActionId,
  paletteSelectIsNotHostExec
} from '@/lib/palette-security'

describe('palette-security (Ctrl+P / dangerous-action)', () => {
  it('ships Ctrl/Cmd+P alongside Ctrl/Cmd+K for nav.commandPalette', () => {
    const meta = KEYBIND_ACTIONS.find(a => a.id === 'nav.commandPalette')
    expect(meta).toBeTruthy()
    expect(commandPaletteDefaultsIncludeCtrlP(meta!.defaults)).toBe(true)
    for (const combo of COMMAND_PALETTE_DEFAULT_COMBOS) {
      expect(meta!.defaults).toContain(combo)
    }
  })

  it('treats palette select as non-host-exec for discovery kinds', () => {
    expect(paletteSelectIsNotHostExec('navigate')).toBe(true)
    expect(paletteSelectIsNotHostExec('toggle')).toBe(true)
    expect(paletteSelectIsNotHostExec('rpc')).toBe(true)
    expect(paletteSelectIsNotHostExec('run')).toBe(true)
    expect(paletteSelectIsNotHostExec('unavailable')).toBe(true)
    expect(paletteSelectIsNotHostExec('exec')).toBe(false)
  })

  it('dangerous palette actions must use existing authorities only', () => {
    expect(isDangerousPaletteActionId('session.yolo')).toBe(true)
    expect(isDangerousPaletteActionId('cc-restart-gateway')).toBe(true)
    expect(DANGEROUS_PALETTE_ACTION_IDS.length).toBeGreaterThan(0)
    expect(dangerousPaletteAuthorityAllowed('setYoloEnabled')).toBe(true)
    expect(dangerousPaletteAuthorityAllowed('runGatewayRestart')).toBe(true)
    expect(dangerousPaletteAuthorityAllowed('spawnShell')).toBe(false)
  })
})
