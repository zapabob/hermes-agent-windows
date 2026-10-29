import { hermesApi, sessionFileOwnerScope } from '@/api/client'
import type {
  HermesConnection,
  HermesReadDirResult,
  HermesReadFileTextResult,
  HermesSelectPathsOptions
} from '@/global'
import { $connection } from '@/store/session'
import type { DesktopThemeSource } from '@/themes/types'

export type DesktopFsSourceScope = DesktopThemeSource

export interface DesktopFsRemotePicker {
  selectPaths: (options?: HermesSelectPathsOptions) => Promise<string[]>
}

let remotePicker: DesktopFsRemotePicker | null = null

export function setDesktopFsRemotePicker(next: DesktopFsRemotePicker | null) {
  remotePicker = next
}

function connectionCacheKey(connection: HermesConnection | null) {
  if (!connection) {
    return 'local:'
  }

  // A profile belongs to a registry connection, not the whole Desktop. The
  // registry id is the isolation boundary, including for SSH connections; the
  // stable host identity below is only the fallback for legacy connections.
  if (connection.connectionId) {
    return `connection:${connection.connectionId}:${connection.profile || ''}`
  }

  const target =
    connection.remoteKind === 'ssh'
      ? connection.remoteIdentity || connection.remoteHost || ''
      : connection.baseUrl || ''

  return `${connection.mode || 'local'}:${connection.remoteKind || ''}:${connection.profile || ''}:${target}`
}

export function desktopFsCacheKey(connection: HermesConnection | null = $connection.get()) {
  return connectionCacheKey(connection)
}

export function isDesktopFsRemoteMode() {
  return $connection.get()?.mode === 'remote'
}

// Active profile for FS/git REST calls. Without it the Electron api bridge
// hits the primary (local) backend even when the user switched to a remote profile.
export function desktopFsProfile(): string | undefined {
  return $connection.get()?.profile || undefined
}

function sameAsActiveScope(scope: DesktopFsSourceScope): boolean {
  const active = $connection.get()
  const activeConnection = active?.connectionId?.trim() || null
  const activeProfile = active?.profile?.trim() || 'default'

  return (
    (scope.connectionId?.trim() || null) === activeConnection && (scope.profile.trim() || 'default') === activeProfile
  )
}

function fsPath(endpoint: string, filePath: string) {
  return `/api/fs/${endpoint}?path=${encodeURIComponent(filePath)}`
}

function bridge() {
  const desktop = window.hermesDesktop

  if (!desktop) {
    throw new Error('Hermes Desktop bridge is unavailable')
  }

  return desktop
}

function remoteFsApi<T>(path: string, body?: Record<string, unknown>, scope?: DesktopFsSourceScope): Promise<T> {
  const request = body
    ? { body, method: 'POST', path, profile: scope?.profile.trim() || desktopFsProfile() }
    : { path, profile: scope?.profile.trim() || desktopFsProfile() }

  if (scope) {
    return bridge().api<T>({ ...request, connectionId: scope.connectionId })
  }

  return hermesApi<T>(request)
}

export async function readDesktopDir(path: string): Promise<HermesReadDirResult> {
  if (!isDesktopFsRemoteMode()) {
    return bridge().readDir(path)
  }

  return remoteFsApi<HermesReadDirResult>(fsPath('list', path))
}

export interface DesktopFsSessionScope {
  connectionId?: null | string
  profile?: string
  sessionId?: null | string
}

/** Where a gateway file request goes. A session id travels only with the profile
 *  that owns it; with no known owner the request names no session and goes to
 *  the window's ambient profile. */
function fsSessionRoute(scope?: DesktopFsSessionScope): {
  owner?: DesktopFsSourceScope
  sessionId?: string
} {
  const sessionId = scope?.sessionId?.trim() || undefined

  if (scope?.profile) {
    return {
      owner: { connectionId: scope.connectionId ?? null, profile: scope.profile },
      sessionId
    }
  }

  if (!sessionId) {
    return {}
  }

  const owner = sessionFileOwnerScope(sessionId)

  return owner ? { owner, sessionId } : {}
}

export async function readDesktopFileText(
  path: string,
  scope?: DesktopFsSessionScope
): Promise<HermesReadFileTextResult> {
  if (!isDesktopFsRemoteMode()) {
    return bridge().readFileText(path)
  }

  const route = fsSessionRoute(scope)
  const session = route.sessionId ? `&session_id=${encodeURIComponent(route.sessionId)}` : ''

  return remoteFsApi<HermesReadFileTextResult>(
    `/api/fs/read-text?path=${encodeURIComponent(path)}${session}`,
    undefined,
    route.owner
  )
}

