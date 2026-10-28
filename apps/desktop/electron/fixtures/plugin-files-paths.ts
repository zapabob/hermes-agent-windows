/**
 * Win32 CI mixes 8.3 (`RUNNER~1`) and long (`runneradmin`) TEMP spellings.
 * Normalize fixtures and comparisons so grants / trash / swap mocks agree.
 */
import fs from 'node:fs'

export function nativeRealPath(target: string): string {
  return fs.realpathSync.native(target)
}

export function sameFsPath(left: fs.PathLike, right: string): boolean {
  const a = String(left)

  if (a === right) {
    return true
  }

  if (process.platform !== 'win32') {
    return false
  }

  const fold = (value: string) => value.replace(/\//g, '\\').toLowerCase()

  if (fold(a) === fold(right)) {
    return true
  }

  try {
    return fold(fs.realpathSync.native(a)) === fold(fs.realpathSync.native(right))
  } catch {
    return false
  }
}
