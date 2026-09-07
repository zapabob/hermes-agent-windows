/**
 * Command-palette security contracts (Windows Workstation Edition).
 *
 * CodeGraph 2026-09-08:
 *   - Owner: apps/desktop command-palette + store/command-palette
 *   - Defaults: nav.commandPalette → mod+k + mod+p (Ctrl+P gap-fill)
 *   - Forbidden: palette-specific subprocess / credential / approval bypass
 *
 * Palette is discovery → existing dispatcher. Dangerous posture changes
 * (YOLO) and gateway restart must call existing store/system authorities —
 * never spawn a parallel exec path.
 */

/** Default chords for `nav.commandPalette` (must include Ctrl/Cmd+P). */
export const COMMAND_PALETTE_DEFAULT_COMBOS = ['mod+k', 'mod+p'] as const

/**
 * Palette action ids that change security posture or restart processes.
 * They remain allowed as discovery doors onto *existing* authorities only.
 */
export const DANGEROUS_PALETTE_ACTION_IDS = [
  'session.yolo',
  'cc-restart-gateway'
] as const

export type DangerousPaletteActionId = (typeof DANGEROUS_PALETTE_ACTION_IDS)[number]

export function commandPaletteDefaultsIncludeCtrlP(
  defaults: readonly string[] = COMMAND_PALETTE_DEFAULT_COMBOS
): boolean {
  return defaults.includes('mod+p')
}

export function isDangerousPaletteActionId(id: string): boolean {
  return (DANGEROUS_PALETTE_ACTION_IDS as readonly string[]).includes(id)
}

/**
 * Contract: selecting a palette row is not a host shell exec.
 * Desktop palette items navigate, toggle stores, or RPC through existing
 * gateways — they must never invent a palette-local subprocess.
 */
export function paletteSelectIsNotHostExec(kind: 'navigate' | 'toggle' | 'rpc' | 'run' | 'unavailable' | 'exec'): boolean {
  return kind !== 'exec'
}

/** Allowed authority labels for dangerous palette actions. */
export const DANGEROUS_PALETTE_ALLOWED_AUTHORITIES = [
  'setYoloEnabled',
  'runGatewayRestart'
] as const

export function dangerousPaletteAuthorityAllowed(authority: string): boolean {
  return (DANGEROUS_PALETTE_ALLOWED_AUTHORITIES as readonly string[]).includes(authority)
}
