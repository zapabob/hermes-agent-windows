/**
 * Pure helpers for choosing a remote URL during passive update checks.
 *
 * An install can end up with an SSH origin whose key is FIDO2/passkey-backed.
 * A background `git fetch origin` can then trigger an unexplained hardware-touch
 * prompt. Passive checks translate GitHub SSH remotes to HTTPS and refuse other
 * SSH transports. Active update/apply flows are left unchanged.
 *
 * Extracted from main.ts so the security-critical remote detection is unit
 * testable without booting Electron (main.ts requires('electron') at load).
 */

const OFFICIAL_REPO_HTTPS_URL = 'https://github.com/NousResearch/hermes-agent.git'
const OFFICIAL_REPO_CANONICAL = 'github.com/nousresearch/hermes-agent'

// Normalize common GitHub remote URL forms to `host/owner/repo` (lowercased,
// no trailing slash, no .git suffix) so SSH and HTTPS forms of the same repo
// compare equal.
function canonicalGitHubRemote(url) {
  if (!url) {
    return ''
  }

  let value = String(url).trim()

  const scpLike = /^git@github\.com:(.+)$/i.exec(value)
  const sshUrl = /^ssh:\/\/git@github\.com\/(.+)$/i.exec(value)

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

  return value.startsWith('git@') || value.startsWith('ssh://')
}

function isOfficialSshRemote(url) {
  return isSshRemote(url) && canonicalGitHubRemote(url) === OFFICIAL_REPO_CANONICAL
}

/**
 * Choose the transport used by an automatic, passive update check.
 *
 * Returning `origin` preserves non-SSH behavior. A GitHub SSH URL is mapped to
 * the same HTTPS repository URL, so no SSH agent or FIDO2 authenticator can be
 * consulted. The caller also disables Git credential helpers for that anonymous
 * probe. Other SSH hosts fail closed with `null`: a passive check may report
 * itself unavailable, but it must never request native credentials.
 */
function resolvePassiveUpdateRemote(url) {
  if (!isSshRemote(url)) {
    return 'origin'
  }

  const value = String(url).trim()

  const githubRepo =
    /^git@github\.com:([^/]+\/[^/]+?)(?:\.git)?\/?$/i.exec(value) ||
    /^ssh:\/\/git@github\.com\/([^/]+\/[^/]+?)(?:\.git)?\/?$/i.exec(value)

  return githubRepo ? `https://github.com/${githubRepo[1]}.git` : null
}

export {
  canonicalGitHubRemote,
  isOfficialSshRemote,
  isSshRemote,
  OFFICIAL_REPO_CANONICAL,
  OFFICIAL_REPO_HTTPS_URL,
  resolvePassiveUpdateRemote
}