// Save UTF-8 text back to a file. Local writes go through the hardened Electron
// IPC; remote writes hit the dashboard's POST /api/fs/write-text (same path
// hardening, parent-must-exist, size cap) so the editor behaves identically in
// both modes. Stale-on-disk detection is the caller's job (re-read before save).
export async function writeDesktopFileText(
  path: string,
  content: string,
  scope?: DesktopFsSessionScope
): Promise<{ path: string }> {
  const desktop = bridge()

  if (!isDesktopFsRemoteMode()) {
    if (!desktop.writeTextFile) {
      throw new Error('Saving is not available')
    }

    return desktop.writeTextFile(path, content)
  }

  const route = fsSessionRoute(scope)

  const result = await remoteFsApi<{ ok?: boolean; path?: string }>(
    '/api/fs/write-text',
    {
      content,
      path,
      ...(route.sessionId ? { session_id: route.sessionId } : {})
    },
    route.owner
  )

  return { path: result.path || path }
}

export async function readDesktopFileDataUrl(path: string, scope?: DesktopFsSourceScope): Promise<string> {
  // A wallpaper's source scope is immutable. Even when the active shell is
  // local, a non-active connection must be read through its authenticated API
  // route rather than falling through to this machine's Electron filesystem.
  if (!isDesktopFsRemoteMode() && (!scope || sameAsActiveScope(scope))) {
    return bridge().readFileDataUrl(path)
  }

  const result = await remoteFsApi<string | { dataUrl?: string }>(fsPath('read-data-url', path), undefined, scope)

  return typeof result === 'string' ? result : result.dataUrl || ''
}

/**
 * Read a composer image local-shell first, even when the active agent is
 * remote. Picker, clipboard, and OS-drop paths belong to this machine; in-app
 * project-tree paths may belong only to the gateway and fall back there.
 */
export async function readDesktopFileDataUrlLocalFirst(path: string): Promise<string> {
  try {
    const local = await window.hermesDesktop?.readFileDataUrl?.(path)

    if (local) {
      return local
    }
  } catch (error) {
    if (!isDesktopFsRemoteMode()) {
      throw error
    }

    // Not on this machine (or unreadable locally) — try the active gateway.
  }

  return readDesktopFileDataUrl(path)
}

export async function desktopGitRoot(path: string): Promise<string | null> {
  const desktop = bridge()

  if (!isDesktopFsRemoteMode()) {
    return desktop.gitRoot ? desktop.gitRoot(path) : null
  }

  return (await remoteFsApi<{ root: string | null }>(fsPath('git-root', path))).root
}

export async function desktopDefaultCwd(): Promise<{ branch: string; cwd: string } | null> {
  if (!isDesktopFsRemoteMode()) {
    return null
  }

  return remoteFsApi<{ branch: string; cwd: string }>('/api/fs/default-cwd')
}

// Reveal a path in the OS file manager (Finder / Explorer / Files). Local only.
export async function revealDesktopPath(path: string): Promise<void> {
  await bridge().revealPath?.(path)
}

// Rename a file/folder in place; returns the new absolute path. Local only.
export async function renameDesktopPath(path: string, newName: string): Promise<string> {
  const desktop = bridge()

  if (!desktop.renamePath) {
    throw new Error('Rename is not available')
  }

  const result = await desktop.renamePath(path, newName)

  return result.path
}

// Move a file/folder to the OS trash (recoverable). Local only.
export async function trashDesktopPath(path: string): Promise<void> {
  const desktop = bridge()

  if (!desktop.trashPath) {
    throw new Error('Delete is not available')
  }

  await desktop.trashPath(path)
}

export async function copyTextToClipboard(text: string): Promise<void> {
  await bridge().writeClipboard(text)
}

// Working-tree-vs-HEAD diff for one file. Empty when unchanged / not a repo.
// Remote gateway → backend git (/api/git/file-diff); local → Electron git.
export async function desktopFileDiff(repoRoot: string, filePath: string): Promise<string> {
  if (isDesktopFsRemoteMode()) {
    const result = await remoteFsApi<{ diff: string }>(
      `/api/git/file-diff?path=${encodeURIComponent(repoRoot)}&file=${encodeURIComponent(filePath)}`
    )

    return result.diff || ''
  }

  const git = bridge().git

  return git?.fileDiff ? git.fileDiff(repoRoot, filePath) : ''
}

export async function selectDesktopPaths(options?: HermesSelectPathsOptions): Promise<string[]> {
  const desktop = bridge()
  const profile = desktopFsProfile()
  const localOptions = profile ? { ...options, profile } : options

  if (!isDesktopFsRemoteMode()) {
    return desktop.selectPaths(localOptions)
  }

  if (!options?.directories) {
    return desktop.selectPaths(localOptions)
  }

  return remotePicker ? remotePicker.selectPaths({ ...options, multiple: false }) : []
}
