/**
 * Pure helpers for choosing a remote URL during passive update checks.
 *
 * An install can end up with an SSH origin whose key is FIDO2/passkey-backed.
 * A background `git fetch origin` can then trigger an unexplained hardware-touch
 * prompt. Passive checks use explicit anonymous HTTP(S), translate recognized
 * GitHub SSH remotes, and refuse every other transport. Active update/apply
 * flows are left unchanged so each operator keeps their own Git identity.
 *
 * Extracted from main.ts so the security-critical remote detection is unit
 * testable without booting Electron (main.ts requires('electron') at load).
 */

const OFFICIAL_REPO_HTTPS_URL = 'https://github.com/NousResearch/hermes-agent.git'
const OFFICIAL_REPO_CANONICAL = 'github.com/nousresearch/hermes-agent'

function passiveGitArgs(args) {
  return [
    '-c',
    'credential.helper=',
    '-c',
    'core.askPass=',
    '-c',
    'core.fsmonitor=false',
    '-c',
    'core.untrackedCache=false',
    '-c',
    'http.proxy=',
    '-c',
    'https.proxy=',
    ...args
  ]
}

function passiveGitEnvironment(base = {}, nullDevice = '/dev/null', isolatedHome = '', ceiling = isolatedHome) {
  // Build an allowlisted process environment instead of trying to enumerate
  // every Git/libcurl credential input. Windows environment keys are
  // case-insensitive, while JavaScript object keys are not; copying then
  // deleting uppercase spellings leaves mixed-case aliases active.
  const allowed = new Set([
    'COMSPEC',
    'LANG',
    'LC_ALL',
    'NUMBER_OF_PROCESSORS',
    'PATH',
    'PATHEXT',
    'SSL_CERT_DIR',
    'SSL_CERT_FILE',
    'SYSTEMROOT',
    'TEMP',
    'TMP',
    'TMPDIR',
    'WINDIR'
  ])

  const env = {}

  for (const [key, value] of Object.entries(base)) {
    if (allowed.has(key.toUpperCase())) {
      env[key] = value
    }
  }

  return {
    ...env,
    GIT_TERMINAL_PROMPT: '0',
    GCM_INTERACTIVE: 'Never',
    GIT_ASKPASS: '',
    SSH_ASKPASS: '',
    SSH_ASKPASS_REQUIRE: 'never',
    GIT_ALLOW_PROTOCOL: 'https:http',
    GIT_CONFIG_NOSYSTEM: '1',
    GIT_CONFIG_SYSTEM: nullDevice,
    GIT_CONFIG_GLOBAL: nullDevice,
    GIT_CONFIG_COUNT: '0',
    GIT_CONFIG_PARAMETERS: '',
    GIT_DISCOVERY_ACROSS_FILESYSTEM: '0',
    GIT_CEILING_DIRECTORIES: ceiling || nullDevice,
    HOME: isolatedHome || nullDevice,
    USERPROFILE: isolatedHome || nullDevice,
    CURL_HOME: isolatedHome || nullDevice,
    NETRC: nullDevice,
    HTTP_PROXY: '',
    HTTPS_PROXY: '',
    ALL_PROXY: '',
    NO_PROXY: ''
  }
}

// Normalize common GitHub remote URL forms to `host/owner/repo` (lowercased,
// no trailing slash, no .git suffix) so SSH and HTTPS forms of the same repo
// compare equal.
function canonicalGitHubRemote(url) {
  if (!url) {
    return ''
  }

  let value = String(url).trim()

  const scpLike = /^[^/@\s]+@github\.com:(.+)$/i.exec(value)
  const sshUrl = /^ssh:\/\/[^/@\s]+@github\.com\/(.+)$/i.exec(value)

  if (scpLike) {
    value = `github.com/${scpLike[1]}`
  } else if (sshUrl) {
    value = `github.com/${sshUrl[1]}`
  } else {
    try {
      const parsed = new URL(value)

      if (parsed.hostname && parsed.pathname) {
        value = `${parsed.hostname}${parsed.pathname}`
      }
    } catch {
      // Leave non-URL forms unchanged.
    }
  }

  value = value.trim().replace(/\/+$/, '')

  if (value.endsWith('.git')) {
    value = value.slice(0, -4)
  }

  return value.toLowerCase()
}

function isSshRemote(url) {
  const value = String(url || '')
    .trim()
    .toLowerCase()

  return value.startsWith('ssh://') || /^[^/@\s]+@[^/:\s]+:/.test(value)
}

function isOfficialSshRemote(url) {
  return isSshRemote(url) && canonicalGitHubRemote(url) === OFFICIAL_REPO_CANONICAL
}

/**
 * Choose the transport used by an automatic, passive update check.
 *
 * A GitHub SSH URL is mapped to the same anonymous HTTPS repository URL. An
 * explicit HTTP(S) URL is returned unchanged. Everything else fails closed:
 * remote helpers, scp aliases and local paths can hide an authentication or
 * executable boundary and therefore are not valid passive transports.
 */
function resolvePassiveUpdateRemote(url) {
  const value = String(url).trim()

  if (!value) {
    return null
  }

  const httpAuthority = /^https?:\/\/([^/?#]*)/i.exec(value)

  if (httpAuthority?.[1].includes('@')) {
    return null
  }

  try {
    const parsed = new URL(value)

    if (
      (parsed.protocol === 'http:' || parsed.protocol === 'https:') &&
      parsed.hostname &&
      !parsed.username &&
      !parsed.password
    ) {
      return value
    }
  } catch {
    // Only explicit HTTP(S) URLs and the GitHub SSH forms below are accepted.
  }

  const githubRepo =
    /^[^/@\s]+@github\.com:([^/]+\/[^/]+?)(?:\.git)?\/?$/i.exec(value) ||
    /^ssh:\/\/[^/@\s]+@github\.com\/([^/]+\/[^/]+?)(?:\.git)?\/?$/i.exec(value)

  return githubRepo ? `https://github.com/${githubRepo[1]}.git` : null
}

export {
  canonicalGitHubRemote,
  isOfficialSshRemote,
  isSshRemote,
  OFFICIAL_REPO_CANONICAL,
  OFFICIAL_REPO_HTTPS_URL,
  passiveGitArgs,
  passiveGitEnvironment,
  resolvePassiveUpdateRemote
}
