// The Hermes-owned folders `ctx.files` must never reach or be granted over.
// One resolver owns the list so the door and its tests agree: the resolved
// HERMES_HOME, every spelling of the default home this platform (or an older
// install) may use, each home's `profiles/` tree (every profile's config,
// `.env`, auth and sessions) and its `vault/` (encrypted autofill secrets).
// plugin-files.ts adds the app's userData folder and system roots, and the
// sensitive-file rules still apply inside any granted folder.

import path from 'node:path'

export interface PluginFilesRootsInput {
  /** The resolved HERMES_HOME of this Desktop (may itself be a profile dir). */
  hermesHome: string
  /** The user's home directory. */
  home: string
  /** `%LOCALAPPDATA%` (Windows default Hermes home lives under it). */
  localAppData?: string
}

// Profiles are HOME-anchored: `<root>/profiles/<name>` is a HERMES_HOME of its
// own, so a Desktop pointed at a profile still has to protect the root above it.
const profileParent = (home: string): null | string => {
  const parent = path.dirname(home)

  return path.basename(parent).toLowerCase() === 'profiles' ? path.dirname(parent) : null
}

const withinHome = (home: string): string[] => [home, path.join(home, 'profiles'), path.join(home, 'vault')]

export function pluginFilesProtectedRoots({ hermesHome, home, localAppData }: PluginFilesRootsInput): string[] {
  const homes = [hermesHome, path.join(home, '.hermes')]

  if (localAppData) {
    homes.push(path.join(localAppData, 'hermes'))
  }

  const owner = hermesHome ? profileParent(hermesHome) : null

  if (owner) {
    homes.push(owner)
  }

  return [...new Set(homes.filter(Boolean).flatMap(withinHome))]
}
