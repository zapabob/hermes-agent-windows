import * as path from 'node:path'

const DESKTOP_ROOT = path.resolve(import.meta.dirname, '..')
const REPO_ROOT = path.resolve(DESKTOP_ROOT, '..', '..')

// ─── Credential stripping (matches launch.spec.ts) ──────────────────────

const CREDENTIAL_SUFFIXES: string[] = [
  '_API_KEY',
  '_TOKEN',
  '_SECRET',
  '_PASSWORD',
  '_CREDENTIALS',
  '_ACCESS_KEY',
  '_PRIVATE_KEY',
  '_OAUTH_TOKEN'
]

const CREDENTIAL_NAMES = new Set([
  'ANTHROPIC_BASE_URL',
  'ANTHROPIC_TOKEN',
  'AWS_ACCESS_KEY_ID',
  'AWS_SECRET_ACCESS_KEY',
  'AWS_SESSION_TOKEN',
  'CUSTOM_API_KEY',
  'GEMINI_BASE_URL',
  'OPENAI_BASE_URL',
  'OPENROUTER_BASE_URL',
  'OLLAMA_BASE_URL',
  'GROQ_BASE_URL',
  'XAI_BASE_URL'
])

function isCredentialEnvVar(name: string): boolean {
  if (CREDENTIAL_NAMES.has(name)) {
    return true
  }

  return CREDENTIAL_SUFFIXES.some(suffix => name.endsWith(suffix))
}

function stripCredentials(env: Record<string, string | undefined>): Record<string, string> {
  const clean: Record<string, string> = {}

  for (const [key, value] of Object.entries(env)) {
    if (!value) {
      continue
    }

    if (isCredentialEnvVar(key)) {
      continue
    }

    clean[key] = value
  }

  return clean
}

// ─── Inherited desktop overrides ────────────────────────────────────────

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

// Windows env names are case-insensitive: an inherited `hermes_home` next to
// the sandbox `HERMES_HOME` leaves the child's effective value to chance.
function withoutCaseVariantsOf(env: Record<string, string>, keys: string[]): Record<string, string> {
  const shadowed = new Set(keys.map(key => key.toUpperCase()))
  const clean: Record<string, string> = {}

  for (const [key, value] of Object.entries(env)) {
    if (!shadowed.has(key.toUpperCase())) {
      clean[key] = value
    }
  }

  return clean
}

// ─── Env building ──────────────────────────────────────────────────────

export interface SandboxPaths {
  hermesHome: string
  userDataDir: string
}

/**
 * Build the environment for the Electron app process.
 *
 * Key env vars:
 *  - HERMES_HOME → sandbox hermes-home (isolated config/sessions)
 *  - HERMES_DESKTOP_USER_DATA_DIR → sandbox electron-user-data
 *  - HERMES_DESKTOP_IGNORE_EXISTING=1 → don't pick up `hermes` from PATH
 *    (we want the dev checkout at REPO_ROOT)
 *  - HERMES_DESKTOP_HERMES_ROOT → REPO_ROOT (dev checkout resolution)
 *  - HERMES_DESKTOP_APP_NAME → unique-ish per test (avoids single-instance lock)
 *  - every other inherited HERMES_DESKTOP_* is dropped
 *  - XDG_RUNTIME_DIR → ensure Electron has a writable runtime dir on Linux
 *
 * `inherited` defaults to the runner's environment; tests pass their own.
 */
export function buildAppEnv(
  sandbox: SandboxPaths,
  extra: Record<string, string> = {},
  inherited: Record<string, string | undefined> = process.env
): Record<string, string> {
  const clean = stripInheritedDesktopOverrides(stripCredentials(inherited))

  // XDG_RUNTIME_DIR is needed for Electron on Linux when running in a
  // headless/CI context — without it the zygote may fail to initialize.
  if (!clean.XDG_RUNTIME_DIR && inherited.XDG_RUNTIME_DIR) {
    clean.XDG_RUNTIME_DIR = inherited.XDG_RUNTIME_DIR
  }

  // DISPLAY — needed for Electron to open a window.
  if (!clean.DISPLAY && inherited.DISPLAY) {
    clean.DISPLAY = inherited.DISPLAY
  }

  const overrides: Record<string, string> = {
    HERMES_HOME: sandbox.hermesHome,
    HERMES_DESKTOP_USER_DATA_DIR: sandbox.userDataDir,
    HERMES_DESKTOP_IGNORE_EXISTING: '1',
    HERMES_DESKTOP_HERMES_ROOT: REPO_ROOT,
    HERMES_DESKTOP_APP_NAME: `HermesE2E-${Date.now()}`,
    // `app.close()` in teardown must exit even when a spec leaves a turn
    // mid-flight — otherwise the quit confirmation waits on a click that no
    // one is there to make, and the worker dies on a teardown timeout.
    HERMES_DESKTOP_SKIP_QUIT_CONFIRM: '1',
    ...extra
  }

  return {
    ...withoutCaseVariantsOf(clean, Object.keys(overrides)),
    ...overrides
  }
}
