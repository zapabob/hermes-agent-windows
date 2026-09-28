/**
 * The runner's own HERMES_DESKTOP_* values describe the developer's desktop,
 * not the sandbox. HERMES_DESKTOP_CWD in particular outranks every fallback
 * in resolveHermesCwd(), so an inherited value points the sandboxed app's
 * sessions, composer git status and worktree actions at the developer's real
 * checkout. Launch settings a spec needs must be passed explicitly.
 */
const DESKTOP_OVERRIDE_PREFIX = 'HERMES_DESKTOP_'

export function stripInheritedDesktopOverrides(env: Record<string, string>): Record<string, string> {
  const clean: Record<string, string> = {}

  for (const [key, value] of Object.entries(env)) {
    if (key.toUpperCase().startsWith(DESKTOP_OVERRIDE_PREFIX)) {
      continue
    }

    clean[key] = value
  }

  return clean
}
